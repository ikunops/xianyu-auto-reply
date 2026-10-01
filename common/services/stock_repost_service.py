"""
售罄自动重发：普通账号用「重发次数」模拟库存

背景
----
闲鱼网页版发布页没有独立库存入口，个人卖家发出来的商品库存恒为 1，卖掉一次商品就
变成「已售出」（xy_catalog_items.metadata.detail.item_status = -9）。

鱼小铺（COMMONPRO）账号可以在发布成功后用卖家接口单独改库存（见
common/services/item_stock_service.py）；个人账号没有这个能力，只能「卖掉了就重新
发一次」来模拟库存。

素材库的 stock 就是重发上限：首发算 1 次，每重发一次 +1，累计成功发布次数达到 stock
就停手。于是 stock=5 的素材，个人账号最多能卖 5 次，效果等价于鱼小铺库存 5。

判定链
------
  xy_catalog_items（item_status = -9 的已售出商品）
    → xy_publish_logs（item_id → material_id / account_id）
    → 该 (素材, 账号) 最近一次成功发布的那条，才是「当前在卖的那条」
    → 成功次数 < 素材 stock，且距上次发布超过最小间隔，才重发

安全阀
------
1. 每轮最多重发 max_items 条（默认 2），避免一次扫出大量商品把账号打爆；
2. 同一 (素材, 账号) 两次重发至少间隔 MIN_REPOST_INTERVAL_SECONDS（默认 1800 秒），
   即用户要求的「重发间隔 ≥30 分钟」；
3. 只统计 status='success' 的发布日志，失败不消耗次数；
4. dry_run=True 只报告不发布。

注：重发 = 用同一素材重新发布一条新商品（新的 item_id）。闲鱼侧对重复铺货有风控，
   标题/图片建议保持差异，间隔不要太小。
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from common.db.session import async_session_maker

# 每轮最多重发条数
MAX_REPOST_PER_RUN = 2
# 同一 (素材, 账号) 两次重发的最小间隔（秒）
MIN_REPOST_INTERVAL_SECONDS = 1800
# 闲鱼侧「已售出」商品状态码
ITEM_STATUS_SOLD_OUT = "-9"

_SOLD_OUT_SQL = """
SELECT a.account_id AS account_str, ci.item_id AS item_id
FROM xy_catalog_items ci
JOIN xy_accounts a ON a.id = ci.account_id
WHERE JSON_UNQUOTE(
        JSON_EXTRACT(
          CAST(JSON_UNQUOTE(JSON_EXTRACT(ci.metadata, '$.detail')) AS JSON),
          '$.item_status'
        )
      ) = :sold_out
"""

_LATEST_PUBLISH_SQL = """
SELECT p.material_id, p.account_id, p.item_id, p.created_at
FROM xy_publish_logs p
JOIN (
    SELECT material_id, account_id, MAX(id) AS max_id
    FROM xy_publish_logs
    WHERE status = 'success' AND material_id IS NOT NULL
    GROUP BY material_id, account_id
) g ON g.max_id = p.id
"""

_SUCCESS_COUNT_SQL = """
SELECT material_id, account_id, COUNT(*) AS cnt
FROM xy_publish_logs
WHERE status = 'success' AND material_id IS NOT NULL
GROUP BY material_id, account_id
"""

_MATERIAL_SQL = """
SELECT id, user_id, title, description, price, images, delivery_method, postage,
       address, brand, `condition`, stock, spec_name, spec_value
