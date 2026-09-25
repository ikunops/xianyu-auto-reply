"""
商品发布业务逻辑服务

功能：
1. 素材库 CRUD（创建/查询/更新/删除商品模板）
2. 提供素材字典转换工具，供发布执行链路复用
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.models.product_material import ProductMaterial
from common.models.publish_log import PublishLog


# ==================== 素材库服务 ====================

from common.utils.time_utils import safe_isoformat
class ProductMaterialService:
    """商品素材库 CRUD 服务"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def _build_source_map(self, material_ids: list[int]) -> dict[int, list[dict]]:
        """一次查出这批素材的网盘来源（目录 / 分享链接 / 提取码 / 链接状态）。

        xy_material_sources 是「网盘目录 → 分享链接 → 卡券」这条链路的落点。
        正常一条素材只有一个来源；历史脏数据里存在一素材多来源，故按主来源优先排序。
        """
        from sqlalchemy import text

        ids = [int(m) for m in material_ids if m]
        if not ids:
            return {}
        rows = (await self.session.execute(text(
            "SELECT material_id, source_type, source_path, share_url, extract_code, "
            "link_status, last_check_at, is_primary FROM xy_material_sources "
            "WHERE material_id IN (%s) ORDER BY is_primary DESC, id ASC" % ",".join(str(m) for m in ids)
        ))).all()
        out: dict[int, list[dict]] = {}
        for r in rows:
            out.setdefault(int(r[0]), []).append({
                "source_type": r[1] or "",
                "source_path": r[2] or "",
                "share_url": r[3] or "",
                "extract_code": r[4] or "",
                "link_status": r[5] or "",
                "last_check_at": r[6].isoformat() if r[6] else None,
                "is_primary": bool(r[7]),
            })
        return out

    async def _build_published_map(self, material_ids: list[int]) -> dict[int, list[str]]:
        """批量查询每条素材已被哪些账号成功发布过"""
        if not material_ids:
            return {}
        stmt = (
            select(PublishLog.material_id, PublishLog.account_id)
            .where(
                PublishLog.material_id.in_(material_ids),
                PublishLog.status == 'success',
            )
            .distinct()
        )
        rows = (await self.session.execute(stmt)).all()
        result: dict[int, list[str]] = {}
        for mid, acc in rows:
            if mid is not None:
                result.setdefault(mid, []).append(acc)
        return result


    async def create(self, user_id: int, data: dict) -> ProductMaterial:
        """创建素材"""
        title = data.get("title")
        description = data.get("description")
        if not title or not description:
            raise ValueError("标题(title)和描述(description)为必填字段")
        material = ProductMaterial(
            user_id=user_id,
            title=title,
            description=description,
            price=float(data["price"]),
            original_price=float(data["original_price"]) if data.get("original_price") else None,
            category=data.get("category"),
            images=data.get("images", []),
            delivery_method=data.get("delivery_method", "pickup"),
            postage=float(data.get("postage", 0)),
            address=data.get("address"),
            brand=data.get("brand"),
            condition=data.get("condition", "全新"),
            remark=data.get("remark"),
        )
        self.session.add(material)
        await self.session.commit()
        await self.session.refresh(material)
        return material

    async def list_materials(
        self, user_id: int = None, page: int = 1, page_size: int = 20,
        title: str = None, category: str = None, condition: str = None,
    ) -> Dict[str, Any]:
        """分页查询素材列表
        
        Args:
            user_id: 用户ID，为None时查询全部（管理员场景）
            title: 标题模糊搜索
            category: 分类筛选
            condition: 成色筛选
        """
        page = max(page, 1)
        page_size = page_size if page_size in (10, 20, 50, 100, 500, 1000) else 20

        base_cond = []
        if user_id is not None:
            base_cond.append(ProductMaterial.user_id == user_id)
        if title:
            base_cond.append(ProductMaterial.title.ilike(f"%{title}%"))
        if category:
            base_cond.append(ProductMaterial.category == category)
        if condition:
            base_cond.append(ProductMaterial.condition == condition)

        count_stmt = (
            select(func.count())
            .select_from(ProductMaterial)
            .where(*base_cond)
        )
        total = (await self.session.execute(count_stmt)).scalar() or 0

        stmt = (
            select(ProductMaterial)
            .where(*base_cond)
            .order_by(desc(ProductMaterial.created_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = (await self.session.execute(stmt)).scalars().all()

        material_ids = [r.id for r in rows]
        pub_map = await self._build_published_map(material_ids)
        src_map = await self._build_source_map(material_ids)

        return {
            "list": [_material_to_dict(r, pub_map.get(r.id, []), src_map.get(r.id, [])) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size if total else 0,
        }

    async def get(self, material_id: int, user_id: int = None) -> Optional[ProductMaterial]:
        """查询单条素材
        
        Args:
            material_id: 素材ID
            user_id: 用户ID，为None时不限用户（管理员场景）
        """
        conds = [ProductMaterial.id == material_id]
        if user_id is not None:
            conds.append(ProductMaterial.user_id == user_id)
        stmt = select(ProductMaterial).where(*conds)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_by_ids(self, material_ids: List[int], user_id: int) -> List[ProductMaterial]:
        if not material_ids:
            return []
        unique_ids = list(dict.fromkeys(material_ids))
        stmt = select(ProductMaterial).where(
            ProductMaterial.user_id == user_id,
            ProductMaterial.id.in_(unique_ids),
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        material_map = {row.id: row for row in rows}
        return [material_map[mid] for mid in material_ids if mid in material_map]

    async def update(self, material_id: int, user_id: int = None, data: dict = None) -> Optional[ProductMaterial]:
        """更新素材（user_id=None时管理员可操作任意素材）"""
        data = data or {}
        material = await self.get(material_id, user_id)
        if not material:
            return None

        updatable = [
            "title", "description", "price", "original_price", "category",
            "images", "delivery_method", "postage", "address", "brand",
            "condition", "remark",
        ]
        for field in updatable:
            if field in data and data[field] is not None:
                value = data[field]
                if field in ("price", "original_price", "postage"):
                    value = float(value) if value else (None if field == "original_price" else 0)
                setattr(material, field, value)

        await self.session.commit()
        await self.session.refresh(material)
        return material

    async def delete(self, material_id: int, user_id: int = None) -> bool:
        """删除素材（user_id=None时管理员可操作任意素材）"""
        material = await self.get(material_id, user_id)
        if not material:
            return False
        await self.session.delete(material)
        await self.session.commit()
        return True

    async def batch_delete(self, material_ids: List[int], user_id: int = None) -> int:
        """批量删除素材，返回实际删除数量
        
        Args:
            material_ids: 素材ID列表
            user_id: 用户ID，为None时管理员可操作任意素材
        """
        if not material_ids:
            return 0
        from sqlalchemy import delete as sa_delete
        conds = [ProductMaterial.id.in_(material_ids)]
        if user_id is not None:
            conds.append(ProductMaterial.user_id == user_id)
        stmt = sa_delete(ProductMaterial).where(*conds)
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount


# ==================== 工具函数 ====================

def _material_to_dict(m: ProductMaterial, published_accounts: list[str] = None,
                      sources: list[dict] = None) -> dict:
    """将素材模型转为字典"""
    return {
        "id": m.id,
        "user_id": m.user_id,
        "title": m.title,
        "description": m.description,
        "price": float(m.price) if m.price is not None else 0,
        "original_price": float(m.original_price) if m.original_price is not None else None,
        "category": m.category,
        "images": m.images or [],
        "stock": getattr(m, "stock", None) or 9999,
        "spec_name": getattr(m, "spec_name", None) or "份数",
        "spec_value": getattr(m, "spec_value", None) or "1份",
        "delivery_method": m.delivery_method,
        "postage": float(m.postage) if m.postage is not None else 0,
        "address": m.address,
        "brand": m.brand,
        "condition": m.condition,
        "remark": m.remark,
        "created_at": safe_isoformat(m.created_at),
        "updated_at": safe_isoformat(m.updated_at),
        "published_accounts": published_accounts or [],
        "sources": sources or [],
    }
