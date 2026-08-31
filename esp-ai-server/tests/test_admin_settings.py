"""
管理员系统设置（网站设置）接口测试

覆盖范围：
- GET  /api/v1/admin/settings：分组返回、密钥掩码（不回明文）、能力元数据
- PUT  /api/v1/admin/settings：类型转换、白名单拒绝、密钥留空保持不变、
  .env 写入（含多行值转义与已有多行值的整块替换）、内存配置热应用
- _update_env_content / _format_env_value：.env 内容操作纯函数
"""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.infrastructure.config import get_settings, reset_settings
from src.infrastructure.routes import admin as admin_routes
from src.infrastructure.routes.admin import (
    SETTING_DEFS,
    _format_env_value,
    _update_env_content,
    router,
)


# ════════════════════════════════════════════════════════════════
# 测试夹具
# ════════════════════════════════════════════════════════════════

@pytest.fixture
def client(tmp_path, monkeypatch):
    """挂载 admin 路由 + 绕过管理员鉴权 + .env 指向临时目录"""
    app = FastAPI()
    app.include_router(router)  # router 自带 /api/v1/admin 前缀

    async def fake_admin():
        user = MagicMock()
        user.email = "admin@test.local"
        return user

    app.dependency_overrides[admin_routes.require_admin] = fake_admin

    # .env 写入隔离到临时目录
    (tmp_path / ".env").write_text("LLM_MODEL=orig-model\nLLM_TEMPERATURE=0.5\n", encoding="utf-8")
    monkeypatch.setattr(admin_routes, "_project_root", lambda: tmp_path)

    # 热应用会写全局 settings 单例，测试后必须恢复
    saved = {}
    settings = get_settings()
    for key in ("llm_model", "llm_temperature", "llm_api_key",
                "llm_system_prompt", "llm_memory_enabled", "music_api_url"):
        saved[key] = getattr(settings, key)
    # 单例加载的是项目真实 .env，先固定初始值让断言稳定
    settings.llm_model = "orig-model"
    settings.llm.model = "orig-model"
    yield TestClient(app), tmp_path, settings
    for key, value in saved.items():
        setattr(settings, key, value)
    settings.model_post_init(None)


# ════════════════════════════════════════════════════════════════
# .env 内容操作纯函数
# ════════════════════════════════════════════════════════════════

class TestFormatEnvValue:
    def test_plain_value(self):
        assert _format_env_value("abc") == "abc"

    def test_empty_value_quoted(self):
        assert _format_env_value("") == '""'

    def test_newline_quoted_and_escaped(self):
        out = _format_env_value("line1\nline2")
        assert out == '"line1\\nline2"'

    def test_quotes_escaped(self):
        out = _format_env_value('say "hi"')
        assert out == '"say \\"hi\\""'


class TestUpdateEnvContent:
    def test_replace_existing(self):
        content = "A=1\nLLM_MODEL=old\nB=2\n"
        out = _update_env_content(content, "LLM_MODEL", "new")
        assert "LLM_MODEL=new" in out
        assert "old" not in out
        assert "A=1" in out and "B=2" in out

    def test_append_missing(self):
        out = _update_env_content("A=1\n", "NEW_KEY", "v")
        assert out.endswith("NEW_KEY=v")

    def test_replace_multiline_quoted_value_whole_block(self):
        content = 'A=1\nLLM_SYSTEM_PROMPT="line1\\nline2"\nB=2\n'
        out = _update_env_content(content, "LLM_SYSTEM_PROMPT", "new")
        assert "LLM_SYSTEM_PROMPT=new" in out
        assert "line2" not in out.replace("LLM_SYSTEM_PROMPT=new", "")
        assert "\nB=2" in out  # 后续行未被吞掉

    def test_key_prefix_not_confused(self):
        content = "LLM_MODEL_X=1\nLLM_MODEL=old\n"
        out = _update_env_content(content, "LLM_MODEL", "new")
        assert "LLM_MODEL_X=1" in out
        assert "LLM_MODEL=new" in out


# ════════════════════════════════════════════════════════════════
# GET /settings
# ════════════════════════════════════════════════════════════════

