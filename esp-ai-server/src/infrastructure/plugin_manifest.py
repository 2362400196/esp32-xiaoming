"""插件包 manifest.json 模型与验证逻辑。

插件包结构（zip）：
    manifest.json   # 必需，插件元数据
    plugin.py       # 必需，工具注册入口（@tool 装饰器）
    <其他资源文件>   # 可选，插件自带的静态资源

manifest.json 示例：
    {
        "id": "weather",
        "name": "天气",
        "version": "1.0.0",
        "author": "system",
        "description": "查询实时天气、温湿度、空气质量并显示天气卡片",
        "api_version": "1.0",
        "requires": [],
        "config_fields": [],
        "permissions": [],
        "signature": ""
    }

设计说明：
    - PluginManifest 使用 Pydantic v2 BaseModel，自带字段校验。
    - from_zip() 从 zip 包内读取 manifest.json 而不解压，避免临时文件。
    - validate_compatibility() 检查 api_version 与当前系统支持的版本是否兼容。
    - to_meta_dict() 转换为 plugin_loader 使用的元数据字典（name/description/requires/config_fields）。
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


# 当前系统支持的插件 API 版本列表（语义化版本，只到 major.minor）
# 新增不兼容改动时，bump major 版本并加入此列表
SUPPORTED_API_VERSIONS: list[str] = ["1.0"]

# manifest.json 在 zip 包内的文件名（根目录或子目录均可）
_MANIFEST_ENTRY = "manifest.json"

# plugin.py 在 zip 包内的文件名
_PLUGIN_ENTRY = "plugin.py"


class PluginManifest(BaseModel):
    """插件包清单（对应 zip 包内 manifest.json）。"""

    id: str = Field(..., description="插件ID（英文，如 'weather'）")
    name: str = Field(..., description="显示名称（中文，如 '天气'）")
    version: str = Field(default="1.0.0", description="语义化版本（如 '1.0.0'）")
    author: str = Field(default="", description="作者")
    description: str = Field(default="", description="描述")
    api_version: str = Field(default="1.0", description="API兼容版本")
    requires: list[str] = Field(default_factory=list, description="能力要求（如 ['display']）")
    config_fields: list[dict[str, Any]] = Field(
        default_factory=list, description="配置字段声明"
    )
    permissions: list[str] = Field(
        default_factory=list, description="权限声明（network/file_read等）"
    )
    signature: str = Field(default="", description="开发者签名（base64）")

    # 忽略 manifest.json 中未声明的额外字段，保持前向兼容
    model_config = {"extra": "ignore"}

    @field_validator("id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        """校验插件 ID：非空且仅含字母、数字、下划线、连字符（防止路径穿越）。"""
        if not v or not v.strip():
            raise ValueError("插件 id 不能为空")
        v = v.strip()
        if not all(c.isalnum() or c in ("_", "-") for c in v):
            raise ValueError("插件 id 只能包含字母、数字、下划线和连字符")
        return v

    @field_validator("version")
    @classmethod
    def _validate_version(cls, v: str) -> str:
        """版本号校验：非空时需为 x.y[.z] 格式，缺省返回 1.0.0。"""
        if not v:
            return "1.0.0"
        parts = v.split(".")
        # 至少要有 major.minor 两段，每段以数字开头
        if len(parts) < 2:
            raise ValueError(f"版本号格式错误（需 x.y[.z]）: {v}")
        for part in parts:
            if not part or not part[0].isdigit():
                raise ValueError(f"版本号格式错误（需 x.y[.z]）: {v}")
        return v

    @classmethod
    def from_zip(cls, zip_path: Path) -> "PluginManifest":
        """从 zip 包中读取 manifest.json 并解析（不解压整个包）。

        Args:
            zip_path: zip 文件路径

        Returns:
            PluginManifest 实例

        Raises:
            FileNotFoundError: zip 文件不存在
            ValueError: zip 包损坏或缺少 manifest.json 或解析失败
        """
        zip_path = Path(zip_path)
        if not zip_path.is_file():
            raise FileNotFoundError(f"插件包不存在: {zip_path}")

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                manifest_name = _find_entry(zf, _MANIFEST_ENTRY)
                if manifest_name is None:
                    raise ValueError(
                        f"zip 包内缺少 manifest.json: {zip_path}"
                    )
                raw = zf.read(manifest_name)
        except zipfile.BadZipFile as e:
            raise ValueError(f"zip 包损坏: {zip_path} -> {e}") from e

        try:
            data = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ValueError(f"manifest.json 解析失败: {e}") from e

        return cls.model_validate(data)

    def validate_compatibility(self) -> bool:
        """检查 api_version 是否与当前系统兼容。

        兼容规则：
            1. api_version 在 SUPPORTED_API_VERSIONS 中 -> 完全兼容
            2. api_version 主版本号在已支持主版本号集合中 -> 兼容（同 major）
            3. 其他 -> 不兼容
        """
        if not self.api_version:
            # 缺省视为兼容（内置/旧插件未声明 api_version）
            return True
        if self.api_version in SUPPORTED_API_VERSIONS:
            return True
        # 主版本号匹配检查（如 1.0 vs 1.1 同属 1.x，视为兼容）
        supported_majors = {v.split(".")[0] for v in SUPPORTED_API_VERSIONS}
        manifest_major = self.api_version.split(".")[0]
        return manifest_major in supported_majors

    def to_meta_dict(self) -> dict:
        """转换为 plugin_loader 使用的元数据字典。

        返回 name/description/requires/config_fields 四个字段。
        """
        return {
            "name": self.name,
            "description": self.description,
            "requires": list(self.requires),
            "config_fields": list(self.config_fields),
        }


def _find_entry(zf: zipfile.ZipFile, target_name: str) -> str | None:
    """在 zip 包内查找指定文件名的条目（支持根目录或单层子目录）。

    优先返回根目录下的条目，其次返回子目录下的。

    Args:
        zf: 已打开的 ZipFile 对象
        target_name: 目标文件名（如 "manifest.json"）

    Returns:
        匹配的 zip 条目名，或 None
    """
    names = zf.namelist()
    # 优先匹配根目录
    for n in names:
        normalized = n.replace("\\", "/")
        if normalized == target_name:
            return n
    # 其次匹配子目录（单层）
    for n in names:
        normalized = n.replace("\\", "/")
        if normalized.endswith("/" + target_name) and normalized.count("/") == 1:
            return n
    return None


def zip_has_plugin_py(zip_path: Path) -> bool:
    """检查 zip 包内是否包含 plugin.py（安装前校验）。

    Args:
        zip_path: zip 文件路径

    Returns:
        True 如果 zip 包内存在 plugin.py
    """
    zip_path = Path(zip_path)
    if not zip_path.is_file():
        return False
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            return _find_entry(zf, _PLUGIN_ENTRY) is not None
    except zipfile.BadZipFile:
        return False


def load_manifest_from_dir(plugin_dir: Path) -> PluginManifest | None:
    """从已解压的插件目录读取 manifest.json。

    Args:
        plugin_dir: 插件目录路径（如 data/plugins/installed/weather/）

    Returns:
        PluginManifest 实例，或 None（目录无 manifest.json 时）
    """
    manifest_file = Path(plugin_dir) / _MANIFEST_ENTRY
    if not manifest_file.is_file():
        return None
    try:
        data = json.loads(manifest_file.read_text(encoding="utf-8"))
        return PluginManifest.model_validate(data)
    except Exception:
        return None