FROM xy_product_materials
WHERE id = :mid
"""


def _default_static_root() -> str:
    return os.environ.get("STATIC_DIR") or "/app/static"


def _material_to_item_data(row: Any) -> Dict[str, Any]:
    """把素材行拼成发布器认识的 item_data（与 backend-web 的 _material_to_dict 对齐）。"""
    images = row.images
    if isinstance(images, str):
        try:
            images = json.loads(images)
        except Exception:  # noqa: BLE001
            images = []
    return {
        "id": int(row.id),
        "material_id": int(row.id),
        "user_id": int(row.user_id),
        "title": row.title,
        "description": row.description,
        "price": float(row.price) if row.price is not None else 0,
        "original_price": None,
        "category": None,
        "images": images or [],
        "delivery_method": row.delivery_method or "pickup",
        "postage": float(row.postage) if row.postage is not None else 0,
        "address": row.address,
        "brand": row.brand,
        "condition": row.condition or "全新",
        "stock": int(row.stock) if row.stock is not None else 9999,
        "spec_name": row.spec_name or "份数",
        "spec_value": row.spec_value or "1份",
    }


async def _load_sold_out(session: AsyncSession) -> set:
    """已售出商品集合：{(闲鱼账号串, item_id)}"""
    rows = (await session.execute(text(_SOLD_OUT_SQL), {"sold_out": ITEM_STATUS_SOLD_OUT})).all()
    return {(str(r[0]), str(r[1])) for r in rows}


async def _load_success_counts(session: AsyncSession) -> Dict[Any, int]:
    """{(material_id, 闲鱼账号串): 成功发布次数}"""
    rows = (await session.execute(text(_SUCCESS_COUNT_SQL))).all()
    return {(int(r[0]), str(r[1])): int(r[2]) for r in rows}


async def collect_candidates(
    session: AsyncSession, owner_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """扫描出「已售出且重发次数还没用完」的素材清单（只读，不发布）。

    owner_id 不为 None 时只返回该用户名下的素材（非管理员手动触发时用）。
    """
    sold_out = await _load_sold_out(session)
    if not sold_out:
        return []
    counts = await _load_success_counts(session)
    latest_rows = (await session.execute(text(_LATEST_PUBLISH_SQL))).all()

    now = datetime.now()
    candidates: List[Dict[str, Any]] = []
    for material_id, account_str, item_id, created_at in latest_rows:
        material_id = int(material_id)
        account_str = str(account_str)
        item_id = str(item_id)
        # 只有「最近一次发布的那条」才是当前在卖的；它没售出说明还有货，跳过
        if (account_str, item_id) not in sold_out:
            continue
        row = (await session.execute(text(_MATERIAL_SQL), {"mid": material_id})).first()
        if not row:
            continue
        if owner_id is not None and int(row.user_id) != int(owner_id):
            continue
        stock = int(row.stock) if row.stock is not None else 9999
        success_count = counts.get((material_id, account_str), 0)
        if success_count >= stock:
            continue
        if created_at is not None:
            gap = (now - created_at).total_seconds()
            if gap < MIN_REPOST_INTERVAL_SECONDS:
                logger.info(
                    f"[售罄重发] 素材 {material_id} / 账号 {account_str} 距上次发布仅 "
                    f"{int(gap)} 秒（<{MIN_REPOST_INTERVAL_SECONDS}），本轮跳过"
                )
                continue
        candidates.append(
            {
                "material_id": material_id,
                "account_id": account_str,
                "item_id": item_id,
                "stock": stock,
                "success_count": success_count,
                "remaining": stock - success_count,
                "last_publish_at": str(created_at) if created_at else None,
                "item_data": _material_to_item_data(row),
            }
        )
    candidates.sort(key=lambda c: c["material_id"])
    return candidates


async def _run_repost(
    session: AsyncSession,
    *,
    max_items: int = MAX_REPOST_PER_RUN,
    dry_run: bool = False,
    owner_id: Optional[int] = None,
) -> Dict[str, Any]:
    """在给定会话上执行一轮扫描 + 重发。"""
    candidates = await collect_candidates(session, owner_id=owner_id)
    logger.info(f"[售罄重发] 本轮候选 {len(candidates)} 条，上限 {max_items} 条（dry_run={dry_run}）")
    for c in candidates:
        logger.info(
            f"[售罄重发] 候选 素材{c['material_id']} 账号{c['account_id']} "
            f"商品{c['item_id']} 已发布{c['success_count']}/{c['stock']} 次 剩余{c['remaining']}"
        )
    if dry_run or max_items <= 0:
        return {"candidates": candidates, "reposted": [], "failed": [], "dry_run": True}

    from common.services.publish_execution_service import execute_single_publish

    reposted: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    static_root = _default_static_root()
    for c in candidates[:max_items]:
        item_data = c["item_data"]
        try:
            result = await execute_single_publish(
                session=session,
                user_id=int(item_data.get("user_id") or 0),
                account_id=c["account_id"],
                item_data=item_data,
                static_root=static_root,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[售罄重发] 素材 {c['material_id']} 重发异常: {exc}")
            failed.append({**c, "error": str(exc)})
            continue
        if result.get("success"):
            logger.info(f"[售罄重发] 素材 {c['material_id']} 重发成功 → 新商品 {result.get('item_id')}")
            reposted.append({**c, "new_item_id": result.get("item_id"), "message": result.get("message")})
        else:
            logger.warning(f"[售罄重发] 素材 {c['material_id']} 重发失败: {result.get('message')}")
            failed.append({**c, "error": result.get("message")})
    return {"candidates": candidates, "reposted": reposted, "failed": failed, "dry_run": False}


async def run_stock_repost_once(
    session: Optional[AsyncSession] = None,
    *,
    max_items: int = MAX_REPOST_PER_RUN,
    dry_run: bool = False,
    owner_id: Optional[int] = None,
) -> Dict[str, Any]:
    """扫一轮并重发售罄商品（不传 session 时自建会话）。"""
    if session is None:
        async with async_session_maker() as own_session:
            return await _run_repost(
                own_session, max_items=max_items, dry_run=dry_run, owner_id=owner_id
            )
    return await _run_repost(session, max_items=max_items, dry_run=dry_run, owner_id=owner_id)


async def run_stock_repost_loop(interval_seconds: int, max_items: int = MAX_REPOST_PER_RUN) -> None:
    """后台常驻循环：每隔 interval_seconds 扫一轮。"""
    logger.info(f"[售罄重发] 后台任务已启动，间隔 {interval_seconds} 秒，每轮最多 {max_items} 条")
    while True:
        try:
            summary = await run_stock_repost_once(max_items=max_items)
            if summary.get("reposted") or summary.get("failed"):
                logger.info(
                    f"[售罄重发] 本轮完成：候选 {len(summary['candidates'])}，"
                    f"成功 {len(summary['reposted'])}，失败 {len(summary['failed'])}"
                )
        except asyncio.CancelledError:
            logger.info("[售罄重发] 后台任务已停止")
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[售罄重发] 本轮异常，忽略后继续: {exc}")
        await asyncio.sleep(interval_seconds)


__all__ = [
    "collect_candidates",
    "run_stock_repost_once",
    "run_stock_repost_loop",
    "MAX_REPOST_PER_RUN",
    "MIN_REPOST_INTERVAL_SECONDS",
]
