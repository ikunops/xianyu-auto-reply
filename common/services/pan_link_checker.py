# -*- coding: utf-8 -*-
"""网盘链接验活服务（卡券/素材通用）

来源：NetDiskLinkValidator（2026-09-20 用于筛 K12 永久有效链接），移植进系统并扩展：
- check_url(url)            单链接验活（八种网盘：夸克/百度/UC/阿里云盘/115/123盘/天翼/迅雷）
- extract_pan_links(text)   从卡券正文/描述中提取网盘分享链接
- check_card_text(text)     汇总一张卡券的链接状态：alive/partial/dead/no_link/unknown
"""
from __future__ import annotations

import asyncio
import json
import re

import httpx
from loguru import logger

PAN_URL_RE = re.compile(
    r"""https?://(?:pan\.quark\.cn|pan\.baidu\.com|drive\.uc\.cn|www\.aliyundrive\.com|"""
    r"""www\.alipan\.com|115\.com|115cdn\.com|anxia\.com|www\.123pan\.com|www\.123912\.com|"""
    r"""www\.123684\.com|cloud\.189\.cn|pan\.xunlei\.com)/[^\s"'<>）)】]+""",
    re.I,
)


def extract_pan_links(text: str) -> list:
    """提取文本中的网盘分享链接（去重保序）。"""
    if not text:
        return []
    out = []
    for m in PAN_URL_RE.finditer(text):
        url = m.group(0).rstrip('.,;')
        if url not in out:
            out.append(url)
    return out


import httpx
import json
import re
import asyncio
from urllib.parse import quote


# UC网盘有效性检测函数（修复版本）
async def check_uc(share_id):
    url = f"https://drive.uc.cn/s/{share_id}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; SM-G975F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.101 Mobile Safari/537.36",
        "Host": "drive.uc.cn",
        "Referer": url,
        "Origin": "https://drive.uc.cn",
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=10)
            # print(f"UC链接: {url}, 状态码: {response.status_code}")
            if response.status_code != 200:
                # print("状态码非200，判断为无效")
                return False

            page_text = _html_text(response.text)
            # print(f"页面文本摘录: {page_text[:100]}...")  # 调试用，显示前100字符

            # 检查错误提示
            error_keywords = ["失效", "不存在", "违规", "删除", "已过期", "被取消"]
            if any(keyword in page_text for keyword in error_keywords):
                # print("检测到错误关键词，判断为无效")
                return False

            # 检查是否需要访问码（有效但需密码）
            if re.search(r"input-wrap[\s\S]{0,400}?<input", response.text, re.I):
                print("发现访问码输入框，判断为有效（需密码）")
                return True

            # 检查是否包含文件列表或分享内容（有效）
            if "文件" in page_text or "分享" in page_text or re.search(r"file-list", response.text, re.I):
                # print("检测到文件或分享内容，判断为有效")
                return True

            # 默认情况：未找到明确有效标志，保守判断为无效
            # print("未找到有效标志，判断为无效")
            return False
    except httpx.RequestError as e:
        print(f"UC检查错误 for {share_id}: {str(e)}")
        return False


# 阿里云盘有效性检测
async def check_aliyun(share_id):
    api_url = "https://api.aliyundrive.com/adrive/v3/share_link/get_share_by_anonymous"
    headers = {"Content-Type": "application/json"}
    data = json.dumps({"share_id": share_id})
    async with httpx.AsyncClient() as client:
        response = await client.post(api_url, headers=headers, data=data)
        response_json = response.json()
        if response_json.get('has_pwd'):
            return True
        if response_json.get('code') == 'NotFound.ShareLink':
            return False
        if not response_json.get('file_infos'):
            return False
        return True


# 115网盘有效性检测
async def check_115(share_id):
    api_url = "https://webapi.115.com/share/snap"
    params = {"share_code": share_id, "receive_code": ""}
    async with httpx.AsyncClient() as client:
        response = await client.get(api_url, params=params)
        response_json = response.json()
        if response_json.get('state'):
            return True
        elif '请输入访问码' in response_json.get('error', ''):
            return True
        return False


