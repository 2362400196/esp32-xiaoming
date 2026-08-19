"""
SQLite 数据库自动备份脚本

使用方法：
  # 手动备份
  python -m scripts.backup_db

  # 指定备份目录
  python -m scripts.backup_db --backup-dir /path/to/backups

  # 保留最近 7 天的备份
  python -m scripts.backup_db --keep-days 7

可通过 cron / Windows Task Scheduler 定时执行：
  # 每天凌晨 2 点备份（Linux cron）
  0 2 * * * cd /path/to/esp-ai-server && python -m scripts.backup_db --keep-days 7

特性：
  - 使用 SQLite 在线 backup API 创建一致性快照（不阻塞写入）
  - 备份完成后通过 PRAGMA integrity_check 验证完整性
  - 自动清理超过 --keep-days 的过期备份
  - 打印备份大小和耗时
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# 确保项目根目录在 sys.path 中，便于 `python -m scripts.backup_db` 直接运行
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _resolve_db_path() -> Path:
    """从应用配置解析数据库文件路径，失败时回退到默认 data/espai.db。

    配置项 ``database.sync_url`` 形如 ``sqlite:///data/espai.db``，
    去掉 ``sqlite:///`` 前缀即可得到文件路径。
    """
    try:
        from src.infrastructure.config import get_settings

        sync_url = get_settings().database.sync_url
        if ":///" in sync_url:
            path_str = sync_url.split(":///", 1)[1]
            # 兼容 sqlite:////abs/path 这种四斜杠绝对路径
            return Path(path_str)
    except Exception as e:  # noqa: BLE001
        print(f"[Backup] 解析数据库路径失败，使用默认路径: {e}", file=sys.stderr)

    return PROJECT_ROOT / "data" / "espai.db"


def verify_backup_integrity(backup_path: Path) -> tuple[bool, str]:
    """验证备份完整性（PRAGMA integrity_check）。

    返回 (是否通过, 详细信息)。
    若文件无法作为 SQLite 数据库打开（例如损坏 / 截断），返回 (False, 错误信息)。
    """
    try:
        conn = sqlite3.connect(str(backup_path))
    except sqlite3.Error as e:
        return False, f"connect failed: {e}"
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error as e:
        return False, f"integrity_check failed: {e}"
    finally:
        conn.close()
    result = row[0] if row else "empty"
    return result == "ok", str(result)


def cleanup_old_backups(backup_dir: Path, keep_days: int) -> int:
    """清理过期备份，返回清理数量。"""
    if keep_days <= 0:
        return 0

    cutoff = datetime.now() - timedelta(days=keep_days)
    removed = 0
    for old_backup in backup_dir.glob("espai_backup_*.db"):
        try:
            mtime = datetime.fromtimestamp(old_backup.stat().st_mtime)
        except OSError:
            continue
        if mtime < cutoff:
            try:
                old_backup.unlink()
                print(f"已清理过期备份: {old_backup.name}")
                removed += 1
            except OSError as e:
                print(f"清理失败 {old_backup.name}: {e}", file=sys.stderr)
    return removed


def backup_database(
    db_path: Path,
    backup_dir: Path,
    keep_days: int = 30,
    timestamp: Optional[str] = None,
) -> Path:
    """创建一致性备份。

    参数：
        db_path:     源数据库文件路径
        backup_dir:  备份目录（不存在会自动创建）
        keep_days:   保留最近 N 天的备份，0 表示不清理
        timestamp:   自定义时间戳字符串（主要供测试使用），默认为当前时间

    返回：
        备份文件路径
    """
    if not db_path.exists():
        raise FileNotFoundError(f"数据库文件不存在: {db_path}")

    backup_dir.mkdir(parents=True, exist_ok=True)

    ts = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"espai_backup_{ts}.db"

    start = time.time()

    # 使用 SQLite backup API（在线备份，不阻塞写入）
    source = sqlite3.connect(str(db_path))
    try:
        dest = sqlite3.connect(str(backup_path))
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()

    elapsed = time.time() - start

    # 验证完整性
    ok, detail = verify_backup_integrity(backup_path)
    if not ok:
        try:
            backup_path.unlink()
        except OSError:
            pass
        raise RuntimeError(f"备份完整性检查失败: {detail}")

    # 清理过期备份
    removed = cleanup_old_backups(backup_dir, keep_days)

    size_mb = backup_path.stat().st_size / 1024 / 1024
    print(f"备份完成: {backup_path}")
    print(f"  大小: {size_mb:.2f} MB")
    print(f"  耗时: {elapsed:.2f} 秒")
    print(f"  保留策略: {keep_days} 天" + (f"（已清理 {removed} 个过期备份）" if removed else ""))

    return backup_path


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="ESP AI Server SQLite 数据库自动备份",
    )
    parser.add_argument(
        "--backup-dir",
        default="data/backups",
        help="备份目录（默认: data/backups/），相对路径基于项目根目录",
    )
    parser.add_argument(
        "--keep-days",
        type=int,
        default=30,
        help="保留最近 N 天的备份（默认: 30，设为 0 表示不清理）",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="数据库文件路径（默认: 从配置读取 data/espai.db），相对路径基于项目根目录",
    )
    args = parser.parse_args(argv)

    db_path = Path(args.db_path) if args.db_path else _resolve_db_path()
    backup_dir = Path(args.backup_dir)

    # 相对路径基于项目根目录
    if not backup_dir.is_absolute():
        backup_dir = PROJECT_ROOT / backup_dir
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path

    print(f"[Backup] 数据库路径: {db_path}")
    print(f"[Backup] 备份目录:   {backup_dir}")
    print(f"[Backup] 保留天数:   {args.keep_days}")

    try:
        backup_database(db_path, backup_dir, keep_days=args.keep_days)
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"[Backup] 备份失败: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
