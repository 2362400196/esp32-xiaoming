"""云市场插件包存储管理（本地文件系统）

存储约定：
  ``MARKETPLACE_STORAGE_DIR / <slug> / <version>.zip``

  - 同一插件的不同版本以 ``<version>.zip`` 区分，便于按版本下载
  - ``save_package`` 返回相对 ``MARKETPLACE_STORAGE_DIR`` 的相对路径，DB 只存相对路径
  - ``get_package_path`` 把相对路径还原为绝对路径，供 ``FileResponse`` 下载

校验和：
  ``compute_checksum`` 计算 SHA256（hexdigest），用于上传时存 DB、下载时校验完整性。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from src.infrastructure.logging import get_logger

logger = get_logger(__name__)

# 存放上传的 zip 包。相对路径 "data/marketplace/packages" 与数据库 (data/esp_ai.db) 同级，
# 在应用 CWD（项目根目录）下创建。
MARKETPLACE_STORAGE_DIR = Path("data/marketplace/packages")


def _ensure_storage_dir() -> None:
    """确保存储根目录存在（幂等）。"""
    MARKETPLACE_STORAGE_DIR.mkdir(parents=True, exist_ok=True)


def _slug_dir(slug: str) -> Path:
    """获取插件 slug 对应的目录（绝对路径）。"""
    _ensure_storage_dir()
    return MARKETPLACE_STORAGE_DIR / slug


async def save_package(zip_bytes: bytes, slug: str, version: str) -> str:
    """保存上传的插件包，返回相对 ``MARKETPLACE_STORAGE_DIR`` 的相对路径。

    Args:
        zip_bytes: zip 包二进制内容
        slug: 插件 slug（manifest.id 转小写）
        version: 语义化版本号

    Returns:
        相对路径字符串，如 "weather/1.0.0.zip"
    """
    plugin_dir = _slug_dir(slug)
    plugin_dir.mkdir(parents=True, exist_ok=True)
    file_path = plugin_dir / f"{version}.zip"
    # 使用 to_thread 避免阻塞事件循环
    import asyncio

    await asyncio.to_thread(file_path.write_bytes, zip_bytes)
    rel_path = file_path.relative_to(MARKETPLACE_STORAGE_DIR).as_posix()
    logger.info(
        f"[Marketplace] 插件包已保存: slug={slug} version={version} "
        f"size={len(zip_bytes)}B path={rel_path}"
    )
    return rel_path


async def get_package_path(slug: str, version: str) -> Path:
    """获取插件包绝对路径。

    Args:
        slug: 插件 slug
        version: 版本号，或 "latest" 表示最新版本（需调用方解析后传入具体版本号）

    Returns:
        zip 包的绝对路径 ``Path`` 对象
    """
    return _slug_dir(slug) / f"{version}.zip"


async def compute_checksum(file_path: Path) -> str:
    """计算文件的 SHA256 校验和（hexdigest）。

    使用分块读取（8MB 一块），避免大文件一次性占满内存。
    """
    import asyncio

    def _calc() -> str:
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    return await asyncio.to_thread(_calc)


__all__ = [
    "MARKETPLACE_STORAGE_DIR",
    "save_package",
    "get_package_path",
    "compute_checksum",
]
