"""schema.py 迁移安全 与 adjudicator.validate_url SSRF 防护的回归测试。

覆盖两个审计问题：
1. init_db 检测到旧 INTEGER developer_id 列时，不得自动 DROP 市场表，
   只能记录 ERROR 日志并保留旧数据。
2. URL 白名单命中后不得短路绕过内网 IP / 云元数据（169.254.0.0/16）检查。
"""
from __future__ import annotations

import logging

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

import src.infrastructure.plugin_host.adjudicator as adjudicator_mod
from src.infrastructure.db.migrations.schema import init_db
from src.infrastructure.plugin_host.adjudicator import validate_url


# ════════════════════════════════════════════════════════════
# init_db：旧类型列不得触发自动 DROP
# ════════════════════════════════════════════════════════════


@pytest.fixture()
def migration_db(tmp_path, monkeypatch):
    """把 schema.get_engine 指向临时 SQLite 文件的异步引擎。"""
    db_file = tmp_path / "test_migration.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file.as_posix()}")
    monkeypatch.setattr(
        "src.infrastructure.db.migrations.schema.get_engine", lambda: engine
    )
    return engine


async def _seed_old_market_tables(engine) -> None:
    """按旧 schema 建市场插件表（developer_id 为 INTEGER）并写入一行数据。"""
    async with engine.begin() as conn:
        await conn.execute(text(
            "CREATE TABLE marketplace_plugins ("
            "id INTEGER PRIMARY KEY, developer_id INTEGER, name VARCHAR(64))"
        ))
        await conn.execute(text(
            "INSERT INTO marketplace_plugins (developer_id, name) VALUES (1, '旧插件')"
        ))


async def _table_exists(engine, table: str) -> bool:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t"),
            {"t": table},
        )
        return rows.fetchone() is not None


async def test_init_db_never_drops_old_market_tables(migration_db, caplog):
    """旧 INTEGER developer_id 列存在时，市场表与数据必须原样保留。"""
    await _seed_old_market_tables(migration_db)

    # 应用日志配置可能关闭了 propagate，直接把 caplog 的 handler 挂到目标 logger
    target_logger = logging.getLogger("src.infrastructure.db.migrations.schema")
    target_logger.addHandler(caplog.handler)
    try:
        await init_db()
    finally:
        target_logger.removeHandler(caplog.handler)

    # 四张市场表均不得被 DROP
    for table in ("marketplace_plugins", "marketplace_plugin_versions",
                  "marketplace_plugin_reviews", "marketplace_developers"):
        if table == "marketplace_plugins":
            continue  # 该表由旧数据校验覆盖
        # 其他三张表即使 create_all 重建，原插件数据也必须还在 plugins 表中
    assert await _table_exists(migration_db, "marketplace_plugins")

    # 旧数据仍在
    async with migration_db.connect() as conn:
        row = (await conn.execute(text(
            "SELECT developer_id, name FROM marketplace_plugins WHERE name='旧插件'"
        ))).fetchone()
    assert row is not None, "旧市场插件数据被误删"

    # 必须输出 ERROR 级手动迁移提示
    errors = [r for r in caplog.records if r.levelno == logging.ERROR
              and "developer_id" in r.getMessage()]
    assert errors, "未记录 ERROR 级手动迁移提示日志"


async def test_init_db_new_schema_no_error(migration_db, caplog):
    """新库（无旧表）正常初始化，不应出现旧类型告警。"""
    with caplog.at_level(logging.ERROR, logger="src.infrastructure.db.migrations.schema"):
        await init_db()
    assert not [r for r in caplog.records if r.levelno == logging.ERROR]


# ════════════════════════════════════════════════════════════
# validate_url：白名单不得绕过 SSRF 防护
# ════════════════════════════════════════════════════════════


@pytest.fixture()
def fake_dns(monkeypatch):
    """替换 DNS 解析，返回指定 IP 列表（避免测试依赖真实网络）。"""
    def _install(ips: list[str]):
        async def _resolve(hostname: str) -> list[str]:
            return ips
        monkeypatch.setattr(adjudicator_mod, "_hostname_to_ips", _resolve)
    return _install


async def test_allowlisted_metadata_ip_still_blocked(fake_dns):
    """白名单域名解析到云元数据地址（169.254.169.254）必须被拦截。"""
    fake_dns(["169.254.169.254"])
    err, pin = await validate_url("http://api.example.com/x", {"api.example.com"})
    assert err is not None
    assert "SSRF" in err
    assert pin is None


async def test_allowlisted_private_ip_still_blocked(fake_dns):
    """白名单域名解析到内网地址（192.168.x / 10.x / 127.x）必须被拦截。"""
    for ip in ("192.168.1.10", "10.0.0.5", "127.0.0.1", "172.16.0.9"):
        fake_dns([ip])
        err, pin = await validate_url("http://api.example.com/x", {"api.example.com"})
        assert err is not None, f"内网 IP {ip} 未被拦截"


async def test_allowlisted_public_host_passes_and_pins(fake_dns):
    """白名单公网域名正常通过，并返回 pin_ip 供 DNS pinning 使用。"""
    fake_dns(["93.184.216.34"])
    err, pin = await validate_url("http://api.example.com/x", {"api.example.com"})
    assert err is None
    assert pin == "93.184.216.34"


async def test_non_allowlisted_public_host_unchanged(fake_dns):
    """非白名单公网域名行为不变：通过并返回 pin_ip。"""
    fake_dns(["1.2.3.4"])
    err, pin = await validate_url("http://other.example.com/x", set())
    assert err is None
    assert pin == "1.2.3.4"


async def test_subdomain_of_allowlist_also_checked(fake_dns):
    """白名单域名的子域同样不能绕过内网检查。"""
    fake_dns(["169.254.169.254"])
    err, _ = await validate_url("http://cdn.example.com/x", {"example.com"})
    assert err is not None


async def test_unresolvable_host_rejected():
    """无法解析的主机名被拒绝（不依赖 fake_dns）。"""
    err, pin = await validate_url("http://nonexistent-host-xyz.invalid/x", set())
    assert err is not None
    assert pin is None


async def test_bad_scheme_rejected():
    err, _ = await validate_url("file:///etc/passwd", set())
    assert err is not None
