"""试点探针：登录t5账号，探测卖家管理/编辑入口，每步截图到/app/static/供检查。"""
import asyncio
import sys
sys.path.insert(0, "/app/backend-web")
from app.services.xianyu_publisher import XianyuPublisher


async def get_cookie(account_id: str) -> str:
    import pymysql
    conn = pymysql.connect(host="mysql", port=3306, user="xianyu",
                           password="xianyu@2026", database="xianyu_data")
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT cookie FROM xy_accounts WHERE account_id=%s", (account_id,))
            row = cur.fetchone()
    finally:
        conn.close()
    if not row or not row[0]:
        raise Exception("账号Cookie为空")
    return row[0]


async def main():
    import os
    account_id = os.environ.get("ACCOUNT_ID", "3174906677")
    print(f"ACCOUNT {account_id}", flush=True)
    pub = XianyuPublisher(static_root="/app/static")
    await pub.initialize(headless=True)
    await pub.set_cookies(await get_cookie(account_id))
    page = pub.page

    async def snap(name):
        await page.screenshot(path=f"/app/static/probe_{name}.png")
        print(f"SHOT probe_{name}.png url={page.url[:100]} title={await page.title()}", flush=True)

    async def dump_state(name):
        state = await page.evaluate("""() => ({
            url: location.href,
            hash: location.hash,
            title: document.title,
            body: document.body.innerText.slice(0, 8000),
            links: [...document.querySelectorAll('a')].map(e => ({text: (e.innerText || '').trim(), href: e.href})).filter(e => e.text || e.href).slice(0, 100),
            controls: [...document.querySelectorAll('a,button,input,textarea,[role="button"],[role="link"]')]
                .filter(e => e.offsetWidth || e.offsetHeight || e.matches('input,textarea'))
                .slice(0, 200)
                .map(e => ({
                    tag: e.tagName,
                    text: (e.innerText || e.value || e.getAttribute('aria-label') || '').trim().slice(0, 120),
                    href: e.href || '',
                    type: e.type || '',
                    name: e.name || '',
                    id: e.id || '',
                    cls: e.className || ''
                }))
        })""")
        print(f"STATE {name} {state}", flush=True)
        await snap(name)

    page.on("request", lambda request: print(f"REQ {request.method} {request.url}", flush=True) if "mtop" in request.url or "seller" in request.url else None)
    page.on("response", lambda response: print(f"RESP {response.status} {response.url}", flush=True) if "mtop" in response.url or "seller" in response.url else None)

    await page.goto("https://seller.goofish.com/?site=COMMONPRO", wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(5)
    await dump_state("01_seller_before_refresh")

    for selector in ('button:has-text("刷 新")', 'button:has-text("刷新")', 'button:has-text("现在开始")'):
        try:
            target = page.locator(selector).first
            if await target.count() and await target.first.is_visible():
                print(f"CLICK {selector}", flush=True)
                await target.first.click(timeout=10000)
                break
        except Exception as exc:
            print(f"CLICK_ERR {selector}: {str(exc)[:200]}", flush=True)
    await asyncio.sleep(12)
    await dump_state("02_seller_after_refresh")

    await pub.close_only_browser() if hasattr(pub, "close_only_browser") else None
    print("PROBE_DONE", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
