# -*- coding: utf-8 -*-
"""卡券网盘链接验活服务（批量扫描 + 单张验活 + 开关）。

配套：
- common/services/pan_link_checker.py  八网盘单链接验活
- xy_cards.link_status / last_check_at  状态落库（前端可见）
- 调度器日切换任务每天 00:00 自动扫一遍；也可用接口手动触发
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy import select, text

from common.db.session import async_session_maker
from common.models.card import Card
from common.services.pan_link_checker import check_card_text, extract_pan_links

# 验活开关与并发（并发过高容易触发网盘限流）
_SETTING_KEY_ENABLED = "link_check.enabled"
_MAX_CONCURRENCY = 4


async def is_link_check_enabled() -> bool:
    """是否启用卡券链接验活（system_settings: link_check.enabled，默认 true）。"""
    try:
        async with async_session_maker() as session:
            row = (
                await session.execute(
                    text("SELECT value FROM xy_system_settings WHERE `key` = :k"),
                    {"k": _SETTING_KEY_ENABLED},
                )
            ).first()
        if not row or row[0] is None:
            return True
        return str(row[0]).lower() in ("1", "true", "yes", "on")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"读取链接验活开关失败（默认启用）: {exc}")
        return True


async def check_one_card(user_id: Optional[int], card_id: int) -> Optional[Dict[str, Any]]:
    """验活单张卡券并落库；卡券不存在返回 None。"""
    async with async_session_maker() as session:
        card = (
            await session.execute(select(Card).where(Card.id == card_id))
        ).scalars().first()
        if card is None:
            return None
        if user_id is not None and card.user_id != user_id:
            return None
        content = " ".join(
            str(x or "") for x in (card.text_content, card.description, card.name)
        )
        result = await check_card_text(content)
        card.link_status = result["status"]
        card.last_check_at = datetime.now()
        session.add(card)
        await session.commit()
    logger.info(
        f"【卡券 {card_id}】链接验活: {result['status']} "
        f"(有效 {result['alive_count']} / 失效 {result['dead_count']})"
    )
    return result


async def check_cards(
    user_id: Optional[int] = None,
    card_ids: Optional[List[int]] = None,
    only_with_link: bool = True,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """批量验活并落库，返回汇总（含失效卡券 id 列表）。"""
    async with async_session_maker() as session:
        stmt = select(Card)
        if card_ids:
            stmt = stmt.where(Card.id.in_(list(card_ids)))
        else:
            stmt = stmt.where(Card.enabled == True)  # noqa: E712
        if user_id is not None:
            stmt = stmt.where(Card.user_id == user_id)
        cards = list((await session.execute(stmt)).scalars().all())

    # 先按"正文里有没有网盘链接"过滤，避免对纯文本卡券发无谓请求
    targets = []
    summary: Dict[str, Any] = {
        "total": 0, "alive": 0, "partial": 0, "dead": 0, "no_link": 0, "unknown": 0,
        "bad_card_ids": [],
    }
    for card in cards:
        content = " ".join(str(x or "") for x in (card.text_content, card.description, card.name))
        if only_with_link and not extract_pan_links(content):
            summary["no_link"] += 1
            continue
        targets.append((card, content))
        if limit and len(targets) >= limit:
            break

    sem = asyncio.Semaphore(_MAX_CONCURRENCY)
    results: List[tuple] = []

    async def run(card, content):
        async with sem:
            try:
                res = await check_card_text(content)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"【卡券 {card.id}】验活异常: {exc}")
                res = {"status": "unknown", "links": [], "alive_count": 0, "dead_count": 0}
            results.append((card.id, res))

    await asyncio.gather(*(run(c, t) for c, t in targets))

    async with async_session_maker() as session:
        for card_id, res in results:
            await session.execute(
                text(
                    "UPDATE xy_cards SET link_status = :s, last_check_at = :t WHERE id = :i"
                ),
                {"s": res["status"], "t": datetime.now(), "i": card_id},
            )
            summary["total"] += 1
            summary[res["status"]] = summary.get(res["status"], 0) + 1
            if res["status"] in ("partial", "dead"):
                summary["bad_card_ids"].append(card_id)
        await session.commit()

    logger.info(f"卡券链接验活完成: {summary}")
    return summary