# 夸克网盘有效性检测
async def check_quark(share_id):
    api_url = "https://drive.quark.cn/1/clouddrive/share/sharepage/token"
    headers = {"Content-Type": "application/json"}
    data = json.dumps({"pwd_id": share_id, "passcode": ""})
    async with httpx.AsyncClient() as client:
        response = await client.post(api_url, headers=headers, data=data)
        response_json = response.json()
        if response_json.get('message') == "ok":
            token = response_json.get('data', {}).get('stoken')
            if not token:
                return False
            detail_url = f"https://drive-h.quark.cn/1/clouddrive/share/sharepage/detail?pwd_id={share_id}&stoken={quote(token)}&_fetch_share=1"
            detail_response = await client.get(detail_url)
            detail_response_json = detail_response.json()
            if detail_response_json.get('status') == 400:
                return True
            if detail_response_json.get('data', {}).get('share', {}).get('status') == 1:
                return True
            return False
        elif response_json.get('message') == "需要提取码":
            return True
        return False


# 123pan网盘有效性检测
async def check_123pan(share_id):
    api_url = f"https://www.123pan.com/api/share/info?shareKey={share_id}"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(api_url, headers={"User-Agent": "Mozilla/5.0"})
            response_json = response.json()
            if not response_json:
                return False
            if "分享页面不存在" in response.text or response_json.get('code', -1) != 0:
                return False
            if response_json.get('data', {}).get('HasPwd', False):
                return True
            return True
    except (httpx.RequestError, json.JSONDecodeError):
        return False


# 天翼网盘有效性检测
async def check_tianyi(share_id):
    api_url = "https://api.cloud.189.cn/open/share/getShareInfoByCodeV2.action"
    async with httpx.AsyncClient() as client:
        response = await client.post(api_url, data={"shareCode": share_id})
        text = response.text
        if any(x in text for x in ["ShareInfoNotFound", "ShareNotFound", "FileNotFound",
                                   "ShareExpiredError", "ShareAuditNotPass"]):
            return False
        if "needAccessCode" in text:
            return True
        return True


# 迅雷网盘有效性检测
async def check_xunlei(share_id):
    token_url = "https://xluser-ssl.xunlei.com/v1/shield/captcha/init"
    headers = {"Content-Type": "application/json"}
    data = json.dumps({
        "client_id": "Xqp0kJBXWhwaTpB6",
        "device_id": "925b7631473a13716b791d7f28289cad",
        "action": "get:/drive/v1/share",
        "meta": {
            "package_name": "pan.xunlei.com",
            "client_version": "1.45.0",
            "captcha_sign": "1.fe2108ad808a74c9ac0243309242726c",
            "timestamp": "1645241033384"
        }
    })
    async with httpx.AsyncClient() as client:
        token_response = await client.post(token_url, headers=headers, data=data)
        token_json = token_response.json()
        token = token_json.get('captcha_token')
        if not token:
            return False
        api_url = f"https://api-pan.xunlei.com/drive/v1/share?share_id={share_id}"
        headers = {
            "x-captcha-token": token,
            "x-client-id": "Xqp0kJBXWhwaTpB6",
            "x-device-id": "925b7631473a13716b791d7f28289cad"
        }
        response = await client.get(api_url, headers=headers)
        text = response.text
        if any(x in text for x in ["NOT_FOUND", "SENSITIVE_RESOURCE", "EXPIRED"]):
            return False
        if "PASS_CODE_EMPTY" in text:
            return True
        return True


# 百度网盘有效性检测
async def check_baidu(share_id):
    url = f"https://pan.baidu.com/s/{share_id}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, follow_redirects=True)
            text = response.text
            if any(x in text for x in ["分享的文件已经被取消", "分享已过期", "你访问的页面不存在", "你所访问的页面"]):
                return False
            if "请输入提取码" in text or "提取文件" in text:
                return True
            if "过期时间" in text or "文件列表" in text:
                return True
            return False
    except httpx.RequestError:
        return False


