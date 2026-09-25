"""账号商业身份（卖家工作台权限）探测

判定依据在闲鱼侧：账号是否持有 bizCode=COMMONPRO「鱼小铺专业卖家工作台」商业身份。
只有持有该身份，`seller.pc.*` / `seller.common.*` 一族接口（下架、数据罗盘等）才可用；
本系统没有任何"主号"字段，这里只是把平台的真实判定读出来。

全程只读，不改动任何数据。
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, List, Optional

import aiohttp
from loguru import logger

from common.utils.xianyu_utils import generate_sign, trans_cookies

IDENTITY_API = "mtop.alibaba.idle.seller.platform.user.business.identity.get"
QUOTA_API = "mtop.alibaba.idle.seller.common.sub.account.quota.query"
WORKBENCH_BIZ_CODE = "COMMONPRO"
APP_KEY = "34839810"
GATEWAY = "https://h5api.m.goofish.com/h5"
REQUEST_TIMEOUT_SECONDS = 20
ACCOUNT_INTERVAL_SECONDS = 0.8


async def _call(session: aiohttp.ClientSession, api: str, data: dict, cookies_str: str) -> Dict[str, Any]:
    cookies = trans_cookies(cookies_str)
    timestamp = str(int(time.time() * 1000))
    token = cookies.get("_m_h5_tk", "").split("_")[0] if cookies.get("_m_h5_tk") else ""
    data_val = json.dumps(data, separators=(",", ":"), ensure_ascii=False)

    params = {
        "jsv": "2.7.2",
        "appKey": APP_KEY,
        "t": timestamp,
        "sign": generate_sign(timestamp, token, data_val),
        "v": "1.0",
        "type": "originaljson",
        "accountSite": "xianyu",
        "dataType": "json",
        "timeout": "20000",
        "api": api,
        "sessionOption": "AutoLoginOnly",
    }
    # 工作台族接口要求带站点业务码与 Referer，缺了会被网关判成非法来源
    headers = {
        "accept": "application/json",
        "content-type": "application/x-www-form-urlencoded",
        "cookie": cookies_str,
        "Referer": "https://seller.goofish.com/?site=COMMONPRO",
        "idle_site_biz_code": WORKBENCH_BIZ_CODE,
        "idle_user_group_member_id": "",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
        ),
    }
    url = f"{GATEWAY}/{api}/1.0/"
    async with session.post(
        url,
        params=params,
        data={"data": data_val},
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS),
    ) as response:
        try:
            return await response.json(content_type=None)
        except Exception:
            return {"ret": ["FAIL_PARSE::响应不是合法JSON"]}


def _ret(res: Optional[Dict[str, Any]]) -> str:
    value = (res or {}).get("ret")
    if isinstance(value, list):
        return ";".join(str(x) for x in value)
    return str(value or "")


def _unwrap(res: Optional[Dict[str, Any]]) -> Any:
    data = (res or {}).get("data")
    return data.get("data") if isinstance(data, dict) else None


async def check_one(cookies_str: str) -> Dict[str, Any]:
    """返回单个账号的商业身份与卖家等级"""
    async with aiohttp.ClientSession() as session:
        identity_res = await _call(session, IDENTITY_API, {}, cookies_str)
        quota_res = await _call(session, QUOTA_API, {"bizType": WORKBENCH_BIZ_CODE}, cookies_str)

    raw_identities = _unwrap(identity_res) or []
    identities = [
        {
            "bizCode": item.get("bizCode"),
            "bizName": item.get("bizName"),
            "bizIdentityStatus": item.get("bizIdentityStatus"),
        }
        for item in raw_identities
        if isinstance(item, dict)
    ]
    quota = _unwrap(quota_res)
    quota = quota if isinstance(quota, dict) else {}

    return {
        "workbench_enabled": any(i.get("bizCode") == WORKBENCH_BIZ_CODE for i in identities),
        "identities": identities,
        "seller_level": quota.get("sellerLevel"),
        "identity_ret": _ret(identity_res),
        "quota_ret": _ret(quota_res),
    }


async def check_accounts(accounts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """逐账号检测（串行 + 小间隔，避免瞬时打满平台风控）"""
    results: List[Dict[str, Any]] = []
    for account in accounts:
        record = {
            "pk": account.get("pk"),
            "account_id": account.get("account_id"),
            "note": account.get("note"),
        }
        cookie = (account.get("cookie") or "").strip()
        if not cookie:
            results.append({**record, "error": "账号Cookie为空，请先登录该账号"})
            continue
        try:
            results.append({**record, **await check_one(cookie)})
        except Exception as exc:
            logger.warning(f"账号 {record.get('account_id')} 商业身份检测失败: {exc}")
            results.append({**record, "error": f"{type(exc).__name__}: {str(exc)[:120]}"})
        await asyncio.sleep(ACCOUNT_INTERVAL_SECONDS)
    return results
