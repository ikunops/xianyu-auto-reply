#!/usr/bin/env python3
import asyncio, sys, time
sys.path.insert(0, '/app/backend-web')
from common.services.xianyu_publish_service import publish_single_item

COURSES = [
    {"title": "网络安全大师课 - 从入门到精通", "description": "系统学习网络安全知识，涵盖渗透测试、漏洞分析、安全防护等核心技能。", "price": 199, "category": "网络安全", "images": ["/tmp/course-images/linux.png"], "address": "湖北省武汉市东西湖区"},
    {"title": "Linux运维就业班 - 全套实战教程", "description": "零基础学习Linux系统管理、Shell编程、网络配置、服务部署等运维核心技能。", "price": 159, "category": "Linux", "images": ["/tmp/course-images/cloud.png"], "address": "湖北省武汉市东西湖区"},
    {"title": "云渗透教程 - 云安全攻防实战", "description": "深入学习云计算环境下的安全攻防技术。", "price": 179, "category": "云计算", "images": ["/tmp/course-images/k8s.png"], "address": "湖北省武汉市东西湖区"},
    {"title": "K8S认证实战班 (CKS)", "description": "针对CKA/CKS认证考试的专项辅导课程。", "price": 249, "category": "Kubernetes", "images": ["/tmp/course-images/database.png"], "address": "湖北省武汉市东西湖区"},
    {"title": "51CTO安全精品班", "description": "51CTO官方认证安全课程，涵盖WEB安全等方向。", "price": 299, "category": "网络安全", "images": ["/tmp/course-images/security.png"], "address": "湖北省武汉市东西湖区"},
    {"title": "OCP认证辅导班 8期", "description": "Oracle OCP认证考试辅导课程。", "price": 399, "category": "数据库", "images": ["/tmp/course-images/cert.png"], "address": "湖北省武汉市东西湖区"},
    {"title": "高俊峰 Linux云计算技能实战课", "description": "知名讲师高俊峰亲授的Linux与云计算综合实战课程。", "price": 199, "category": "Linux", "images": ["/tmp/course-images/linux.png"], "address": "湖北省武汉市东西湖区"},
    {"title": "K8S+DevOps全栈课程", "description": "系统学习Kubernetes与DevOps全流程。", "price": 259, "category": "Kubernetes", "images": ["/tmp/course-images/cloud.png"], "address": "湖北省武汉市东西湖区"},
]

async def main():
    cookie = 'cookie2=121ae58c6a6b99e8b19c5fa00dabc478; XSRF-TOKEN=328443f5-ce4a-432b-b788-da36243d7d4a; _samesite_flag_=true; sgcookie=E100axSmlWTg1J7YlLW74bv7GeM2AbkQ8UkTBpoDhctu%2B42%2FUKHUVdt3RkmO5T%2BbH4kILP7rKsEsf0zYrs4kmWyD6TbXaeAP61u0uR6Fu8UrTXA%3D; tracknick=xy45932284569; csg=37135813; t=9f8017f2475c45b424900f1728f0cf4e; _tb_token_=e57ee55a5ea7b; unb=2215600676819; x5secdata=xgc62529a9b12eb59djae0e7020a3de61e2818ce2d170d545cf81789387527a-717315356a1038868164abaad3eaa33b393a8cf3513e524f2448790f16ea79da__bx__h5api.m.taobao.com:443/h5/mtop.relationrecommend.wirelessrecommend.recommend/2.0; x5sectag=37516; x5sec=7b22733b32223a2261633262396662353836383739653865222c22617365727665723b33223a22307c434948476e395547454c716a385955454b4951454d50617079597344227d; mtop_partitioned_detect=1; _m_h5_tk=5940e74c9f1e9bbbf42089778bfb4a4e_1789395044326; _m_h5_tk_enc=a686d12f176d32d342578f75e661fe6a; sdkSilent=1789475091142; havana_lgc2_77=eyJoaWQiOiIyMTU2MDA2NzY4MTksInNnIjoiOThlNWI0YTlkNWJhYzc1NzU5YTA3OWVhNjA0MTQ0MGYiLCJzaXRlIjo3NywidG9rZW4iOiIxdXNVUEFBNm1zMnR1Yjcwd0FRaURvUSJ9; _hvn_lgc_=77; havana_lgc_exp=1791980691400'
    
    for i, course in enumerate(COURSES, 1):
        print(f"[{i}/{len(COURSES)}] {course['title'][:25]}...", flush=True)
        t0 = time.time()
        try:
            item_data = {
                "title": course["title"],
                "description": course["description"],
                "price": course["price"],
                "category": course["category"],
                "images": course["images"],
                "address": course["address"],
                "delivery_method": "pickup",
                "postage": 0,
                "condition": "全新",
            }
            result = await publish_single_item(
                item_data=item_data,
                cookie=cookie,
                static_root="/app/static",
            )
            elapsed = time.time() - t0
            status = "OK" if result.get("success") else "FAIL"
            url = result.get("item_url", "")
            mid = result.get("item_id", "")
            msg = result.get("message", "")[:100]
            print(f"  [{status}] {msg} (took {elapsed:.0f}s)", flush=True)
            if status == "OK":
                print(f"  URL: {url}", flush=True)
                print(f"  ID: {mid}", flush=True)
        except Exception as e:
            elapsed = time.time() - t0
            print(f"  [ERROR] after {elapsed:.0f}s: {str(e)[:150]}", flush=True)

asyncio.run(main())