# 提取分享码函数（支持多种网盘）
def extract_share_id(url):
    net_disk_patterns = {
        'uc': {
            'domains': ['drive.uc.cn'],
            'pattern': r"https?://drive\.uc\.cn/s/([a-zA-Z0-9]+)"
        },
        'aliyun': {
            'domains': ['aliyundrive.com', 'alipan.com'],
            'pattern': r"https?://(?:www\.)?(?:aliyundrive|alipan)\.com/s/([a-zA-Z0-9]+)"
        },
        'quark': {
            'domains': ['pan.quark.cn'],
            'pattern': r"https?://(?:www\.)?pan\.quark\.cn/s/([a-zA-Z0-9]+)"
        },
        '115': {
            'domains': ['115.com', '115cdn.com', 'anxia.com'],
            'pattern': r"https?://(?:www\.)?(?:115|115cdn|anxia)\.com/s/([a-zA-Z0-9]+)"
        },
        '123pan': {
            'domains': ['123684.com', '123685.com', '123912.com', '123pan.com', '123pan.cn', '123592.com'],
            'pattern': r"https?://(?:www\.)?(?:123684|123685|123912|123pan|123pan\.cn|123592)\.com/s/([a-zA-Z0-9-]+)"
        },
        'tianyi': {
            'domains': ['cloud.189.cn'],
            'pattern': r"https?://cloud\.189\.cn/(?:t/|web/share\?code=)([a-zA-Z0-9]+)"
        },
        'xunlei': {
            'domains': ['pan.xunlei.com'],
            'pattern': r"https?://(?:www\.)?pan\.xunlei\.com/s/([a-zA-Z0-9-]+)"
        },
        'baidu': {
            'domains': ['pan.baidu.com', 'yun.baidu.com'],
            'pattern': r"https?://(?:[a-z]+\.)?(?:pan|yun)\.baidu\.com/(?:s/|share/init\?surl=)([a-zA-Z0-9_-]+)(?:\?|$)"
        }
    }
    for net_disk, config in net_disk_patterns.items():
        if any(domain in url for domain in config['domains']):
            match = re.search(config['pattern'], url)
            if match:
                share_id = match.group(1)
                return share_id, net_disk
    return None, None


# 检查链接有效性（通用函数）
def _html_text(html: str) -> str:
    """极简 HTML 取文本：去脚本/样式、剥标签、压缩空白（替代 BeautifulSoup.get_text）。"""
    if not html:
        return ''
    t = re.sub(r'(?is)<(script|style)[^>]*>.*?</>', ' ', html)
    t = re.sub(r'(?s)<[^>]+>', ' ', t)
    t = re.sub(r'&nbsp;|&#160;', ' ', t)
    return re.sub(r'\s+', '', t)


async def check_url(url):
    share_id, service = extract_share_id(url)
    if not share_id or not service:
        logger.debug(f"无法识别的链接或网盘服务: {url}")
        return url, False
    check_functions = {
        "uc": check_uc,
        "aliyun": check_aliyun,
        "quark": check_quark,
        "115": check_115,
        "123pan": check_123pan,
        "tianyi": check_tianyi,
        "xunlei": check_xunlei,
        "baidu": check_baidu
    }
    if service in check_functions:
        result = await check_functions[service](share_id)
        return url, result
    logger.debug(f"未找到服务 {service} 的检测函数")
    return url, False


# 主函数
async def main(urls):
    tasks = [check_url(url) for url in urls]
    results = await asyncio.gather(*tasks)
    print("\n检测结果：")
    for url, result in results:
        print(f"{url} - {'有效' if result else '无效'}")
    return results

async def check_card_text(text: str, timeout_each: float = 15.0) -> dict:
    """验活一张卡券的正文：返回 {status, links, alive_count, dead_count}。

    status 语义：
      alive   —— 全部链接有效
      partial —— 部分有效（有死链，需要处理）
      dead    —— 全部失效
      no_link —— 正文里没有网盘链接（可能是纯文本/图片卡券）
      unknown —— 校验过程异常
    """
    links = extract_pan_links(text or "")
    if not links:
        return {"status": "no_link", "links": [], "alive_count": 0, "dead_count": 0}

    async def one(u):
        async with _sem:
            try:
                _u, ok = await asyncio.wait_for(check_url(u), timeout=timeout_each)
                return {"url": u, "alive": bool(ok)}
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"验活异常 {u[:60]}: {exc}")
                return {"url": u, "alive": None}

    # 限制单张卡券内的并发：赠品卡券可能有 15+ 条链接，一次性全发会触发
    # 网盘限流导致大批超时（表现为 alive=null）。串行化到 3 路更稳。
    _sem = asyncio.Semaphore(3)
    results = await asyncio.gather(*(one(u) for u in links))
    alive = sum(1 for r in results if r["alive"] is True)
    dead = sum(1 for r in results if r["alive"] is False)
    unknown = sum(1 for r in results if r["alive"] is None)
    # 判定顺序很重要：只要探测成功的链接全都有效，就算 alive —— 即便另有若干条
    # 因超时/限流探测失败（unknown）。这些失败多为并发压力导致，不代表链接已死。
    # 之前"有 unknown 且无 dead"会落到 unknown，把好卡券误判成状态未知。
    if alive > 0 and dead == 0:
        status = "alive"
    elif dead == len(results):
        status = "dead"
    elif dead > 0:
        status = "partial"
    else:
        status = "unknown"
    return {"status": status, "links": results, "alive_count": alive,
            "dead_count": dead, "unknown_count": unknown}
