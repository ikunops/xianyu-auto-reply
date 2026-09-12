"""
版本路由

功能：
1. 提供系统当前版本号查询接口

接口规范：
- 所有接口统一返回 ApiResponse（success/message/data）。
"""
from __future__ import annotations

from fastapi import APIRouter

from app.services.version_service import get_current_version
from common.schemas.common import ApiResponse

router = APIRouter(prefix="/version", tags=["版本检测"])


@router.get("/current", response_model=ApiResponse)
async def get_current_version_api() -> ApiResponse:
    """
    获取系统当前版本号

    Returns:
        ApiResponse.data: { version: str }
    """
    version = get_current_version()
    if not version:
        return ApiResponse(success=False, message="无法读取当前版本号")
    return ApiResponse(success=True, data={"version": version})
