"""闲鱼卖家平台（鱼小铺）商品接口服务

功能：
1. 拉取鱼小铺在售商品列表，含每个商品的实时库存（quantity）与商品状态（itemStatus）；
2. 更新商品价格与库存（单规格一次提交；多规格逐个 SKU 提交）。

说明：
- 本模块调用 seller.pc.* 一族接口，只有持有 bizCode=COMMONPRO「鱼小铺专业卖家工作台」
  身份的账号可用；普通卖家会被网关以 FAIL_BIZ_IDLE_USER_UNAUTHORIZED 拒绝，
  调用方需先用 seller_identity_service 判定账号身份；
- 请求必须带 idle_site_biz_code=COMMONPRO 与 seller.goofish.com 的 Origin/Referer，
  否则网关判成非法来源（见 common/services/xianyu_mtop.py 的 extra_headers 参数）。

只读列表 + 改价改库存，不做删除。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from loguru import logger

from common.services.xianyu_mtop import mtop_call

# 卖家平台商品列表接口
SELLER_ITEM_LIST_API = "mtop.alibaba.idle.seller.pc.common.item.search"
# 卖家平台商品信息更新接口（改价/改库存），单规格与多规格共用
SELLER_ITEM_UPDATE_API = "mtop.alibaba.idle.seller.pc.item.info.update"
SELLER_ITEM_LIST_VERSION = "1.0"
SELLER_ITEM_UPDATE_VERSION = "1.0"

SELLER_ORIGIN = "https://seller.goofish.com"
SELLER_REFERER = "https://seller.goofish.com/?site=COMMONPRO"
# 卖家平台商品搜索业务类型
SELLER_BIZ_TYPE = "commonPro"
# 商品状态：0 = 在售（与个人版 groupName='在售' 语义一致）
SELLER_ITEM_STATUS_ON_SALE = "0"
# 专业版卖家（COMMONPRO）鉴权请求头：缺失时服务端返回 FAIL_BIZ_IDLE_USER_UNAUTHORIZED
SELLER_BIZ_HEADERS = {
    "idle_site_biz_code": "COMMONPRO",
    "idle_user_group_member_id": "",
}
SELLER_EXTRA_PARAMS = {"spm_cnt": "a21107h.42826273.0.0"}


def _map_sku_list(raw_list: Any) -> List[Dict[str, Any]]:
    """把卖家平台多规格明细 idleItemSkuList 映射为界面友好的结构。

    Args:
        raw_list: 卖家平台返回的 idleItemSkuList（单规格商品无此字段）。
    Returns:
        list[dict]：每项含 sku_id / inventory_id / quantity / price(元) / specs。
    """
    result: List[Dict[str, Any]] = []
    if not isinstance(raw_list, list):
        return result
    for sku in raw_list:
        if not isinstance(sku, dict):
            continue
        features = sku.get("features") or {}
        price = str(features.get("priceYuan") or "").strip()
        if not price:
            cent = sku.get("priceInCent")
            if cent in (None, ""):
                cent = sku.get("price")
            try:
                price = f"{int(cent) / 100:.2f}" if cent not in (None, "") else ""
            except (ValueError, TypeError):
                price = ""
        specs = [
            {
                "name": str(prop.get("propertyText") or ""),
                "value": str(prop.get("valueText") or ""),
            }
            for prop in (sku.get("propertyList") or [])
            if isinstance(prop, dict)
        ]
        result.append(
            {
                "sku_id": str(sku.get("skuId") or ""),
                "inventory_id": str(sku.get("inventoryId") or ""),
                "quantity": sku.get("quantity", ""),
                "price": price,
                "specs": specs,
            }
        )
    return result


def map_seller_item(raw: Dict[str, Any]) -> Dict[str, Any]:
    """把卖家平台商品字段映射为与个人版一致的入库结构。

    Args:
        raw: itemSearchResponseList 中的单个商品。
    Returns:
        dict: 含 quantity（库存）与 item_status（商品状态）的商品结构。
    """
    item_id = str(raw.get("itemId") or "")
    price = str(raw.get("reservePrice") or "")
    image_url = str(raw.get("itemImageUrl") or "")
    return {
        "id": item_id,
        "title": raw.get("title", ""),
        "price": price,
        "price_text": price,
        "category_id": "",
        "auction_type": "",
        "item_status": raw.get("itemStatus", 0),
        "detail_url": "",
        "pic_info": {"url": image_url} if image_url else {},
        "detail_params": {},
        "track_params": {},
        "item_label_data": {},
        "card_type": 0,
        # 数据源标记：供入库/前端识别鱼小铺商品（改价改库存仅鱼小铺可用）
        "source": "seller",
        "item_status_desc": raw.get("itemStatusDesc", ""),
        "quantity": raw.get("quantity", ""),
        "gmt_create": raw.get("gmtCreate", ""),
        "gmt_shelf": raw.get("gmtShelf", ""),
        "item_type": raw.get("itemType", ""),
        "image_url": image_url,
        "idle_item_sku_list": _map_sku_list(raw.get("idleItemSkuList")),
    }


async def fetch_seller_items(
    *,
    account_id: str,
    cookie: str,
    owner_id: Optional[int] = None,
    page_no: int = 1,
    page_size: int = 20,
    item_status: str = SELLER_ITEM_STATUS_ON_SALE,
) -> Dict[str, Any]:
    """拉取鱼小铺指定页的商品列表。

    Args:
        account_id: 闲鱼账号标识。
        cookie: 账号 Cookie。
        owner_id: 账号所属用户 ID，令牌刷新后回写 Cookie 使用。
        page_no: 页码，从 1 开始。
        page_size: 每页数量。
        item_status: 商品状态过滤，默认只取在售（"0"）。
    Returns:
        dict: {success, items, has_more, cookies_str, raw_data} 或 {success: False, message}。
    """
    data = {
        "pageNo": page_no,
        "pageSize": page_size,
        "bizType": SELLER_BIZ_TYPE,
        "searchRequest": "{}",
        "itemStatus": item_status,
    }
    response = await mtop_call(
        account_id=account_id,
        cookies_str=cookie,
        api=SELLER_ITEM_LIST_API,
        version=SELLER_ITEM_LIST_VERSION,
        data=data,
        owner_id=owner_id,
        extra_params={
            **SELLER_EXTRA_PARAMS,
            "needLoginPC": "true",
            "accountSite": "xianyu",
        },
        extra_headers=SELLER_BIZ_HEADERS,
        origin=SELLER_ORIGIN,
        referer=SELLER_REFERER,
    )
    latest_cookie = response.get("cookies_str") or cookie

    if not response.get("success"):
        error_msg = response.get("error") or "获取鱼小铺商品失败"
        logger.error(f"【{account_id}】卖家平台商品列表获取失败: {error_msg}")
        return {
            "success": False,
            "message": error_msg,
            "cookies_str": latest_cookie,
            "account_invalid": bool(response.get("account_invalid")),
        }

    biz = ((response.get("res") or {}).get("data") or {}).get("data") or {}
    item_list = biz.get("itemSearchResponseList") or []
    items = [map_seller_item(raw) for raw in item_list if isinstance(raw, dict)]
    has_more = bool(biz.get("hasNextPage"))
    logger.info(
        f"【{account_id}】卖家平台第 {page_no} 页获取到 {len(items)} 个商品，hasNextPage={has_more}"
    )
    return {
        "success": True,
        "items": items,
        "page_no": page_no,
        "page_size": page_size,
        "has_more": has_more,
        "cookies_str": latest_cookie,
        "raw_data": biz,
    }


def _parse_update_response(response: Dict[str, Any], account_id: str) -> Dict[str, Any]:
    """解析卖家平台改价改库存接口返回。

    成功：res.data.code == "success" 或 res.data.data is True。
    业务失败同样在 res.data.code/res.data.msg 表达（如 SKU_PRICE_ILLEGAL），
    此时 ret 仍可能是 SUCCESS，故必须以 res.data.code 判定结果。
    """
    if not response.get("success"):
        error_msg = response.get("error") or "改价改库存请求失败"
        raw = json.dumps(response.get("res"), ensure_ascii=False, default=str)
        logger.error(f"【{account_id}】卖家平台改价改库存失败: {error_msg}；完整返回: {raw}")
        return {
            "success": False,
            "message": error_msg,
            "cookies_str": response.get("cookies_str"),
            "account_invalid": bool(response.get("account_invalid")),
        }

    res = response.get("res") or {}
    inner = res.get("data")
    if not isinstance(inner, dict):
        inner = {}
    code = str(inner.get("code") or "").lower()
    ok = code == "success" or inner.get("data") is True
    if ok:
        logger.info(f"【{account_id}】卖家平台改价改库存成功")
        return {"success": True, "message": "改价改库存成功", "cookies_str": response.get("cookies_str")}

    raw = json.dumps(res, ensure_ascii=False, default=str)
    msg = str(inner.get("msg") or "").strip() or "卖家平台未接受本次改价改库存"
    logger.warning(f"【{account_id}】卖家平台改价改库存被拒绝: {msg}；完整返回: {raw}")
    return {"success": False, "message": msg, "cookies_str": response.get("cookies_str")}


async def update_seller_item_inventory(
    *,
    account_id: str,
    cookie: str,
    item_id: str,
    quantity: Optional[int] = None,
    price: Any = None,
    sku_list: Optional[List[Dict[str, Any]]] = None,
    owner_id: Optional[int] = None,
) -> Dict[str, Any]:
    """更新鱼小铺商品的价格与库存（单规格与多规格共用）。

    Args:
        account_id: 闲鱼账号标识。
        cookie: 账号 Cookie。
        item_id: 商品ID。
        quantity: 单规格库存（与 price 配套使用）。
        price: 单规格价格（元）。接口要求价格与库存一并提交。
        sku_list: 多规格 [{"sku_id": str, "price": 元, "quantity": int}, ...]。
        owner_id: 账号所属用户 ID，令牌刷新回写使用。
    Returns:
        dict: {success, message, cookies_str}。
    """
    use_sku = bool(sku_list)
    if use_sku and quantity is not None:
        return {"success": False, "message": "改库存参数错误：单规格与多规格需二选一"}
    if not use_sku and quantity is None:
        return {"success": False, "message": "改库存参数错误：缺少 quantity 或 sku_list"}

    data: Dict[str, Any] = {"itemId": str(item_id)}
    if use_sku:
        # 多规格：itemSkuListStr 为 JSON 字符串，逐个 SKU 提交 skuId/quantity/price(元)
        sku_payload = [
            {
                "skuId": int(sku["sku_id"]),
                "quantity": int(sku["quantity"]),
                "price": sku["price"],
            }
            for sku in (sku_list or [])
        ]
        data["itemSkuListStr"] = json.dumps(sku_payload, ensure_ascii=False)
    else:
        # 单规格：顶层携带 price(元) 与 quantity
        data["quantity"] = int(quantity)
        if price is not None:
            data["price"] = price

    logger.info(f"【{account_id}】卖家平台改库存请求参数: {json.dumps(data, ensure_ascii=False)}")

    response = await mtop_call(
        account_id=account_id,
        cookies_str=cookie,
        api=SELLER_ITEM_UPDATE_API,
        version=SELLER_ITEM_UPDATE_VERSION,
        data=data,
        owner_id=owner_id,
        extra_params={
            **SELLER_EXTRA_PARAMS,
            "needLoginPC": "true",
            "accountSite": "xianyu",
        },
        extra_headers=SELLER_BIZ_HEADERS,
        origin=SELLER_ORIGIN,
        referer=SELLER_REFERER,
    )
    return _parse_update_response(response, account_id)


__all__ = [
    "fetch_seller_items",
    "update_seller_item_inventory",
    "map_seller_item",
    "SELLER_ITEM_LIST_API",
    "SELLER_ITEM_UPDATE_API",
]
