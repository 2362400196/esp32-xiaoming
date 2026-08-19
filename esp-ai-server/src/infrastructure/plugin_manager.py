"""本地插件管理器：处理插件的安装、卸载、更新。

安装流程（install_from_zip）：
    1. 从 zip 读取并验证 manifest.json（PluginManifest.from_zip）
    2. 检查 api_version 兼容性（manifest.validate_compatibility）
    3. 校验 zip 内含 plugin.py（zip_has_plugin_py）
    4. 如已存在同 ID 插件，先卸载旧版
    5. 解压到 INSTALLED_DIR/{plugin_id}/（自动展平单层根目录）
    6. 验证解压后 plugin.py 存在
    7. 调用 plugin_loader.reload_single_plugin 加载
    8. 返回安装结果

卸载流程（uninstall）：
    1. 校验非内置插件（内置插件不可卸载）
    2. 调用 plugin_loader._unload_plugin 注销工具
    3. 删除 INSTALLED_DIR/{plugin_id}/ 目录

更新流程（update_plugin）：
    1. 从市场查询最新版本
    2. 下载 zip 到缓存
    3. 卸载旧版 → 安装新版

市场 API 约定（可通过 PLUGIN_MARKETPLACE_URL 环境变量配置）：
    GET  {base}/api/plugins/{slug}/info            -> {"version": "1.1.0", ...}
    GET  {base}/api/plugins/{slug}/download?version={version} -> zip 文件流
"""

from __future__ import annotations

import os
import shutil
import zipfile
from pathlib import Path

import httpx

from src.infrastructure.logging import get_logger
from src.infrastructure.plugin_manifest import (
    PluginManifest,
    zip_has_plugin_py,
)

logger = get_logger(__name__)

# 默认市场 API 基址（可通过环境变量 PLUGIN_MARKETPLACE_URL 覆盖）
_DEFAULT_MARKETPLACE_URL = "https://marketplace.esp-ai.com"

# HTTP 下载超时（秒）
_DOWNLOAD_TIMEOUT = 60.0


def _get_marketplace_url() -> str:
    """获取市场 API 基址（优先环境变量 PLUGIN_MARKETPLACE_URL）。"""
    return os.environ.get("PLUGIN_MARKETPLACE_URL", _DEFAULT_MARKETPLACE_URL).rstrip("/")


def _parse_version(v: str) -> tuple[int, ...]:
    """解析语义化版本字符串为可比较的元组。

    "1.2.3" -> (1, 2, 3)
    "1.2"   -> (1, 2, 0)
    非数字前缀部分视为 0。
    """
    if not v:
        return (0, 0, 0)
    parts = v.split(".")
    nums: list[int] = []
    for p in parts:
        # 提取前导数字
        num_str = ""
        for c in p:
            if c.isdigit():
                num_str += c
            else:
                break
        nums.append(int(num_str) if num_str else 0)
    # 补齐到 3 段
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)


def _version_gt(a: str, b: str) -> bool:
    """返回 True 如果版本 a > b。"""
    return _parse_version(a) > _parse_version(b)


