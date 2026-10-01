"""
公共商品发布执行服务

功能：
1. 统一执行单品发布的业务编排
2. 在发布前处理地址解析和发布日志
3. 在发布成功后自动同步账号商品
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.models.xy_account import XYAccount
from common.services.item_service import ItemService
from common.services.publish_address_service import PublishAddressService
from common.services.publish_log_service import PublishLogService
from common.services.item_stock_service import apply_stock_after_publish
from common.services.xianyu_publish_service import publish_single_item


async def _get_account(session: AsyncSession, account_id: str, user_id: int) -> Optional[XYAccount]:
    """获取用户可用的闲鱼账号。"""
    stmt = (
        select(XYAccount)
        .where(
            XYAccount.account_id == account_id,
            XYAccount.owner_id == user_id,
        )
        .order_by(desc(XYAccount.id))
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalars().first()


async def _sync_account_items_after_publish(
    session: AsyncSession,
    account_id: str,
    account: XYAccount,
) -> Dict[str, Any]:
    """发布成功后自动同步账号商品。"""
    item_svc = ItemService(session)
    try:
        sync_result = await item_svc.fetch_all_items_from_account(account=account)
        sync_status = "success" if sync_result.get("success") else "failed"
        sync_total_count = int(sync_result.get("total_count") or 0)
        sync_saved_count = int(sync_result.get("saved_count") or 0)
        if sync_status == "success":
            sync_message = f"已自动获取 {sync_total_count} 个商品，入库 {sync_saved_count} 个商品"
            logger.info(
                f"账号 {account_id} 发布后自动获取商品完成：共 {sync_total_count} 件，保存 {sync_saved_count} 件"
            )
        else:
            sync_message = f"自动获取商品失败：{sync_result.get('message') or '未知错误'}"
            logger.warning(
                f"账号 {account_id} 发布后自动获取商品失败，不影响后续发布：{sync_result.get('message', '未知错误')}"
            )
        return {
            "sync_status": sync_status,
            "sync_message": sync_message,
            "sync_total_count": sync_total_count,
            "sync_saved_count": sync_saved_count,
        }
    except Exception as sync_exc:
        logger.warning(
            f"账号 {account_id} 发布后自动获取商品异常，不影响后续发布：{sync_exc}"
        )
        return {
            "sync_status": "failed",
            "sync_message": f"自动获取商品异常：{sync_exc}",
            "sync_total_count": 0,
            "sync_saved_count": 0,
        }


async def _load_material_stock(session: AsyncSession, material_id: Any) -> Optional[int]:
    """回查素材库里的库存。

    单品发布（前端「立即发布」）的请求体不带 stock，只有批量发布带的是素材字典；
    为了两条链路行为一致，这里按 material_id 回查一次。
    """
    if not material_id:
        return None
    try:
        from sqlalchemy import text

        row = (
            await session.execute(
                text("SELECT stock FROM xy_product_materials WHERE id = :mid"),
                {"mid": int(material_id)},
            )
        ).first()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"回查素材库存失败 material={material_id}: {exc}")
        return None
    if not row or row[0] is None:
        return None
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return None


async def _bind_material_card_after_publish(
    user_id: int,
    material_id: Optional[int],
    item_id: Optional[str],
) -> Dict[str, Any]:
    """发布成功后把该素材的卡券绑到新商品上（出生就写，避免买家拍下发不出货）

    锚定走"卡券唯一键 = 分享链接"那条边：素材来源链接里的 pwd_id → 反查正文含该 pwd_id 的卡券。
    刻意不用 xy_cards.material_id：那列是早期按名称猜的回填，实测有错绑。
    守卫：① 商品已有任何卡券关联则直接跳过（挂两张会让发货端"唯一卡券"判定失败）；
          ② 命中 0 张或多张都不绑，留给人工。
    """
    if not material_id or not item_id:
        return {"card_bound": 0, "card_bind_message": ""}

    from sqlalchemy import text

    from common.db.session import async_session_maker
    from common.services.card_matcher import CardMatcher

    try:
        async with async_session_maker() as fresh_session:
            bound = (
                await fresh_session.execute(
                    text("SELECT COUNT(*) FROM xy_card_item_relations WHERE item_id = :iid"),
                    {"iid": str(item_id)},
                )
            ).scalar() or 0
            if bound:
                return {"card_bound": 0, "card_bind_message": ""}

            pwd_rows = (
                await fresh_session.execute(
                    text(
                        "SELECT DISTINCT SUBSTRING_INDEX(share_url, '/s/', -1) "
                        "FROM xy_material_sources "
                        "WHERE material_id = :mid AND share_url LIKE '%/s/%'"
                    ),
                    {"mid": int(material_id)},
                )
            ).all()
            pwds = [str(r[0]).strip('/') for r in pwd_rows if r[0]]
            if not pwds:
                return {"card_bound": 0, "card_bind_message": "该素材没有可锚定的分享链接，未自动绑定"}

            card_ids = []
            for pwd in pwds:
                hit = (
                    await fresh_session.execute(
                        text("SELECT id FROM xy_cards WHERE enabled = 1 AND text_content LIKE :kw"),
                        {"kw": "%" + pwd + "%"},
                    )
                ).all()
                card_ids += [int(r[0]) for r in hit]
            card_ids = sorted(set(card_ids))
            if not card_ids:
                return {"card_bound": 0, "card_bind_message": "按分享链接没找到对应卡券，未自动绑定"}

            # 一个素材多张卡券是正常的（一条链接一张卡券）：给这个商品选一张即可，
            # 商品侧仍只有一张，发货端"唯一卡券"的判定不受影响。
            picked_note = ""
            if len(card_ids) == 1:
                card_id = card_ids[0]
            else:
                ranked = (
                    await fresh_session.execute(
                        text(
                            "SELECT id FROM xy_cards WHERE id IN (%s) "
                            "ORDER BY delivery_count DESC, id ASC"
                            % ",".join(str(c) for c in card_ids)
                        )
                    )
                ).all()
                card_id = int(ranked[0][0])
                picked_note = f"该素材有 {len(card_ids)} 张卡券，已选 #{card_id}（发货次数最多、编号最小）"
            matcher = CardMatcher(fresh_session)
            res = await matcher.batch_bind_cards_to_items(
                user_id=user_id,
                card_ids=[card_id],
                item_ids=[str(item_id)],
            )
            await fresh_session.commit()
            if res.get("success_count"):
                logger.info(f"发布成功后自动绑定卡券 #{card_id} → 商品 {item_id}")
                msg = f"已自动绑定卡券 #{card_id} 到新商品"
                if picked_note:
                    msg = f"{msg}，{picked_note}"
                return {"card_bound": 1, "card_bind_message": msg}
            return {"card_bound": 0, "card_bind_message": f"卡券 #{card_id} 与该商品已绑定，无需重复绑"}
    except Exception as exc:
        logger.warning(f"发布后自动绑卡券失败 material={material_id} item={item_id}: {exc}")
        return {"card_bound": 0, "card_bind_message": f"自动绑卡券失败：{str(exc)[:80]}"}


async def execute_single_publish(
    session: AsyncSession,
    user_id: int,
    account_id: str,
    item_data: dict,
    static_root: str | Path | None = None,
) -> Dict[str, Any]:
    """执行单品发布并返回统一结果。"""
    # 单品发布也可能来自素材：从素材库导入时前端会带 material_id（批量发布带的是 id）
    material_id = item_data.get("id") or item_data.get("material_id")
    log_svc = PublishLogService(session)
    address_svc = PublishAddressService(session)

    account = await _get_account(session=session, account_id=account_id, user_id=user_id)
    cookies_str = account.cookie if account and account.cookie else ""
    if not cookies_str:
        log = await log_svc.create_log(
            user_id=user_id,
            account_id=account_id,
            title=item_data.get("title", ""),
            description=item_data.get("description", ""),
            price=str(item_data.get("price", "")),
            material_id=material_id,
            status="failed",
            error_message="账号不存在或无权使用",
        )
        return {"success": False, "message": "账号不存在或无权使用", "log_id": log.id}

    try:
        resolved_address = await address_svc.resolve_publish_address(account_id, item_data)
    except ValueError as exc:
        log = await log_svc.create_log(
            user_id=user_id,
            account_id=account_id,
            title=item_data.get("title", ""),
            description=item_data.get("description", ""),
            price=str(item_data.get("price", "")),
            material_id=material_id,
            status="failed",
            error_message=str(exc),
        )
        return {"success": False, "message": str(exc), "log_id": log.id}

    publish_item_data = resolved_address.apply_to_item_data(item_data)
    log = await log_svc.create_log(
        user_id=user_id,
        account_id=account_id,
        title=item_data.get("title", ""),
        description=item_data.get("description", ""),
        price=str(item_data.get("price", "")),
        material_id=material_id,
        status="publishing",
        **resolved_address.to_log_fields(),
    )

    result = None
    pub_error = None
    try:
        result = await publish_single_item(
            item_data=publish_item_data,
            cookie=cookies_str,
            static_root=static_root,
        )
    except Exception as exc:
        pub_error = exc
        logger.error(f"单品发布异常: {exc}")

    from common.db.session import async_session_maker

    try:
        async with async_session_maker() as fresh_session:
            fresh_log_svc = PublishLogService(fresh_session)
            if pub_error:
                await fresh_log_svc.update_log(
                    log_id=log.id,
                    status="failed",
                    error_message=str(pub_error),
                )
                return {"success": False, "message": f"发布异常: {str(pub_error)}", "log_id": log.id}

            status = "success" if result.get("success") else "failed"
            await fresh_log_svc.update_log(
                log_id=log.id,
                status=status,
                item_url=result.get("item_url"),
                item_id=result.get("item_id"),
                error_message=None if result.get("success") else result.get("message"),
            )
    except Exception as db_err:
        logger.error(f"更新发布日志失败: {db_err}")

    if pub_error:
        return {"success": False, "message": f"发布异常: {str(pub_error)}", "log_id": log.id}

    publish_success = result.get("success", False)
    sync_info = {
        "sync_status": "skipped",
        "sync_message": "发布未成功，未触发自动获取商品",
        "sync_total_count": 0,
        "sync_saved_count": 0,
    }
    if publish_success and account is not None:
        sync_info = await _sync_account_items_after_publish(
            session=session,
            account_id=account_id,
            account=account,
        )

    card_bind_info = await _bind_material_card_after_publish(
        user_id=user_id,
        material_id=material_id,
        item_id=result.get("item_id") if publish_success else None,
    )

    # 网页版发布页没有库存入口，鱼小铺账号在发布成功后用卖家接口把库存补上
    stock_info = {"stock_applied": 0, "stock_message": ""}
    if publish_success:
        try:
            # 单品发布不带 stock：按 material_id 回查素材库，保证两条链路一致
            stock_value = item_data.get("stock")
            if not stock_value and material_id:
                stock_value = await _load_material_stock(session, material_id)
            stock_info = await apply_stock_after_publish(
                account_id=account_id,
                cookie=cookies_str,
                item_id=result.get("item_id"),
                stock=stock_value,
                price=item_data.get("price"),
                owner_id=user_id,
            )
        except Exception as stock_exc:  # noqa: BLE001
            logger.warning(f"发布后补设库存异常，不影响发布结果: {stock_exc}")

    message = result.get("message") or ("商品发布成功" if publish_success else "发布失败")
    if publish_success and sync_info.get("sync_message"):
        message = f"{message}，{sync_info['sync_message']}"
    if publish_success and card_bind_info.get("card_bind_message"):
        message = f"{message}，{card_bind_info['card_bind_message']}"
    if publish_success and stock_info.get("stock_message"):
        message = f"{message}，{stock_info['stock_message']}"

    return {
        "success": publish_success,
        "message": message,
        "item_url": result.get("item_url"),
        "item_id": result.get("item_id"),
        "log_id": log.id,
        **sync_info,
        **card_bind_info,
        **stock_info,
    }
