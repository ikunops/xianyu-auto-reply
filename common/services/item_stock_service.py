"""
发布成功后把素材库存写到闲鱼商品上（鱼小铺专用）

背景：
- 闲鱼网页版发布页没有独立库存入口，库存挂在「商品规格」里；而平台要求每个规格至少
  2 个规格值，多规格订单会带 spec_value，导致现有卡券（is_multi_spec=false）匹配不上、
  自动发货断链。所以发布流程刻意跳过规格（XIANYU_SPEC_MODE 默认关闭），代价是网页版
  发出来的商品库存恒为 1。
- 鱼小铺（bizCode=COMMONPRO）卖家另有 mtop.alibaba.idle.seller.pc.item.info.update
  接口，可以在发布完成后单独改库存。本模块就是这条补丁：发布成功 → 探测账号身份 →
  是鱼小铺就把 quantity 改成素材库存。
- 普通卖家没有这个接口（网关返回 FAIL_BIZ_IDLE_USER_UNAUTHORIZED），库存恒为 1，
  由「售罄重发」用重发次数模拟。

只改价格与库存，不动标题/图片/状态；接口要求 price 与 quantity 一并提交，故把发布
时用的价格原样回传（格式化到分，避免精度漂移）。
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional, Tuple

from loguru import logger

from common.services.seller_item_service import update_seller_item_inventory

# 身份探测结果缓存时长：同一账号 6 小时内不重复探测，避免每次发布多打两次网关
_IDENTITY_TTL_SECONDS = 6 * 3600
# account_id -> (是否鱼小铺, 过期时间戳, cookie 指纹)
_identity_cache: Dict[str, Tuple[bool, float, str]] = {}


def _cookie_fingerprint(cookie: str) -> str:
    """取 Cookie 的轻量指纹：换号/重新登录后缓存立即失效。"""
    text = cookie or ""
    return "%d:%s" % (len(text), text[-24:] if len(text) > 24 else text)


def _load_identity_checker():
    """加载账号商业身份探测函数（backend-web 侧实现）。

    延迟导入：本模块被 backend-web 的发布链路引用，导入期不碰 app.* 命名空间，
    避免调度器/脚本等无 app 包的场景 import 失败。
    """
    try:
        from app.services.seller_identity_service import check_one
        return check_one
    except Exception:  # noqa: BLE001
        return None


async def is_workbench_account(account_id: str, cookie: str) -> bool:
    """判断账号是否持有鱼小铺（COMMONPRO）商业身份，结果按账号缓存。

    探测失败（网络抖动、缺依赖等）时保守返回 False：宁可不设库存，也不要误判后
    打断已成功的发布流程。
    """
    fingerprint = _cookie_fingerprint(cookie)
    cached = _identity_cache.get(account_id)
    if cached and cached[2] == fingerprint and cached[1] > time.time():
        return cached[0]

    check_one = _load_identity_checker()
    if check_one is None:
        logger.warning("未找到 seller_identity_service，跳过鱼小铺身份探测")
        _identity_cache[account_id] = (False, time.time() + _IDENTITY_TTL_SECONDS, fingerprint)
        return False

    try:
        result = await check_one(cookie)
        enabled = bool(result.get("workbench_enabled"))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"【{account_id}】鱼小铺身份探测失败，本次不补设库存: {exc}")
        return False

    _identity_cache[account_id] = (enabled, time.time() + _IDENTITY_TTL_SECONDS, fingerprint)
    logger.info(f"【{account_id}】鱼小铺身份探测结果: workbench_enabled={enabled}")
    return enabled


def _format_price(price: Any) -> Optional[str]:
    """把价格格式化成两位小数的字符串；无法解析时返回 None（接口只改库存）。"""
    if price is None or price == "":
        return None
    try:
        return f"{float(price):.2f}"
    except (TypeError, ValueError):
        return None


async def apply_stock_after_publish(
    *,
    account_id: str,
    cookie: str,
    item_id: Any,
    stock: Any,
    price: Any = None,
    owner_id: Optional[int] = None,
    retries: int = 3,
) -> Dict[str, Any]:
    """发布成功后把素材库存写到刚发布的商品上。

    Returns:
        dict: {stock_applied: int, stock_message: str}
              stock_applied>0 表示闲鱼侧库存确实已改成该值。
    """
    try:
        stock_int = int(stock or 1)
    except (TypeError, ValueError):
        stock_int = 1

    if stock_int <= 1:
        return {"stock_applied": 0, "stock_message": ""}
    if not item_id:
        return {"stock_applied": 0, "stock_message": "未拿到商品ID，未补设库存"}
    if not cookie:
        return {"stock_applied": 0, "stock_message": "账号Cookie为空，未补设库存"}

    if not await is_workbench_account(account_id, cookie):
        return {
            "stock_applied": 0,
            "stock_message": "非鱼小铺账号（网页版无库存入口），库存由售罄重发模拟",
        }

    formatted_price = _format_price(price)
    last_message = ""
    for attempt in range(1, max(1, retries) + 1):
        result = await update_seller_item_inventory(
            account_id=account_id,
            cookie=cookie,
            item_id=str(item_id),
            quantity=stock_int,
            price=formatted_price,
            owner_id=owner_id,
        )
        if result.get("success"):
            logger.info(f"【{account_id}】商品 {item_id} 库存已补设为 {stock_int}")
            return {"stock_applied": stock_int, "stock_message": f"库存已设为 {stock_int}"}

        last_message = str(result.get("message") or "未知错误")
        # 账号级失败重试无意义（Cookie 失效/被风控），直接放弃
        if result.get("account_invalid"):
            break
        if attempt < retries:
            # 刚发布的商品在卖家平台侧可能还没建索引，稍等再试
            await asyncio.sleep(3 * attempt)

    logger.warning(f"【{account_id}】商品 {item_id} 补设库存失败: {last_message}")
    return {"stock_applied": 0, "stock_message": f"补设库存失败：{last_message}"}


__all__ = ["apply_stock_after_publish", "is_workbench_account"]
