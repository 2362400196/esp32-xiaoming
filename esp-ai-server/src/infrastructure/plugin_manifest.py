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

from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


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
    dependencies: list[str] = Field(
        default_factory=list, description="依赖的 pip 包名（如 ['httpx']）"
    )
    config_fields: list[dict[str, Any]] = Field(
        default_factory=list, description="配置字段声明"
    )
    permissions: list[str] = Field(
        default_factory=list, description="权限声明（network/file_read等）"
    )
    optional: bool = Field(
        default=False, description="可选插件，默认不安装，需用户从商店启用"
    )
    frontend: bool = Field(
        default=False, description="是否包含前端页面"
    )
    frontend_config: dict[str, Any] = Field(
        default_factory=dict, description="前端页面配置（nav_label, nav_icon, width 等）"
    )
    file_hashes: list[dict[str, str]] = Field(
        default_factory=list, description="包内每个文件的 SHA-256（签名负载的一部分）"
    )
    signature: str = Field(default="", description="开发者签名（base64, Ed25519）")

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
        """转换为 plugin_loader 使用的元数据字典。"""
        return {
            "name": self.name,
            "description": self.description,
            "requires": list(self.requires),
            "config_fields": list(self.config_fields),
            "permissions": list(self.permissions),  # 运行时权限校验用
            "optional": self.optional,
            "frontend": self.frontend,
            "frontend_config": dict(self.frontend_config),
        }

    # ──────────────────────────────────────────────────────────
    # 签名（Ed25519，基于 cryptography 库）
    # ──────────────────────────────────────────────────────────

    def signature_payload(self) -> bytes:
        """签名的 canonical payload（排除 signature 字段）。

        字段顺序固定、JSON 序列化键排序，保证不同语言/库签名一致。
        包含 file_hashes：签名覆盖包内每个文件的哈希，防止文件被单独篡改。
        """
        payload = {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "api_version": self.api_version,
            "requires": list(self.requires),
            "dependencies": list(self.dependencies),
            "config_fields": list(self.config_fields),
            "permissions": list(self.permissions),
            "optional": self.optional,
            "file_hashes": sorted(self.file_hashes, key=lambda h: h.get("path", "")),
        }
        return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def has_signature(self) -> bool:
        return bool(self.signature)

    def verify_signature(self, public_key_b64: str | None = None) -> bool:
        """验证插件签名。

        Args:
            public_key_b64: base64 编码的 Ed25519 公钥（可选）。
                为 None 时从环境变量 PLUGIN_SIGN_PUBLIC_KEY 读取。

        Returns:
            无签名或未配置公钥 → True（视为"未签名/不校验"）；
            配置了公钥但签名缺失或验证失败 → False。
        """
        if not self.signature:
            # 未签名插件：仅在"已配置公钥强制签名"时拒绝
            if public_key_b64 is None:
                public_key_b64 = _get_sign_public_key()
            return public_key_b64 is None
        try:
            import base64

            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

            if public_key_b64 is None:
                public_key_b64 = _get_sign_public_key()
            if not public_key_b64:
                logger.warning("[插件签名] 插件含签名但未配置 PLUGIN_SIGN_PUBLIC_KEY，跳过验证")
                return True
            pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
            pub.verify(base64.b64decode(self.signature), self.signature_payload())
            return True
        except Exception as e:
            logger.error(f"[插件签名] 签名验证失败（{self.id} v{self.version}）: {e}")
            return False

    def verify_files(self, plugin_dir) -> bool:
        """校验插件目录内文件哈希与 manifest.file_hashes 一致。

        任一文件缺失/哈希不匹配/存在未声明文件均返回 False（防文件被单独篡改）。
        """
        if not self.file_hashes:
            return True
        expected = {h.get("path", ""): h.get("sha256", "").lower() for h in self.file_hashes}
        if not all(expected.values()):
            return False
        plugin_dir = Path(plugin_dir)
        try:
            actual = {
                f.relative_to(plugin_dir).as_posix(): _sha256_of(f)
                for f in plugin_dir.rglob("*")
                if f.is_file()
            }
        except OSError:
            return False
        # 未声明文件：拒绝（防止被注入额外可执行文件）
        if set(actual) != set(expected):
            logger.error(
                f"[插件签名] {self.id} 文件清单与 manifest.file_hashes 不一致: "
                f"多余={sorted(set(actual) - set(expected))} 缺失={sorted(set(expected) - set(actual))}"
            )
            return False
        for path, digest in expected.items():
            if actual.get(path) != digest:
                logger.error(f"[插件签名] {self.id} 文件哈希不匹配: {path}")
                return False
        return True

    def verify_package(self, plugin_dir, public_key_b64: str | None = None) -> bool:
        """完整校验：签名 + 文件哈希。返回是否通过。"""
        if not self.verify_signature(public_key_b64):
            return False
        if not self.verify_files(plugin_dir):
            return False
        return True


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