class TestGetSettings:
    def test_returns_groups_with_items(self, client):
        tc, _tmp, _settings = client
        res = tc.get("/api/v1/admin/settings")
        assert res.status_code == 200
        data = res.json()["data"]
        group_ids = [g["id"] for g in data["groups"]]
        assert "basic" in group_ids and "llm" in group_ids
        # 所有定义项都归属到某个分组
        total = sum(len(g["items"]) for g in data["groups"])
        assert total == len(SETTING_DEFS)

    def test_secret_masked_with_has_value(self, client):
        tc, _tmp, settings = client
        settings.llm_api_key = "super-secret"
        res = tc.get("/api/v1/admin/settings")
        llm = next(g for g in res.json()["data"]["groups"] if g["id"] == "llm")
        key_item = next(i for i in llm["items"] if i["key"] == "LLM_API_KEY")
        assert key_item["value"] == ""          # 不回明文
        assert key_item["has_value"] is True    # 只回是否已设置

    def test_normal_fields_expose_value(self, client):
        tc, _tmp, _settings = client
        res = tc.get("/api/v1/admin/settings")
        llm = next(g for g in res.json()["data"]["groups"] if g["id"] == "llm")
        model_item = next(i for i in llm["items"] if i["key"] == "LLM_MODEL")
        assert model_item["value"] == "orig-model"


# ════════════════════════════════════════════════════════════════
# PUT /settings
# ════════════════════════════════════════════════════════════════

class TestUpdateSettings:
    def test_update_writes_env_and_hot_applies(self, client):
        tc, tmp, settings = client
        res = tc.put("/api/v1/admin/settings", json={"LLM_MODEL": "new-model"})
        assert res.status_code == 200
        body = res.json()
        assert body["data"]["updated"] == 1
        # .env 已写入
        env = (tmp / ".env").read_text(encoding="utf-8")
        assert "LLM_MODEL=new-model" in env
        assert "LLM_TEMPERATURE=0.5" in env  # 未改动的键保留
        # 内存配置已热应用
        assert settings.llm.model == "new-model"
        assert settings.llm_model == "new-model"

    def test_float_and_bool_conversion(self, client):
        tc, tmp, settings = client
        res = tc.put("/api/v1/admin/settings", json={
            "LLM_TEMPERATURE": "0.9",
            "LLM_MEMORY_ENABLED": False,
        })
        assert res.status_code == 200
        env = (tmp / ".env").read_text(encoding="utf-8")
        assert "LLM_TEMPERATURE=0.9" in env
        assert "LLM_MEMORY_ENABLED=false" in env
        assert settings.llm.temperature == 0.9
        assert settings.llm.memory_enabled is False

    def test_multiline_prompt_written_quoted(self, client):
        tc, tmp, settings = client
        res = tc.put("/api/v1/admin/settings", json={
            "LLM_SYSTEM_PROMPT": "第一行\n第二行",
        })
        assert res.status_code == 200
        env = (tmp / ".env").read_text(encoding="utf-8")
        assert 'LLM_SYSTEM_PROMPT="第一行\\n第二行"' in env
        # 热应用后提示词带换行（python-dotenv 同样解析为换行）
        assert settings.llm.system_prompt == "第一行\n第二行"

    def test_secret_empty_keeps_existing(self, client):
        tc, tmp, settings = client
        res = tc.put("/api/v1/admin/settings", json={"LLM_API_KEY": ""})
        assert res.status_code == 200
        assert res.json()["data"]["updated"] == 0  # 留空 = 保持不变，无修改
        assert "LLM_API_KEY" not in (tmp / ".env").read_text(encoding="utf-8")

    def test_secret_value_saved(self, client):
        tc, tmp, settings = client
        res = tc.put("/api/v1/admin/settings", json={"LLM_API_KEY": "sk-test-123"})
        assert res.status_code == 200
        env = (tmp / ".env").read_text(encoding="utf-8")
        assert "LLM_API_KEY=sk-test-123" in env
        assert settings.llm.api_key == "sk-test-123"

    def test_unknown_key_rejected(self, client):
        tc, _tmp, _settings = client
        res = tc.put("/api/v1/admin/settings", json={"HACKED_KEY": "x"})
        assert res.status_code == 400

    def test_invalid_int_rejected(self, client):
        tc, _tmp, _settings = client
        res = tc.put("/api/v1/admin/settings", json={"LLM_MAX_TOKENS": "abc"})
        assert res.status_code == 400

    def test_invalid_select_rejected(self, client):
        tc, _tmp, _settings = client
        res = tc.put("/api/v1/admin/settings", json={"DEPLOY_MODE": "cluster"})
        assert res.status_code == 400

    def test_restart_keys_reported(self, client):
        tc, _tmp, _settings = client
        res = tc.put("/api/v1/admin/settings", json={
            "LLM_MODEL": "m2",          # restart=True
            "WAKEUP_TEXT": "你好呀",     # restart=False
        })
        assert res.status_code == 200
        restart_keys = res.json()["data"]["restart_keys"]
        assert "LLM_MODEL" in restart_keys
        assert "WAKEUP_TEXT" not in restart_keys

    def test_empty_body_rejected(self, client):
        tc, _tmp, _settings = client
        res = tc.put("/api/v1/admin/settings", json={})
        assert res.status_code == 400
