"""scripts/backup_db.py 单元测试

覆盖：
- _resolve_db_path（从配置解析 / 回退默认路径）
- verify_backup_integrity（完整性校验）
- cleanup_old_backups（按 keep_days 清理过期备份）
- backup_database（端到端备份 + 完整性验证 + 清理）
- main CLI（参数解析 + 退出码）
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backup_db import (  # noqa: E402
    _resolve_db_path,
    backup_database,
    cleanup_old_backups,
    main,
    verify_backup_integrity,
)


# ============================================================
# 测试夹具
# ============================================================

@pytest.fixture
def sample_db(tmp_path: Path) -> Path:
    """创建一个带数据的测试用 SQLite 数据库"""
    db_path = tmp_path / "sample.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE devices (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO devices (name) VALUES ('dev1'), ('dev2')")
        conn.commit()
    finally:
        conn.close()
    return db_path


# ============================================================
# _resolve_db_path 测试
# ============================================================

class TestResolveDbPath:
    def test_resolve_from_settings(self, tmp_path: Path):
        """能从配置的 sync_url 中解析数据库路径"""
        fake_settings = type("S", (), {})()
        fake_settings.database = type("D", (), {})()
        fake_settings.database.sync_url = f"sqlite:///{tmp_path / 'custom.db'}"
        with patch("src.infrastructure.config.get_settings", return_value=fake_settings):
            path = _resolve_db_path()
        assert path == tmp_path / "custom.db"

    def test_resolve_fallback_on_exception(self):
        """配置读取异常时回退到默认 data/espai.db"""
        with patch(
            "src.infrastructure.config.get_settings",
            side_effect=RuntimeError("no config"),
        ):
            path = _resolve_db_path()
        # 回退到 PROJECT_ROOT / data / espai.db
        assert path.name == "espai.db"
        assert path.parent.name == "data"


# ============================================================
# verify_backup_integrity 测试
# ============================================================

class TestVerifyBackupIntegrity:
    def test_valid_db(self, sample_db: Path):
        ok, detail = verify_backup_integrity(sample_db)
        assert ok is True
        assert detail == "ok"

    def test_corrupt_db(self, tmp_path: Path):
        """损坏的 DB 文件完整性检查失败"""
        bad = tmp_path / "corrupt.db"
        bad.write_bytes(b"not a sqlite database")
        ok, detail = verify_backup_integrity(bad)
        assert ok is False
        assert detail != "ok"


# ============================================================
# cleanup_old_backups 测试
# ============================================================

class TestCleanupOldBackups:
    def test_removes_old_backups(self, tmp_path: Path):
        """超过 keep_days 的备份应被清理"""
        old_file = tmp_path / "espai_backup_20200101_000000.db"
        old_file.write_bytes(b"old")
        new_file = tmp_path / "espai_backup_20990101_000000.db"
        new_file.write_bytes(b"new")

        # 把 old_file 的 mtime 改到 10 天前
        old_ts = time.time() - 10 * 86400
        os.utime(old_file, (old_ts, old_ts))

        removed = cleanup_old_backups(tmp_path, keep_days=7)
        assert removed == 1
        assert not old_file.exists()
        assert new_file.exists()

    def test_keep_days_zero_skips_cleanup(self, tmp_path: Path):
        """keep_days=0 表示不清理"""
        old_file = tmp_path / "espai_backup_20200101_000000.db"
        old_file.write_bytes(b"old")
        old_ts = time.time() - 365 * 86400
        os.utime(old_file, (old_ts, old_ts))
        removed = cleanup_old_backups(tmp_path, keep_days=0)
        assert removed == 0
        assert old_file.exists()

    def test_ignores_non_matching_files(self, tmp_path: Path):
        """非 espai_backup_*.db 命名的文件不应被清理"""
        other = tmp_path / "other_20200101_000000.db"
        other.write_bytes(b"x")
        old_ts = time.time() - 30 * 86400
        os.utime(other, (old_ts, old_ts))
        removed = cleanup_old_backups(tmp_path, keep_days=7)
        assert removed == 0
        assert other.exists()

    def test_no_backups(self, tmp_path: Path):
        """目录为空时返回 0"""
        assert cleanup_old_backups(tmp_path, keep_days=7) == 0


# ============================================================
# backup_database 端到端测试
# ============================================================

class TestBackupDatabase:
    def test_creates_valid_backup(self, sample_db: Path, tmp_path: Path):
        """备份文件存在、完整性校验通过、内容与源库一致"""
        backup_dir = tmp_path / "backups"
        backup_path = backup_database(
            sample_db, backup_dir, keep_days=30, timestamp="20260718_120000"
        )
        assert backup_path.exists()
        assert backup_path.name == "espai_backup_20260718_120000.db"

        # 完整性校验
        ok, _ = verify_backup_integrity(backup_path)
        assert ok is True

        # 数据一致
        conn = sqlite3.connect(str(backup_path))
        try:
            rows = conn.execute("SELECT name FROM devices ORDER BY id").fetchall()
        finally:
            conn.close()
        assert [r[0] for r in rows] == ["dev1", "dev2"]

    def test_creates_backup_dir_if_missing(self, sample_db: Path, tmp_path: Path):
        """备份目录不存在时应自动创建"""
        backup_dir = tmp_path / "nested" / "backups"
        assert not backup_dir.exists()
        backup_database(sample_db, backup_dir, keep_days=30, timestamp="20260718_120000")
        assert backup_dir.exists()

    def test_missing_db_raises(self, tmp_path: Path):
        """源数据库不存在时应抛 FileNotFoundError"""
        with pytest.raises(FileNotFoundError):
            backup_database(
                tmp_path / "no_such.db", tmp_path / "backups",
                keep_days=30, timestamp="20260718_120000",
            )

    def test_cleanup_invoked_after_backup(self, sample_db: Path, tmp_path: Path):
        """备份完成后应触发过期清理"""
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        # 预置一个 10 天前的过期备份
        old_file = backup_dir / "espai_backup_20200101_000000.db"
        old_file.write_bytes(b"old")
        old_ts = time.time() - 10 * 86400
        os.utime(old_file, (old_ts, old_ts))

        backup_database(sample_db, backup_dir, keep_days=7, timestamp="20260718_120000")
        assert not old_file.exists()


# ============================================================
# main CLI 测试
# ============================================================

class TestMainCli:
    def test_main_success(self, sample_db: Path, tmp_path: Path, capsys):
        """正常备份应返回 0"""
        rc = main([
            "--db-path", str(sample_db),
            "--backup-dir", str(tmp_path / "backups"),
            "--keep-days", "7",
        ])
        assert rc == 0
        out = capsys.readouterr().out
        assert "备份完成" in out

    def test_main_missing_db_returns_1(self, tmp_path: Path, capsys):
        """源 DB 不存在时返回 1 并打印错误"""
        rc = main([
            "--db-path", str(tmp_path / "no_such.db"),
            "--backup-dir", str(tmp_path / "backups"),
            "--keep-days", "7",
        ])
        assert rc == 1
        err = capsys.readouterr().err
        assert "备份失败" in err
