"""
商品/账号统计日采任务

数据源（全部为已实测可用的 mtop 接口）：
- mtop.taobao.idle.pc.detail (v1.0, itemId) -> data.itemDO:
    browseCnt 浏览 / wantCnt 想要 / soldCnt 售出 / collectCnt 收藏 / favorCnt 超赞
- mtop.idle.web.user.page.nav (零参) -> module.base:
    soldCount 累计售出 / followers / following / purchaseCount / collectionCount
- mtop.idle.web.user.page.head (userId) -> module:
    shop.level / praiseRatio / reviewNum

入库：xy_item_stats_daily / xy_account_stats_daily（日粒度，唯一键幂等 upsert）。
回写：最新统计写入 xy_catalog_items.metadata.stats，供前端列表直接展示。
注意：pc.detail 直调对高频敏感（实测单账号高频会撞 USER_VALIDATE），
任务按天调度、商品间 ITEM_SLEEP 秒，单账号单轮最多 ITEM_LIMIT 件，
超出部分按 metadata.stats 最旧优先滚动覆盖。
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import date
from typing import Any, Dict, Optional

import aiohttp
from loguru import logger
from sqlalchemy import text

from common.db.session import async_session_maker
from common.utils.xianyu_utils import trans_cookies, generate_sign
from common.services.order_service import get_goofish_connector

# 单账号单轮最多采集件数（防风控；商品多的账号多天滚动覆盖）
ITEM_LIMIT = 40
# 商品间间隔秒数
ITEM_SLEEP = 3.0

STAT_KEYS = ("browseCnt", "wantCnt", "soldCnt", "collectCnt", "favorCnt")
DB_COLS = {
    "browseCnt": "browse_cnt",
    "wantCnt": "want_cnt",
    "soldCnt": "sold_cnt",
    "collectCnt": "collect_cnt",
    "favorCnt": "favor_cnt",
}


async def _h5(
    session: aiohttp.ClientSession,
    connector,
    api: str,
    ver: str,
    data_obj: dict,
    cookie: str,
    referer: str = "https://www.goofish.com/",
) -> dict:
    ts = str(int(time.time() * 1000))
    data_val = json.dumps(data_obj, separators=(",", ":"))
    ck = trans_cookies(cookie)
    token = ck.get("_m_h5_tk", "").split("_")[0] if ck.get("_m_h5_tk") else ""
    sign = generate_sign(ts, token, data_val)
    params = {
        "jsv": "2.7.2", "appKey": "34839810", "t": ts, "sign": sign, "v": ver,
        "type": "originaljson", "accountSite": "xianyu", "dataType": "json",
        "timeout": "20000", "api": api, "sessionOption": "AutoLoginOnly",
    }
    headers = {
        "accept": "application/json",
        "content-type": "application/x-www-form-urlencoded",
        "cookie": cookie,
        "Referer": referer,
        "origin": referer.rstrip("/"),
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "Chrome/138.0.0.0 Safari/537.36",
    }
    async with session.post(
        f"https://h5api.m.goofish.com/h5/{api}/{ver}/",
        params=params,
        data={"data": data_val},
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=15),
    ) as r:
        return await r.json(content_type=None)


async def _collect_account_stats(
    session: aiohttp.ClientSession, connector, account_id: str, cookie: str
) -> Optional[Dict[str, Any]]:
    """账号级统计：nav + head，失败返回 None"""
    try:
        nav = await _h5(session, connector, "mtop.idle.web.user.page.nav", "1.0", {}, cookie)
        base = ((nav.get("data") or {}).get("module") or {}).get("base") or {}
        head = await _h5(
            session, connector, "mtop.idle.web.user.page.head", "1.0",
            {"userId": account_id}, cookie,
        )
        hmod = (head.get("data") or {}).get("module") or {}
        shop = hmod.get("shop") or {}
        return {
            "sold_total": int(base.get("soldCount") or 0),
            "followers": int(base.get("followers") or 0),
            "following": int(base.get("following") or 0),
            "purchase_count": int(base.get("purchaseCount") or 0),
            "collection_count": int(base.get("collectionCount") or 0),
            "praise_ratio": int(shop.get("praiseRatio") or 0),
            "review_num": int(shop.get("reviewNum") or 0),
            "shop_level": str(shop.get("level") or ""),
        }
    except Exception as exc:
        logger.warning(f"[统计日采] 账号 {account_id} 账号级统计失败: {exc}")
        return None


async def _upsert_account_stats(acct: str, today: str, stats: Dict[str, Any]) -> None:
    col_names = ", ".join(stats.keys())
    col_params = ", ".join(f":{k}" for k in stats)
    set_clause = ", ".join(f"{k}=excluded.{k}" for k in stats)
    params = {"account_id": acct, "stat_date": today, **stats}
    async with async_session_maker() as s:
        await s.execute(text(
            f"INSERT INTO xy_account_stats_daily (account_id, stat_date, {col_names}) "
            f"VALUES (:account_id, :stat_date, {col_params}) "
            f"ON CONFLICT(account_id, stat_date) DO UPDATE SET {set_clause}"
        ), params)
        await s.commit()


async def _upsert_item_stats(acct: str, item_id: str, today: str, itemDO: dict) -> None:
    """只写有值的统计键"""
    present = [k for k in STAT_KEYS if itemDO.get(k) is not None]
    if not present:
        return
    col_names = ", ".join(DB_COLS[k] for k in present)
    col_params = ", ".join(f":{DB_COLS[k]}" for k in present)
    set_clause = ", ".join(f"{DB_COLS[k]}=excluded.{DB_COLS[k]}" for k in present)
    params = {
        "account_id": acct, "item_id": item_id, "stat_date": today,
        **{DB_COLS[k]: int(itemDO.get(k) or 0) for k in present},
    }
    async with async_session_maker() as s:
        await s.execute(text(
            f"INSERT INTO xy_item_stats_daily (account_id, item_id, stat_date, {col_names}) "
            f"VALUES (:account_id, :item_id, :stat_date, {col_params}) "
            f"ON CONFLICT(account_id, item_id, stat_date) DO UPDATE SET {set_clause}"
        ), params)
        await s.commit()


async def _writeback_item_metadata(item_pk: int, itemDO: dict) -> None:
    """最新统计回写 xy_catalog_items.metadata.stats（前端列表直读，不再发请求）"""
    stats = {k: itemDO.get(k) for k in STAT_KEYS if itemDO.get(k) is not None}
    if not stats:
        return
    async with async_session_maker() as s:
        row = (await s.execute(
            text("SELECT metadata FROM xy_catalog_items WHERE id = :pk"),
            {"pk": item_pk},
        )).one_or_none()
        if not row:
            return
        try:
            meta = json.loads(row[0]) if row[0] else {}
        except Exception:
            meta = {}
        meta["stats"] = {"value": stats, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        await s.execute(
            text("UPDATE xy_catalog_items SET metadata = :meta WHERE id = :pk"),
            {"meta": json.dumps(meta, ensure_ascii=False), "pk": item_pk},
        )
        await s.commit()


async def _pick_items_for_account(pk: int, limit: int):
    """选本轮要采的商品：无 stats 的优先，其次 metadata.stats.at 最旧的"""
    async with async_session_maker() as s:
        rows = (await s.execute(text(
            "SELECT id, item_id, metadata FROM xy_catalog_items "
            "WHERE account_id = :pk "
            "AND CAST(json_extract(json_extract(metadata, '$.detail'), '$.item_status') AS TEXT) = '0' "
            "ORDER BY (metadata IS NULL OR json_extract(metadata, '$.stats') IS NULL) DESC, "
            "json_extract(metadata, '$.stats.at') ASC "
            "LIMIT :limit"
        ), {"pk": pk, "limit": limit})).all()
    return rows


async def run_stats_daily_task(max_items_per_account: int = ITEM_LIMIT) -> dict:
    """任务入口：遍历启用账号 -> 账号级统计 + 商品级 pc.detail"""
    today = date.today().isoformat()
    summary = {"accounts": 0, "items": 0, "item_errors": 0, "account_errors": 0}
    connector = get_goofish_connector()

    async with async_session_maker() as s:
        accounts = (await s.execute(text(
            "SELECT id, account_id, cookie FROM xy_accounts "
            "WHERE status NOT IN ('inactive','disabled','suspended','deleted') "
            "AND cookie IS NOT NULL AND cookie != ''"
        ))).all()

    async with aiohttp.ClientSession(
        connector=connector, connector_owner=False, cookie_jar=aiohttp.DummyCookieJar()
    ) as ses:
        for pk, acct, cookie in accounts:
            summary["accounts"] += 1

            # 1) 账号级
            astats = await _collect_account_stats(ses, connector, acct, cookie)
            if astats:
                try:
                    await _upsert_account_stats(acct, today, astats)
                except Exception as exc:
                    logger.warning(f"[统计日采] 账号 {acct} 入库失败: {exc}")
                    summary["account_errors"] += 1
            else:
                summary["account_errors"] += 1
            await asyncio.sleep(2)

            # 2) 商品级
            try:
                items = await _pick_items_for_account(pk, max_items_per_account)
            except Exception as exc:
                logger.warning(f"[统计日采] 账号 {acct} 商品列表查询失败: {exc}")
                items = []
            for item_pk, item_id, _meta in items:
                try:
                    res = await _h5(ses, connector, "mtop.taobao.idle.pc.detail", "1.0",
                                    {"itemId": item_id}, cookie)
                    ret = (res.get("ret") or [""])[0]
                    itemDO = (res.get("data") or {}).get("itemDO") or {}
                    if "SUCCESS" in ret and itemDO:
                        await _upsert_item_stats(acct, item_id, today, itemDO)
                        await _writeback_item_metadata(item_pk, itemDO)
                        summary["items"] += 1
                    else:
                        summary["item_errors"] += 1
                        # 已删除/查不到的商品跳过即可，不强求
                        logger.info(f"[统计日采] 商品 {item_id} 未取到统计: {ret[:40]}")
                except Exception as exc:
                    summary["item_errors"] += 1
                    logger.warning(f"[统计日采] 商品 {item_id} 采集异常: {exc}")
                await asyncio.sleep(ITEM_SLEEP)

    logger.info(
        f"[统计日采] 完成: 账号{summary['accounts']}个 "
        f"(失败{summary['account_errors']}), 商品{summary['items']}件 (失败{summary['item_errors']})"
    )
    return summary


class StatsDailyTask:
    """统计日采任务服务（调度器循环调用的 execute 入口）"""

    async def execute(self, max_items_per_account: int = ITEM_LIMIT) -> dict:
        return await run_stats_daily_task(max_items_per_account)


# 全局实例：调度器注册引用
stats_daily_task_service = StatsDailyTask()
