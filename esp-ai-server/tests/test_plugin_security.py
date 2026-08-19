"""插件安全模块测试（静态审计 / 运行时守卫 / 脱敏 / 签名）。

验证：
- 静态审计（AST）：正确提取真实使用的危险能力集合，SDK 通道豁免
- check_permissions：未声明的能力被拦截
- 运行时守卫：contextvars 权限上下文按 manifest.permissions 二次拦截
- 脱敏：密钥类配置输出掩码，避免日志泄露
- Ed25519 签名：签名→验证闭环，错误密钥/篡改包被拒绝
- plugin_loader 工具名提取：@tool 装饰器 AST 解析
"""
from __future__ import annotations

import base64

import pytest

from src.infrastructure.plugin_manifest import (
    PluginManifest,
    generate_sign_keypair,
    sign_manifest_data,
)
from src.infrastructure.plugin_security import (
    audit_plugin_source,
    check_permissions,
    current_plugin,
    is_secret_key,
    mask_dict_secrets,
    mask_secret,
    require_permission,
    reset_plugin_context,
    set_plugin_context,
)

# ════════════════════════════════════════════════════════════
# 1. 静态审计（AST）
# ════════════════════════════════════════════════════════════

class TestAuditPluginSource:
    def test_http_requests_require_network(self):
        used = audit_plugin_source(
            "import httpx\n"
            "async def f():\n"
            "    async with httpx.AsyncClient() as c:\n"
            "        r = await c.get('https://example.com')\n"
        )
        assert "network" in used

    def test_socket_requires_network(self):
        used = audit_plugin_source(
            "import socket\n"
            "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        )
        assert "network" in used

    def test_subprocess_requires_subprocess(self):
        used = audit_plugin_source("import subprocess\nsubprocess.run(['ls'])\n")
        assert "subprocess" in used
        used2 = audit_plugin_source("import os\nos.system('rm -rf /')\n")
        assert "subprocess" in used2

    def test_dynamic_exec_requires_exec(self):
        used = audit_plugin_source("eval('1+1')\nexec('x=1')\ncompile('y=2', '', 'exec')\n")
        assert {"exec"} <= used

    def test_open_read_only_requires_file_read(self):
        used = audit_plugin_source("with open('a.txt', 'r') as f:\n    f.read()\n")
        assert used == {"file_read"}

    def test_open_write_requires_file_write(self):
        used = audit_plugin_source("with open('a.txt', 'w') as f:\n    f.write('x')\n")
        assert {"file_read", "file_write"} <= used

    def test_path_read_write_methods(self):
        used = audit_plugin_source(
            "from pathlib import Path\n"
            "p = Path('a.txt')\n"
            "p.write_text('x')\n"
        )
        assert "file_write" in used

    def test_env_read(self):
        used = audit_plugin_source("import os\nk = os.environ.get('HOME')\n")
        assert "env_read" in used
        used2 = audit_plugin_source("import os\nk = os.getenv('HOME')\n")
        assert "env_read" in used2

    def test_db_requires_db(self):
        used = audit_plugin_source("import sqlite3\nconn = sqlite3.connect('x.db')\n")
        assert "db" in used

    def test_sdk_functions_are_exempt_from_static_audit(self):
        # SDK 通道由运行时守卫拦截，静态审计不应重复标记
        used = audit_plugin_source(
            "from src.use_cases._plugin_helpers import send_device_command, http_request, get_ltm_service\n"
            "await send_device_command(tool_manager, 'set_volume')\n"
            "await http_request('GET', 'https://example.com')\n"
            "svc = get_ltm_service(tool_manager)\n"
        )
        assert not used

    def test_syntax_error_returns_empty(self):
        used = audit_plugin_source("def broken(:\n")
        assert used == set()


class TestCheckPermissions:
    def test_declared_permissions_pass(self, tmp_path):
        (tmp_path / "plugin.py").write_text(
            "import httpx\n"
            "async def f():\n"
            "    async with httpx.AsyncClient() as c:\n"
            "        await c.get('https://x.com')\n",
            encoding="utf-8",
        )
        ok, undeclared = check_permissions(tmp_path, ["network"])
        assert ok is True
        assert undeclared == []

    def test_undeclared_permissions_are_rejected(self, tmp_path):
        (tmp_path / "plugin.py").write_text(
            "import httpx\n"
            "import sqlite3\n"
            "conn = sqlite3.connect('x.db')\n",
            encoding="utf-8",
        )
        ok, undeclared = check_permissions(tmp_path, ["network"])
        assert ok is False
        assert "db" in undeclared


# ════════════════════════════════════════════════════════════
# 2. 运行时守卫（contextvars）
# ════════════════════════════════════════════════════════════

class TestRuntimeGuard:
    def test_no_context_always_passes(self):
        require_permission("network", "测试")

    def test_declared_permission_passes(self):
        token = set_plugin_context("demo", ["network", "device"])
        try:
            require_permission("network")
        finally:
            reset_plugin_context(token)
        assert current_plugin() is None

    def test_undeclared_permission_raises(self):
        token = set_plugin_context("demo", ["network"])
        try:
            with pytest.raises(PermissionError) as ei:
                require_permission("ltm", "访问长期记忆")
            assert "demo" in str(ei.value)
            assert "ltm" in str(ei.value)
        finally:
            reset_plugin_context(token)

    def test_current_plugin_returns_context(self):
        token = set_plugin_context("demo", ["device"])
        try:
            ctx = current_plugin()
            assert ctx is not None
            assert ctx.plugin == "demo"
            assert "device" in ctx.permissions
        finally:
            reset_plugin_context(token)


# ════════════════════════════════════════════════════════════
# 3. 脱敏
# ════════════════════════════════════════════════════════════

class TestMasking:
    def test_is_secret_key_suffixes(self):
        assert is_secret_key("api_key")
        assert is_secret_key("OPENAI_API_TOKEN")
        assert is_secret_key("password")
        assert not is_secret_key("city")
        assert not is_secret_key("wifi_name")

    def test_mask_secret_keeps_tail(self):
        assert mask_secret("sk-abc123456") == "*" * 8 + "3456"
        assert mask_secret("abc") == "***"
        assert mask_secret("") == ""

    def test_mask_dict_secrets(self):
        data = {"api_key": "sk-123456789", "city": "北京", "wifi_password": "secretpw"}
        masked = mask_dict_secrets(data)
        assert masked["api_key"] != "sk-123456789"
        assert masked["city"] == "北京"
        assert masked["wifi_password"].startswith("*")


# ════════════════════════════════════════════════════════════
# 4. Ed25519 签名
# ════════════════════════════════════════════════════════════

def _make_manifest_data(**overrides) -> dict:
    data = {
        "id": "demo",
        "name": "Demo Plugin",
        "version": "1.0.0",
        "author": "tester",
        "description": "test",
        "api_version": "1.0",
        "requires": [],
        "dependencies": [],
        "config_fields": [],
        "permissions": ["network"],
    }
    data.update(overrides)
    return data


def _make_manifest(**overrides) -> PluginManifest:
    return PluginManifest.model_validate(_make_manifest_data(**overrides))


class TestSignature:
    def test_sign_verify_roundtrip(self):
        priv, pub = generate_sign_keypair()
        data = _make_manifest_data()
        sig = sign_manifest_data(data, priv)
        manifest = _make_manifest(signature=sig)
        assert manifest.verify_signature(pub) is True

    def test_verify_with_wrong_key_fails(self):
        priv, _ = generate_sign_keypair()
        _, other_pub = generate_sign_keypair()
        sig = sign_manifest_data(_make_manifest_data(), priv)
        manifest = _make_manifest(signature=sig)
        assert manifest.verify_signature(other_pub) is False

    def test_tampered_manifest_fails(self):
        priv, pub = generate_sign_keypair()
        sig = sign_manifest_data(_make_manifest_data(), priv)
        tampered = _make_manifest_data(permissions=["network", "device"])
        tampered["signature"] = sig
        manifest = PluginManifest.model_validate(tampered)
        assert manifest.verify_signature(pub) is False

    def test_garbage_signature_fails(self):
        priv, pub = generate_sign_keypair()
        manifest = _make_manifest(signature=base64.b64encode(b"garbage").decode())
        assert manifest.verify_signature(pub) is False

    def test_unsigned_manifest_without_key_passes(self, monkeypatch):
        monkeypatch.delenv("PLUGIN_SIGN_PUBLIC_KEY", raising=False)
        assert _make_manifest().verify_signature() is True

    def test_unsigned_manifest_with_configured_key_fails(self, monkeypatch):
        _, pub = generate_sign_keypair()
        monkeypatch.setenv("PLUGIN_SIGN_PUBLIC_KEY", pub)
        assert _make_manifest().verify_signature() is False

    def test_signed_manifest_without_configured_key_passes(self, monkeypatch):
        monkeypatch.delenv("PLUGIN_SIGN_PUBLIC_KEY", raising=False)
        priv, _ = generate_sign_keypair()
        sig = sign_manifest_data(_make_manifest_data(), priv)
        assert _make_manifest(signature=sig).verify_signature() is True

    def test_signature_payload_is_stable(self):
        a = _make_manifest()
        b = _make_manifest()
        assert a.signature_payload() == b.signature_payload()


# ════════════════════════════════════════════════════════════
# 5. plugin_loader：AST 工具名提取
# ════════════════════════════════════════════════════════════

class TestExtractToolNames:
    def test_plain_tool_decorator(self):
        import tempfile
        from pathlib import Path

        from src.infrastructure.plugin_loader import _extract_tool_names

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "plugin.py"
            p.write_text(
                "from src.use_cases.tools_system import tool\n"
                "\n"
                "@tool()\n"
                "def hello():\n"
                "    return 'hi'\n",
                encoding="utf-8",
            )
            assert _extract_tool_names(p) == ["hello"]

    def test_named_tool_decorator(self):
        import tempfile
        from pathlib import Path

        from src.infrastructure.plugin_loader import _extract_tool_names

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "plugin.py"
            p.write_text(
                "from src.use_cases import tools_system\n"
                "\n"
                "@tools_system.tool(name='weather_forecast')\n"
                "def _impl():\n"
                "    return 1\n",
                encoding="utf-8",
            )
            assert _extract_tool_names(p) == ["weather_forecast"]

    def test_non_tool_decorators_ignored(self):
        import tempfile
        from pathlib import Path

        from src.infrastructure.plugin_loader import _extract_tool_names

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "plugin.py"
            p.write_text(
                "@some_decorator\n"
                "def not_a_tool():\n"
                "    return 0\n",
                encoding="utf-8",
            )
            assert _extract_tool_names(p) == []
