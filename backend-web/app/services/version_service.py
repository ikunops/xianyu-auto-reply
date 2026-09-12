"""
版本服务

功能：
1. 获取系统当前版本号（复用桌面启动器的版本号常量）
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger


def get_current_version() -> str:
    """
    获取系统当前版本号

    优先复用桌面启动器的版本号常量（launcher.version.CURRENT_VERSION），
    以保证 Windows 桌面版与 Web 端版本号一致；若导入失败则尝试从
    data/version.txt 读取，最后返回空字符串由调用方决定如何向用户提示。

    Returns:
        当前版本号字符串（如 "1.0.3"），失败时返回空字符串
    """
    # 方式1：尝试从 launcher 模块读取（开发模式或完整打包时可用）
    try:
        from launcher.version import CURRENT_VERSION  # type: ignore
        version = str(CURRENT_VERSION or "").strip()
        if version:
            return version
    except Exception:
        pass

    # 方式2：从 data/version.txt 文件读取（打包后独立运行时可用）
    try:
        version_file = Path.cwd() / "data" / "version.txt"
        if version_file.exists():
            version = version_file.read_text(encoding="utf-8").strip()
            if version:
                return version
    except Exception as exc:
        logger.warning(f"从 data/version.txt 读取版本号失败: {exc}")

    # 方式3：从项目根目录的 version.txt 读取
    try:
        version_file = Path.cwd() / "version.txt"
        if version_file.exists():
            version = version_file.read_text(encoding="utf-8").strip()
            if version:
                return version
    except Exception as exc:
        logger.warning(f"从 version.txt 读取版本号失败: {exc}")

    return ""