def _get_sign_public_key() -> str | None:
    """读取签名公钥（环境变量 PLUGIN_SIGN_PUBLIC_KEY，base64 编码）。"""
    import os
    v = os.environ.get("PLUGIN_SIGN_PUBLIC_KEY", "").strip()
    return v or None


def _sha256_of(path: Path) -> str:
    """计算文件 SHA-256（hex）。"""
    import hashlib

    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_file_hashes(plugin_dir) -> list[dict[str, str]]:
    """计算插件目录内所有文件的 SHA-256，返回 [{path, sha256}, ...]。"""
    plugin_dir = Path(plugin_dir)
    return sorted(
        (
            {"path": f.relative_to(plugin_dir).as_posix(), "sha256": _sha256_of(f)}
            for f in plugin_dir.rglob("*")
            if f.is_file()
        ),
        key=lambda h: h["path"],
    )


def sign_manifest_data(data: dict, private_key_b64: str) -> str:
    """为 manifest 数据生成 Ed25519 签名（base64 输出）。

    用于插件开发者在本地对 manifest.json 签名：
        from src.infrastructure.plugin_manifest import PluginManifest, sign_manifest_data
        m = PluginManifest.model_validate(data)
        m.signature = sign_manifest_data(data, PRIVATE_KEY)
    """
    import base64

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    m = PluginManifest.model_validate(data)
    key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_key_b64))
    return base64.b64encode(key.sign(m.signature_payload())).decode("ascii")


def sign_package(plugin_dir, private_key_b64: str) -> tuple[str, dict]:
    """为插件目录生成签名（计算文件哈希 + 写入签名）。

    Args:
        plugin_dir: 插件目录（必须含 manifest.json）
        private_key_b64: 开发者 Ed25519 私钥（base64）

    Returns:
        (signature_b64, manifest_dict)：调用方把签名写回 manifest.json 的 signature 字段。
        注意：签名基于 manifest 内容生成，因此需要先写入 file_hashes，再用
        更新后的 manifest 重新签名。
    """
    import json

    manifest_file = Path(plugin_dir) / _MANIFEST_ENTRY
    data = json.loads(manifest_file.read_text(encoding="utf-8"))
    data["file_hashes"] = compute_file_hashes(plugin_dir)
    signature = sign_manifest_data(data, private_key_b64)
    data["signature"] = signature
    return signature, data


def generate_sign_keypair() -> tuple[str, str]:
    """生成一对 Ed25519 密钥（返回 (private_key_b64, public_key_b64)）。

    用于首次部署时初始化签名体系：
        私钥 → 交给插件开发者本地签名；
        公钥 → 设置到服务器环境变量 PLUGIN_SIGN_PUBLIC_KEY。
    """
    import base64

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    priv = base64.b64encode(key.private_bytes_raw()).decode("ascii")
    pub = base64.b64encode(key.public_key().public_bytes_raw()).decode("ascii")
    return priv, pub


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
