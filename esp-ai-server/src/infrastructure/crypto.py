"""字段级加密 - 对称加密敏感字段

使用 ``cryptography.fernet.Fernet`` 对称加密，对设备密钥、LLM API Key、
ASR/TTS 配置中的 ``api_key``/``secret_key``/``secret_id`` 等敏感字段进行
加密存储。

设计要点：
- 加密密钥从环境变量 ``FIELD_ENCRYPTION_KEY`` 读取（base64 编码的 32 字节密钥）
- 若未配置，启动时自动生成并打印 WARNING（仅开发模式，生产必须配置）
- 加密后的值以 ``enc:`` 前缀标识，便于区分明文/密文（向后兼容已有明文数据）
- ``decrypt`` 遇到非 ``enc:`` 前缀的值时直接返回原值（向后兼容）
- 空字符串不加密，直接返回空
"""
from __future__ import annotations

import os
from typing import Optional

from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


# 加密值前缀，用于区分明文/密文（向后兼容已有明文数据）
_ENCRYPTED_PREFIX = "enc:"

# 模块级 Fernet 实例（由 init_crypto 初始化）
_fernet: Optional["Fernet"] = None  # type: ignore[name-defined]


def _generate_key() -> str:
    """生成一个新的 Fernet 密钥（base64 编码的 32 字节随机密钥）"""
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode("ascii")


def init_crypto(field_encryption_key: str = "") -> None:
    """初始化模块级 Fernet 实例。

    - 若 ``field_encryption_key`` 非空，使用该密钥（base64 编码的 32 字节）
    - 若为空，从环境变量 ``FIELD_ENCRYPTION_KEY`` 读取
    - 若仍未配置，自动生成一个临时密钥并打印 WARNING（仅开发模式）

    Args:
        field_encryption_key: base64 编码的 Fernet 密钥
    """
    global _fernet
    from cryptography.fernet import Fernet

    key = (field_encryption_key or "").strip()
    if not key:
        # 兼容：直接读取环境变量（绕过 Settings，便于早期初始化）
        key = (os.environ.get("FIELD_ENCRYPTION_KEY") or "").strip()

    if not key:
        # 开发模式：自动生成临时密钥
        generated = _generate_key()
        logger.warning(
            "[Crypto] FIELD_ENCRYPTION_KEY 未配置，已自动生成临时密钥（仅开发模式）。"
            "生产环境必须通过环境变量 FIELD_ENCRYPTION_KEY 配置固定的 base64 编码密钥，"
            "否则重启后已加密的敏感字段将无法解密。"
            "请运行 python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\" "
            "生成密钥并配置到环境变量 FIELD_ENCRYPTION_KEY"
        )
        key = generated

    try:
        _fernet = Fernet(key.encode("ascii") if isinstance(key, str) else key)
    except Exception as e:
        logger.error(f"[Crypto] 初始化 Fernet 失败（密钥格式无效）: {e}")
        # 降级：生成临时密钥，避免启动崩溃
        generated = _generate_key()
        logger.warning("[Crypto] 降级使用自动生成的临时密钥")
        _fernet = Fernet(generated.encode("ascii"))


def is_configured() -> bool:
    """判断是否配置了固定的加密密钥（环境变量或显式传入）。

    未配置时使用进程内临时密钥——加密的数据在重启后无法解密，
    调用方（如 wechat_bot）应据此决定是否降级为明文存储。
    """
    if _fernet is not None:
        # 已初始化：无法回溯判断是否外部配置，保守返回 True
        # （调用方应在进程生命周期早期、init 之前做该判断）
        return True
    return bool((os.environ.get("FIELD_ENCRYPTION_KEY") or "").strip())


def _get_fernet() -> "Fernet":  # type: ignore[name-defined]
    """获取已初始化的 Fernet 实例（懒初始化）"""
    global _fernet
    if _fernet is None:
        init_crypto()
    assert _fernet is not None  # noqa: S101 - init_crypto 保证 _fernet 已设置
    return _fernet


def encrypt(plaintext: str) -> str:
    """加密明文字符串。

    - 空字符串不加密，直接返回空（避免无意义的 enc: 前缀）
    - 已加密的值（以 ``enc:`` 开头）不重复加密（幂等）
    - 加密后的值以 ``enc:`` 前缀标识

    Args:
        plaintext: 明文字符串

    Returns:
        加密后的字符串（``enc:<base64 ciphertext>``），或空字符串
    """
    if not plaintext:
        return ""
    # 幂等：已加密的值不重复加密
    if plaintext.startswith(_ENCRYPTED_PREFIX):
        return plaintext
    try:
        fernet = _get_fernet()
        token = fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")
        return f"{_ENCRYPTED_PREFIX}{token}"
    except Exception as e:
        logger.error(f"[Crypto] 加密失败，返回原值（明文）: {e}")
        return plaintext


def decrypt(ciphertext: str) -> str:
    """解密字符串。

    - 空字符串直接返回空
    - 非 ``enc:`` 前缀的值视为明文，直接返回原值（向后兼容已有明文数据）
    - ``enc:`` 前缀的值解密后返回明文

    Args:
        ciphertext: 密文字符串（``enc:<base64 ciphertext>``）或明文字符串

    Returns:
        解密后的明文字符串，或原值（若非 enc: 前缀）
    """
    if not ciphertext:
        return ""
    if not ciphertext.startswith(_ENCRYPTED_PREFIX):
        # 向后兼容：非 enc: 前缀视为明文
        return ciphertext
    try:
        fernet = _get_fernet()
        token = ciphertext[len(_ENCRYPTED_PREFIX):]
        return fernet.decrypt(token.encode("ascii")).decode("utf-8")
    except Exception as e:
        logger.error(f"[Crypto] 解密失败，返回原值: {e}")
        return ciphertext


def is_encrypted(value: str) -> bool:
    """判断值是否已加密（以 ``enc:`` 前缀标识）"""
    return bool(value) and value.startswith(_ENCRYPTED_PREFIX)


__all__ = [
    "init_crypto",
    "encrypt",
    "decrypt",
    "is_encrypted",
]