class PluginManager:
    """本地插件管理器：安装、卸载、更新插件包。"""

    INSTALLED_DIR: Path  # 已安装插件目录（与 plugin_loader.INSTALLED_PLUGINS_DIR 一致）
    CACHE_DIR: Path      # zip 缓存目录

    def __init__(self) -> None:
        # 从 plugin_loader 导入路径常量，保持单一数据源
        from src.infrastructure.plugin_loader import (
            INSTALLED_PLUGINS_DIR,
            PLUGINS_CACHE_DIR,
        )
        self.INSTALLED_DIR = INSTALLED_PLUGINS_DIR
        self.CACHE_DIR = PLUGINS_CACHE_DIR

    def _ensure_dirs(self) -> None:
        """确保安装目录和缓存目录存在。"""
        self.INSTALLED_DIR.mkdir(parents=True, exist_ok=True)
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # ──────────────────────────────────────────────────────────
    # 安装
    # ──────────────────────────────────────────────────────────

    async def install_from_zip(self, zip_path: Path) -> dict:
        """从 zip 包安装插件。

        流程：验证 manifest → 检查兼容性 → 校验 plugin.py → 卸载旧版 →
              解压到 INSTALLED_DIR/{id}/ → 验证 plugin.py → 加载插件

        Args:
            zip_path: zip 文件路径

        Returns:
            {"success": bool, "plugin_id": str, "name": str, "version": str,
             "message": str, "tools": list[str]}
        """
        self._ensure_dirs()
        zip_path = Path(zip_path)

        try:
            # 1. 读取并验证 manifest
            manifest = PluginManifest.from_zip(zip_path)
        except (FileNotFoundError, ValueError) as e:
            msg = f"manifest 验证失败: {e}"
            logger.error(f"[插件管理] {msg}")
            return {"success": False, "message": msg, "tools": []}

        # 2. 检查 API 兼容性
        if not manifest.validate_compatibility():
            from src.infrastructure.plugin_manifest import SUPPORTED_API_VERSIONS
            msg = (f"插件 {manifest.id} 的 api_version({manifest.api_version}) "
                   f"与当前系统不兼容（支持: {SUPPORTED_API_VERSIONS}）")
            logger.error(f"[插件管理] {msg}")
            return {"success": False, "message": msg, "tools": []}

        # 3. 校验 zip 内含 plugin.py
        if not zip_has_plugin_py(zip_path):
            msg = f"zip 包内缺少 plugin.py: {zip_path}"
            logger.error(f"[插件管理] {msg}")
            return {"success": False, "message": msg, "tools": []}

        plugin_id = manifest.id
        dest_dir = self.INSTALLED_DIR / plugin_id

        # 4. 如已存在同 ID 插件，先卸载旧版（支持覆盖安装）
        if dest_dir.exists():
            logger.info(f"[插件管理] 插件 {plugin_id} 已存在，先卸载旧版")
            await self._do_unload(plugin_id)
            # 删除旧目录
            if dest_dir.exists():
                shutil.rmtree(dest_dir, ignore_errors=True)

        # 5. 解压到目标目录
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            self._extract_zip(zip_path, dest_dir)
        except Exception as e:
            # 解压失败，清理残留
            if dest_dir.exists():
                shutil.rmtree(dest_dir, ignore_errors=True)
            msg = f"解压失败: {e}"
            logger.error(f"[插件管理] {msg}")
            return {"success": False, "message": msg, "tools": []}

        # 6. 验证解压后 plugin.py 存在
        plugin_file = dest_dir / "plugin.py"
        if not plugin_file.is_file():
            # 清理残留
            shutil.rmtree(dest_dir, ignore_errors=True)
            msg = f"解压后未找到 plugin.py: {dest_dir}"
            logger.error(f"[插件管理] {msg}")
            return {"success": False, "message": msg, "tools": []}

        # 7. 加载插件
        from src.infrastructure.plugin_loader import reload_single_plugin
        loaded = reload_single_plugin(plugin_id)
        if not loaded:
            msg = (f"插件 {plugin_id} 解压成功但加载失败，请检查 plugin.py 语法")
            logger.error(f"[插件管理] {msg}")
            return {"success": False, "plugin_id": plugin_id, "message": msg, "tools": []}

        # 8. 获取加载后的工具列表
        from src.infrastructure.plugin_loader import _loaded_tools
        tools = _loaded_tools.get(plugin_id, [])

        logger.info(
            f"[插件管理] 插件 {plugin_id} v{manifest.version} 安装成功，"
            f"工具: {tools}"
        )
        return {
            "success": True,
            "plugin_id": plugin_id,
            "name": manifest.name,
            "version": manifest.version,
            "author": manifest.author,
            "description": manifest.description,
            "message": f"插件 {manifest.name} v{manifest.version} 安装成功",
            "tools": tools,
        }

    async def install_from_marketplace(
        self, plugin_slug: str, version: str = "latest"
    ) -> dict:
        """从云市场下载并安装插件。

        流程：
            1. 从市场 API 下载 zip 到 CACHE_DIR
            2. 调用 install_from_zip 安装

        Args:
            plugin_slug: 插件 slug（市场标识，通常等于插件 id）
            version: 要安装的版本，"latest" 表示最新

        Returns:
            安装结果（同 install_from_zip）
        """
        self._ensure_dirs()
        base_url = _get_marketplace_url()

        if not base_url:
            return {
                "success": False,
                "message": "市场地址未配置（设置 PLUGIN_MARKETPLACE_URL 环境变量）",
                "tools": [],
            }

        # 1. 下载 zip
        download_url = f"{base_url}/api/v1/marketplace/plugins/{plugin_slug}/download"
        params = {"version": version} if version and version != "latest" else {}

        cache_zip = self.CACHE_DIR / f"{plugin_slug}_{version}.zip"
        logger.info(f"[插件管理] 从市场下载: {download_url} -> {cache_zip}")

        try:
            async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT) as client:
                resp = await client.get(download_url, params=params, follow_redirects=True)
                resp.raise_for_status()
                cache_zip.write_bytes(resp.content)
        except httpx.HTTPStatusError as e:
            msg = f"市场下载失败（HTTP {e.response.status_code}）: {e}"
            logger.error(f"[插件管理] {msg}")
            return {"success": False, "message": msg, "tools": []}
        except (httpx.RequestError, Exception) as e:
            msg = f"市场下载失败（网络错误）: {e}"
            logger.error(f"[插件管理] {msg}")
            return {"success": False, "message": msg, "tools": []}

        # 2. 安装下载的 zip
        result = await self.install_from_zip(cache_zip)

        # 安装完成后清理缓存 zip
        try:
            if cache_zip.exists():
                cache_zip.unlink()
        except OSError:
            pass

        return result

    # ──────────────────────────────────────────────────────────
    # 卸载
    # ──────────────────────────────────────────────────────────

    async def uninstall(self, plugin_name: str) -> dict:
        """卸载插件。

        流程：
            1. 校验非内置插件（内置不可卸载）
            2. 注销工具（_unload_plugin）
            3. 删除 INSTALLED_DIR/{plugin_name}/ 目录

        Args:
            plugin_name: 插件 ID

        Returns:
            {"success": bool, "message": str}
        """
        from src.infrastructure.plugin_loader import (
            is_builtin_plugin,
            is_installed_plugin,
        )

        # 1. 校验非内置插件
        if is_builtin_plugin(plugin_name) and not is_installed_plugin(plugin_name):
            msg = f"内置插件 {plugin_name} 不可卸载"
            logger.warning(f"[插件管理] {msg}")
            return {"success": False, "message": msg}

        plugin_dir = self.INSTALLED_DIR / plugin_name
        if not plugin_dir.is_dir():
            msg = f"插件 {plugin_name} 未安装（目录不存在: {plugin_dir}）"
            logger.warning(f"[插件管理] {msg}")
            return {"success": False, "message": msg}

        # 2. 注销工具
        await self._do_unload(plugin_name)

        # 3. 删除目录
        try:
            shutil.rmtree(plugin_dir, ignore_errors=True)
        except Exception as e:
            msg = f"删除插件目录失败: {e}"
            logger.error(f"[插件管理] {msg}")
            return {"success": False, "message": msg}

        logger.info(f"[插件管理] 插件 {plugin_name} 已卸载")
        return {"success": True, "message": f"插件 {plugin_name} 已卸载"}

    async def _do_unload(self, plugin_name: str) -> None:
        """注销插件工具（不删除目录，供安装覆盖时复用）。"""
        from src.infrastructure.plugin_loader import _unload_plugin
        try:
            _unload_plugin(plugin_name)
        except Exception as e:
            logger.warning(f"[插件管理] 卸载工具时异常（可忽略）: {e}")

    # ──────────────────────────────────────────────────────────
    # 更新检查
    # ──────────────────────────────────────────────────────────

    async def check_updates(self) -> list[dict]:
        """检查所有已安装插件是否有新版本。

        Returns:
            [{"name": str, "current_version": str, "latest_version": str,
              "has_update": bool}, ...]
        """
        installed = self.list_installed()
        if not installed:
            return []

        base_url = _get_marketplace_url()
        if not base_url:
            logger.warning("[插件管理] 市场地址未配置，无法检查更新")
            return []

        results: list[dict] = []
        async with httpx.AsyncClient(timeout=15.0) as client:
            for plugin in installed:
                name = plugin["name"]
                current = plugin["version"]
                slug = plugin.get("slug", name)
                info_url = f"{base_url}/api/v1/marketplace/plugins/{slug}"
                try:
                    resp = await client.get(info_url, follow_redirects=True)
                    if resp.status_code != 200:
                        results.append({
                            "name": name,
                            "current_version": current,
                            "latest_version": current,
                            "has_update": False,
                            "error": f"市场返回 HTTP {resp.status_code}",
                        })
                        continue
                    data = resp.json()
                    # 市场 API 返回 {"code": 0, "data": {"latest_version": "1.1.0", ...}}
                    plugin_data = data.get("data") or data
                    latest = plugin_data.get("latest_version", current)
                    results.append({
                        "name": name,
                        "current_version": current,
                        "latest_version": latest,
                        "has_update": _version_gt(latest, current),
                    })
                except Exception as e:
                    results.append({
                        "name": name,
                        "current_version": current,
                        "latest_version": current,
                        "has_update": False,
                        "error": str(e),
                    })

        return results

    async def update_plugin(self, plugin_name: str) -> dict:
        """更新插件到最新版本。

        流程：
            1. 校验插件已安装
            2. 从市场下载最新版 zip
            3. 卸载旧版
            4. 安装新版

        Args:
            plugin_name: 插件 ID

        Returns:
            更新结果（同 install_from_zip）
        """
        from src.infrastructure.plugin_loader import is_installed_plugin

        if not is_installed_plugin(plugin_name):
            return {
                "success": False,
                "message": f"插件 {plugin_name} 未安装，无法更新",
                "tools": [],
            }

        # 通过市场安装最新版（install_from_marketplace 会先卸载旧版再安装）
        result = await self.install_from_marketplace(plugin_name, version="latest")
        if result.get("success"):
            result["message"] = f"插件 {plugin_name} 更新成功"
        return result

    # ──────────────────────────────────────────────────────────
    # 列表
    # ──────────────────────────────────────────────────────────

    def list_installed(self) -> list[dict]:
        """列出所有已安装插件（含版本、来源）。

        扫描 INSTALLED_DIR 目录，读取每个插件的 manifest.json 获取版本信息。
        同时合并 plugin_loader 中已加载的插件运行时状态。

        Returns:
            [{"name": str, "version": str, "source": str, "slug": str, ...}, ...]
        """
        from src.infrastructure.plugin_loader import (
            _loaded_tools,
            _plugin_source,
            _plugin_version,
        )
        from src.infrastructure.plugin_manifest import load_manifest_from_dir

        out: list[dict] = []

        if not self.INSTALLED_DIR.is_dir():
            return out

        for entry in sorted(self.INSTALLED_DIR.iterdir()):
            if not entry.is_dir():
                continue
            name = entry.name
            # 优先从 manifest.json 读取
            manifest = load_manifest_from_dir(entry)
            if manifest is not None:
                out.append({
                    "name": name,
                    "display_name": manifest.name,
                    "version": manifest.version,
                    "author": manifest.author,
                    "description": manifest.description,
                    "source": "installed",
                    "slug": manifest.id,
                    "requires": list(manifest.requires),
                    "tools": _loaded_tools.get(name, []),
                    "loaded": name in _loaded_tools,
                })
            else:
                # 无 manifest，从加载状态获取版本
                out.append({
                    "name": name,
                    "display_name": name,
                    "version": _plugin_version.get(name, "1.0.0"),
                    "author": "",
                    "description": "",
                    "source": _plugin_source.get(name, "installed"),
                    "slug": name,
                    "requires": [],
                    "tools": _loaded_tools.get(name, []),
                    "loaded": name in _loaded_tools,
                })

        return out

    # ──────────────────────────────────────────────────────────
    # 内部工具方法
    # ──────────────────────────────────────────────────────────

    @staticmethod
    def _extract_zip(zip_path: Path, dest_dir: Path) -> None:
        """解压 zip 到目标目录，自动展平单层根目录。

        如果 zip 内所有文件都在同一个顶层目录下（如 weather/plugin.py），
        则将内容提升到 dest_dir 根级（dest_dir/plugin.py）。

        Args:
            zip_path: zip 文件路径
            dest_dir: 目标目录（需已存在）
        """
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(dest_dir)

        # 检查是否有单一顶层目录需要展平
        entries = list(dest_dir.iterdir())
        if len(entries) == 1 and entries[0].is_dir():
            top_dir = entries[0]
            # 将顶层目录内的所有内容移动到 dest_dir
            for item in list(top_dir.iterdir()):
                target = dest_dir / item.name
                if target.exists():
                    # 同名冲突时跳过（保留已有文件）
                    if target.is_dir():
                        shutil.rmtree(target, ignore_errors=True)
                    else:
                        target.unlink(missing_ok=True)
                item.rename(target)
            # 删除空的顶层目录
            try:
                top_dir.rmdir()
            except OSError:
                # 目录非空（可能 rename 失败），忽略
                pass


# 模块级单例（供路由层直接使用）
_plugin_manager: PluginManager | None = None


def get_plugin_manager() -> PluginManager:
    """获取 PluginManager 单例。"""
    global _plugin_manager
    if _plugin_manager is None:
        _plugin_manager = PluginManager()
    return _plugin_manager
