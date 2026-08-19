"""JSON → SQLite 数据迁移脚本（阶段 4）

将以下 JSON 数据源迁移到 SQLite 数据库：
- ``users.json`` → ``devices`` 表
- ``data/memories/{id}.json`` → ``short_term_memories`` 表
- ``data/memories/{id}/records.jsonl`` → ``long_term_memory_records`` 表（合并后取最新状态）
- ``data/devices/{id}/profile/user_profile.json`` → ``user_profiles`` 表
- ``data/devices/{id}/profile/emotion_history.json`` → ``emotion_history`` 表
- ``data/devices/{id}/growth/learning_log.json`` → ``learning_logs`` 表
- ``emos/packs/*/meta.json`` → ``emo_packs`` 表
- ``SKILL.md`` → ``skills`` 表（扫描 ``src/skills/`` 和 ``data/devices/*/skills/``）

特性：
- 幂等：每张表迁移前检查是否已有数据，有则跳过（除非 ``--force``）
- UPSERT：使用仓储类的 upsert 方法
- 报告：迁移完成后输出各表行数、耗时、警告
- CLI：支持 ``--dry-run`` 和 ``--force``

命令行入口：
    python -m src.infrastructure.db.migrations.data_migration
    python -m src.infrastructure.db.migrations.data_migration --dry-run
    python -m src.infrastructure.db.migrations.data_migration --force
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from src.domain.entities import MemoryItem
from src.infrastructure.db.engine import dispose_engine
from src.infrastructure.db.migrations.schema import init_db
from src.infrastructure.db.models.device import DeviceModel
from src.infrastructure.db.models.emo import EmoPackModel
from src.infrastructure.db.models.growth import (
    EmotionHistoryModel,
    LearningLogModel,
    UserProfileModel,
)
from src.infrastructure.db.models.memory import (
    LongTermMemoryRecordModel,
    ShortTermMemoryModel,
)
from src.infrastructure.db.models.skill import SkillModel
from src.infrastructure.db.repositories.device_repository import DeviceRepository
from src.infrastructure.db.repositories.emo_repository import EmoPackRepository
from src.infrastructure.db.repositories.growth_repositories import (
    EmotionHistoryRepository,
    LearningLogRepository,
    UserProfileRepository,
)
from src.infrastructure.db.repositories.ltm_repository import SqlLongTermMemoryRepository
from src.infrastructure.db.repositories.short_term_memory_repo import (
    SqlShortTermMemoryRepository,
)
from src.infrastructure.db.repositories.skill_repository import (
    SkillRepository,
    _frontmatter_to_fields,
    _parse_skill_md,
)
from src.infrastructure.db.session import get_session_ctx
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)

# 默认项目根目录：src/infrastructure/db/migrations/ → 项目根
_DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[4]


# ============================================================
# 迁移报告
# ============================================================


@dataclass
class MigrationReport:
    """单张表的迁移报告"""

    table: str
    rows_before: int = 0
    rows_after: int = 0
    inserted: int = 0  # 新增/更新的记录数
    skipped: bool = False
    skip_reason: str = ""
    elapsed_seconds: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "table": self.table,
            "rows_before": self.rows_before,
            "rows_after": self.rows_after,
            "inserted": self.inserted,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "warnings": self.warnings,
        }


# ============================================================
# 迁移上下文
# ============================================================


@dataclass
class MigrationContext:
    """迁移上下文：封装所有数据源路径

    路径布局（与项目结构一致）：
        {project_root}/
            users.json
            src/
                data/
                    memories/
                        {id}.json          ← 短期记忆
                        {id}/records.jsonl ← 长期记忆
                    devices/
                        {id}/
                            profile/
                                user_profile.json
                                emotion_history.json
                            growth/
                                learning_log.json
                            skills/
                                {skill_id}/SKILL.md
                emos/
                    packs/
                        {pack}/meta.json
                skills/
                    {skill_id}/SKILL.md
    """

    project_root: Path
    users_json_path: Path
    data_dir: Path
    memories_dir: Path
    devices_dir: Path
    emos_packs_dir: Path
    skills_root_dir: Path

    @classmethod
    def from_root(cls, project_root: Path) -> "MigrationContext":
        """从项目根目录构造迁移上下文"""
        root = Path(project_root).resolve()
        return cls(
            project_root=root,
            users_json_path=root / "users.json",
            data_dir=root / "src" / "data",
            memories_dir=root / "src" / "data" / "memories",
            devices_dir=root / "src" / "data" / "devices",
            emos_packs_dir=root / "src" / "emos" / "packs",
            skills_root_dir=root / "src" / "skills",
        )


# ============================================================
# 辅助函数
# ============================================================


async def _count_rows(model_cls) -> int:
    """查询表行数"""
    async with get_session_ctx() as session:
        result = await session.execute(select(func.count()).select_from(model_cls))
        return int(result.scalar_one() or 0)


def _load_json(path: Path) -> Optional[dict]:
    """加载 JSON 文件，失败返回 None"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.debug(f"JSON 解析失败 {path}: {e}")
        return None


def _load_jsonl_records(path: Path) -> list[dict]:
    """加载 JSONL 文件，按 memory_id 合并取最新状态

    合并逻辑与 ``JsonLongTermMemoryRepository._load_records`` 一致：
    同一 memory_id 的多条记录，取最后一条（文件追加顺序 = 时间顺序）。
    """
    merged: dict[str, dict] = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                mid = rec.get("memory_id", "")
                if mid:
                    merged[mid] = rec
    except IOError:
        pass
    return list(merged.values())


def _build_key_to_mac_mapping(users_json_path: Path) -> dict[str, str]:
    """从 users.json 建立 device_key → mac 映射

    用于将设备目录名（通常是 device_key）解析为 MAC 地址。
    文件不存在或解析失败时返回空 dict（回退到用目录名作为 device_id）。
    """
    mapping: dict[str, str] = {}
    data = _load_json(users_json_path)
    if not data:
        return mapping
    for mac, cfg in (data.get("devices") or {}).items():
        key = cfg.get("key", "") if isinstance(cfg, dict) else ""
        if key:
            mapping[key] = mac
    return mapping


# ============================================================
# 迁移各表
# ============================================================


async def _migrate_devices(
    ctx: MigrationContext, dry_run: bool, force: bool, report: MigrationReport
) -> None:
    """迁移 users.json → devices 表

    读取 users.json，遍历 devices 字典，逐条 UPSERT。
    """
    start = time.time()
    if not ctx.users_json_path.is_file():
        report.warnings.append(f"users.json 不存在: {ctx.users_json_path}")
        report.elapsed_seconds = time.time() - start
        return

    data = _load_json(ctx.users_json_path)
    if data is None:
        report.warnings.append(f"users.json 解析失败: {ctx.users_json_path}")
        report.elapsed_seconds = time.time() - start
        return

    devices = data.get("devices", {}) or {}
    if not devices:
        report.warnings.append("users.json 中无 devices 数据")
        report.elapsed_seconds = time.time() - start
        return

    if dry_run:
        report.inserted = len(devices)
        report.elapsed_seconds = time.time() - start
        return

    repo = DeviceRepository()
    for device_id, config in devices.items():
        if not isinstance(config, dict):
            report.warnings.append(f"设备 {device_id} 配置非 dict，跳过")
            continue
        await repo.upsert_device(device_id, config)
        report.inserted += 1
    report.elapsed_seconds = time.time() - start


async def _migrate_short_term_memories(
    ctx: MigrationContext, dry_run: bool, force: bool, report: MigrationReport
) -> None:
    """迁移 memories/{id}.json → short_term_memories 表

    遍历 data/memories/*.json 文件，每个文件的 messages 数组逐条 INSERT
    （使用 SqlShortTermMemoryRepository.save()，DELETE + batch INSERT）。
    """
    start = time.time()
    if not ctx.memories_dir.is_dir():
        report.warnings.append(f"memories 目录不存在: {ctx.memories_dir}")
        report.elapsed_seconds = time.time() - start
        return

    # 遍历 *.json 文件（排除子目录）
    json_files = [
        entry
        for entry in ctx.memories_dir.iterdir()
        if entry.is_file() and entry.suffix == ".json"
    ]

    if not json_files:
        report.elapsed_seconds = time.time() - start
        return

    if dry_run:
        for f in json_files:
            data = _load_json(f)
            if data is None:
                report.warnings.append(f"解析失败: {f}")
                continue
            messages = data.get("messages", []) or []
            report.inserted += len(messages)
        report.elapsed_seconds = time.time() - start
        return

    repo = SqlShortTermMemoryRepository()
    for f in json_files:
        data = _load_json(f)
        if data is None:
            report.warnings.append(f"解析失败 {f}")
            continue
        device_id = data.get("device_id") or f.stem
        messages = data.get("messages", []) or []
        if messages:
            repo.save(device_id, messages)
            report.inserted += len(messages)
    report.elapsed_seconds = time.time() - start


async def _migrate_long_term_memories(
    ctx: MigrationContext, dry_run: bool, force: bool, report: MigrationReport
) -> None:
    """迁移 memories/{id}/records.jsonl → long_term_memory_records 表

    遍历 data/memories/*/records.jsonl，逐行解析 JSON，
    按 memory_id 合并取最新状态，INSERT 合并后的记录，
    重建 summary_labels + keyword_index。
    """
    start = time.time()
    if not ctx.memories_dir.is_dir():
        report.warnings.append(f"memories 目录不存在: {ctx.memories_dir}")
        report.elapsed_seconds = time.time() - start
        return

    # 遍历子目录，查找 records.jsonl
    records_files: list[tuple[str, Path]] = []
    for entry in ctx.memories_dir.iterdir():
        if entry.is_dir():
            rpath = entry / "records.jsonl"
            if rpath.is_file():
                records_files.append((entry.name, rpath))

    if not records_files:
        report.elapsed_seconds = time.time() - start
        return

    if dry_run:
        for _device_key, rpath in records_files:
            records = _load_jsonl_records(rpath)
            report.inserted += len(records)
        report.elapsed_seconds = time.time() - start
        return

    repo = SqlLongTermMemoryRepository()
    for _device_key, rpath in records_files:
        records = _load_jsonl_records(rpath)
        for rec in records:
            try:
                item = MemoryItem.from_dict(rec)
                if not item.memory_id or not item.device_id:
                    report.warnings.append(
                        f"跳过无效记录（缺 memory_id/device_id）: {rpath}"
                    )
                    continue
                # save() 使用 UPSERT + 自动重建索引
                await repo.save(item)
                report.inserted += 1
            except Exception as e:
                report.warnings.append(f"保存失败 {rpath}: {e}")
    report.elapsed_seconds = time.time() - start


async def _migrate_user_profiles(
    ctx: MigrationContext, dry_run: bool, force: bool, report: MigrationReport
) -> None:
    """迁移 devices/{id}/profile/user_profile.json → user_profiles 表"""
    start = time.time()
    if not ctx.devices_dir.is_dir():
        report.elapsed_seconds = time.time() - start
        return

    profiles: list[tuple[str, Path]] = []
    for device_entry in ctx.devices_dir.iterdir():
        if not device_entry.is_dir():
            continue
        profile_path = device_entry / "profile" / "user_profile.json"
        if profile_path.is_file():
            profiles.append((device_entry.name, profile_path))

    if not profiles:
        report.elapsed_seconds = time.time() - start
        return

    if dry_run:
        report.inserted = len(profiles)
        report.elapsed_seconds = time.time() - start
        return

    repo = UserProfileRepository()
    for device_key, path in profiles:
        profile = _load_json(path)
        if profile is None:
            report.warnings.append(f"解析失败 {path}")
            continue
        # 优先使用 profile 内的 device_id，其次目录名
        device_id = profile.get("device_id") or device_key
        await repo.upsert(device_id, profile)
        report.inserted += 1
    report.elapsed_seconds = time.time() - start


async def _migrate_emotion_history(
    ctx: MigrationContext, dry_run: bool, force: bool, report: MigrationReport
) -> None:
    """迁移 devices/{id}/profile/emotion_history.json → emotion_history 表"""
    start = time.time()
    if not ctx.devices_dir.is_dir():
        report.elapsed_seconds = time.time() - start
        return

    entries: list[tuple[str, Path]] = []
    for device_entry in ctx.devices_dir.iterdir():
        if not device_entry.is_dir():
            continue
        path = device_entry / "profile" / "emotion_history.json"
        if path.is_file():
            entries.append((device_entry.name, path))

    if not entries:
        report.elapsed_seconds = time.time() - start
        return

    if dry_run:
        for _device_key, path in entries:
            data = _load_json(path)
            if data is None:
                report.warnings.append(f"解析失败: {path}")
                continue
            if isinstance(data, list):
                report.inserted += len(data)
        report.elapsed_seconds = time.time() - start
        return

    repo = EmotionHistoryRepository()
    for device_key, path in entries:
        data = _load_json(path)
        if data is None:
            report.warnings.append(f"解析失败 {path}")
            continue
        if not isinstance(data, list):
            report.warnings.append(f"非数组格式: {path}")
            continue
        for record in data:
            if not isinstance(record, dict):
                continue
            await repo.append(device_key, record)
            report.inserted += 1
    report.elapsed_seconds = time.time() - start


async def _migrate_learning_logs(
    ctx: MigrationContext, dry_run: bool, force: bool, report: MigrationReport
) -> None:
    """迁移 devices/{id}/growth/learning_log.json → learning_logs 表"""
    start = time.time()
    if not ctx.devices_dir.is_dir():
        report.elapsed_seconds = time.time() - start
        return

    entries: list[tuple[str, Path]] = []
    for device_entry in ctx.devices_dir.iterdir():
        if not device_entry.is_dir():
            continue
        path = device_entry / "growth" / "learning_log.json"
        if path.is_file():
            entries.append((device_entry.name, path))

    if not entries:
        report.elapsed_seconds = time.time() - start
        return

    if dry_run:
        for _device_key, path in entries:
            data = _load_json(path)
            if data is None:
                report.warnings.append(f"解析失败: {path}")
                continue
            if isinstance(data, list):
                report.inserted += len(data)
        report.elapsed_seconds = time.time() - start
        return

    repo = LearningLogRepository()
    for device_key, path in entries:
        data = _load_json(path)
        if data is None:
            report.warnings.append(f"解析失败 {path}")
            continue
        if not isinstance(data, list):
            report.warnings.append(f"非数组格式: {path}")
            continue
        for entry in data:
            if not isinstance(entry, dict):
                continue
            await repo.append(device_key, entry)
            report.inserted += 1
    report.elapsed_seconds = time.time() - start


async def _migrate_emo_packs(
    ctx: MigrationContext, dry_run: bool, force: bool, report: MigrationReport
) -> None:
    """迁移 emos/packs/*/meta.json → emo_packs 表

    display_name 优先取 meta.json，其次目录名。
    """
    start = time.time()
    if not ctx.emos_packs_dir.is_dir():
        report.elapsed_seconds = time.time() - start
        return

    packs: list[tuple[str, Path]] = []
    for entry in ctx.emos_packs_dir.iterdir():
        if entry.is_dir():
            packs.append((entry.name, entry / "meta.json"))

    if not packs:
        report.elapsed_seconds = time.time() - start
        return

    if dry_run:
        report.inserted = len(packs)
        report.elapsed_seconds = time.time() - start
        return

    repo = EmoPackRepository()
    for pack_name, meta_path in packs:
        display_name = pack_name
        if meta_path.is_file():
            meta = _load_json(meta_path)
            if meta is not None:
                display_name = meta.get("display_name") or pack_name
            else:
                report.warnings.append(f"meta.json 解析失败: {meta_path}")
        await repo.upsert_pack(pack_name, display_name)
        report.inserted += 1
    report.elapsed_seconds = time.time() - start


async def _migrate_skills(
    ctx: MigrationContext, dry_run: bool, force: bool, report: MigrationReport
) -> None:
    """迁移 SKILL.md → skills 表

    扫描 src/skills/ 和 data/devices/*/skills/，
    使用 frontmatter + body UPSERT（覆盖所有字段，含 file_path/directory/source/device_id）。
    """
    start = time.time()

    # 收集所有技能目录：(skill_id, skill_dir, device_id)
    skill_dirs: list[tuple[str, str, str]] = []

    # 1. 全局技能：src/skills/*
    if ctx.skills_root_dir.is_dir():
        for entry in ctx.skills_root_dir.iterdir():
            if entry.is_dir():
                md_path = entry / "SKILL.md"
                if md_path.is_file():
                    skill_dirs.append((entry.name, str(entry), ""))

    # 2. 设备自学习技能：data/devices/*/skills/*
    if ctx.devices_dir.is_dir():
        # 建立 key → MAC 映射（从 users.json）
        key_to_mac = _build_key_to_mac_mapping(ctx.users_json_path)

        for device_entry in ctx.devices_dir.iterdir():
            if not device_entry.is_dir():
                continue
            device_key = device_entry.name
            device_mac = key_to_mac.get(device_key, device_key)
            skills_dir = device_entry / "skills"
            if not skills_dir.is_dir():
                continue
            for skill_entry in skills_dir.iterdir():
                if skill_entry.is_dir():
                    md_path = skill_entry / "SKILL.md"
                    if md_path.is_file():
                        skill_dirs.append(
                            (skill_entry.name, str(skill_entry), device_mac)
                        )

    if not skill_dirs:
        report.elapsed_seconds = time.time() - start
        return

    if dry_run:
        report.inserted = len(skill_dirs)
        report.elapsed_seconds = time.time() - start
        return

    # 逐个 UPSERT（覆盖所有字段）
    now_ts = datetime.now(timezone.utc).timestamp()
    for skill_id, skill_dir, device_id in skill_dirs:
        skill_md_path = os.path.join(skill_dir, "SKILL.md")
        try:
            frontmatter, body = _parse_skill_md(skill_md_path)
        except Exception as e:
            report.warnings.append(f"解析失败 {skill_md_path}: {e}")
            continue

        if not frontmatter or not frontmatter.get("name"):
            report.warnings.append(f"frontmatter 无效或缺少 name: {skill_md_path}")
            continue

        fields = _frontmatter_to_fields(frontmatter)
        metadata = frontmatter.get("metadata", {}) or {}
        source = metadata.get("source", "self_learning" if device_id else "builtin")

        insert_values = {
            "skill_id": skill_id,
            **fields,
            "body": body or "",
            "device_id": device_id,
            "file_path": skill_md_path,
            "directory": skill_dir,
            "source": source,
        }
        # ON CONFLICT DO UPDATE：更新所有字段（含 file_path / directory / device_id / source）
        update_cols = {
            k: getattr(sqlite_insert(SkillModel).excluded, k)
            for k in insert_values
            if k != "skill_id"
        }
        update_cols["updated_at"] = now_ts

        stmt = (
            sqlite_insert(SkillModel)
            .values(**insert_values)
            .on_conflict_do_update(
                index_elements=["skill_id"],
                set_=update_cols,
            )
        )
        async with get_session_ctx() as session:
            await session.execute(stmt)
        report.inserted += 1

    report.elapsed_seconds = time.time() - start


# ============================================================
# 主流程
# ============================================================

# 迁移任务注册表：(表名, 模型类, 迁移函数)
_MIGRATIONS = [
    ("devices", DeviceModel, _migrate_devices),
    ("short_term_memories", ShortTermMemoryModel, _migrate_short_term_memories),
    ("long_term_memory_records", LongTermMemoryRecordModel, _migrate_long_term_memories),
    ("user_profiles", UserProfileModel, _migrate_user_profiles),
    ("emotion_history", EmotionHistoryModel, _migrate_emotion_history),
    ("learning_logs", LearningLogModel, _migrate_learning_logs),
    ("emo_packs", EmoPackModel, _migrate_emo_packs),
    ("skills", SkillModel, _migrate_skills),
]


async def run_migration(
    project_root: Optional[Path] = None,
    dry_run: bool = False,
    force: bool = False,
) -> list[MigrationReport]:
    """运行完整迁移流程

    迁移流程（按顺序）：
        a. 初始化 DB schema（调用 ``init_db()``）
        b. 检查 DB 是否已有数据，有则跳过对应表迁移（除非 ``force=True``）
        c-h. 依次迁移各表
        i. 输出报告

    Args:
        project_root: 项目根目录（None = 自动检测）
        dry_run: 只报告不执行
        force: 强制重新迁移（忽略已有数据）

    Returns:
        各表的迁移报告列表
    """
    if project_root is None:
        project_root = _DEFAULT_PROJECT_ROOT
    ctx = MigrationContext.from_root(project_root)

    # a. 初始化 DB schema（幂等，已存在的表不会被重建）
    await init_db()

    reports: list[MigrationReport] = []
    for table_name, model_cls, migrate_fn in _MIGRATIONS:
        report = MigrationReport(table=table_name)

        # b. 检查 DB 是否已有数据
        rows_before = await _count_rows(model_cls)
        report.rows_before = rows_before

        if rows_before > 0 and not force:
            report.skipped = True
            report.skip_reason = (
                f"已有 {rows_before} 行数据（使用 --force 强制重新迁移）"
            )
            report.rows_after = rows_before
            reports.append(report)
            continue

        # c-h. 执行迁移
        try:
            await migrate_fn(ctx, dry_run, force, report)
        except Exception as e:
            report.warnings.append(f"迁移异常: {e}")
            logger.exception(f"[Migration] {table_name} 迁移异常")

        # 统计迁移后行数
        if not dry_run:
            report.rows_after = await _count_rows(model_cls)
        else:
            report.rows_after = rows_before

        reports.append(report)

    return reports


# ============================================================
# 报告格式化
# ============================================================


def format_report(reports: list[MigrationReport], dry_run: bool) -> str:
    """格式化迁移报告为可读字符串"""
    mode = "[DRY-RUN] " if dry_run else ""
    lines = [
        "",
        "=" * 70,
        f"  {mode}数据迁移报告",
        "=" * 70,
        f"{'表名':<30} {'迁移前':>8} {'迁移后':>8} {'新增/更新':>10} "
        f"{'耗时(s)':>10} {'状态':<8}",
        "-" * 70,
    ]

    total_warnings = 0
    for r in reports:
        if r.skipped:
            status = "SKIP"
        elif r.warnings:
            status = "WARN"
        else:
            status = "OK"
        lines.append(
            f"{r.table:<30} {r.rows_before:>8} {r.rows_after:>8} "
            f"{r.inserted:>10} {r.elapsed_seconds:>10.3f} {status:<8}"
        )
        total_warnings += len(r.warnings)

    lines.append("-" * 70)
    lines.append(f"  警告总数: {total_warnings}")

    if total_warnings > 0:
        lines.append("")
        lines.append("  警告详情:")
        for r in reports:
            for w in r.warnings:
                lines.append(f"    [{r.table}] {w}")

    lines.append("=" * 70)
    lines.append("")
    return "\n".join(lines)


# ============================================================
# 命令行入口
# ============================================================


def main() -> int:
    """命令行入口

    用法：
        python -m src.infrastructure.db.migrations.data_migration
        python -m src.infrastructure.db.migrations.data_migration --dry-run
        python -m src.infrastructure.db.migrations.data_migration --force
    """
    parser = argparse.ArgumentParser(
        description="JSON → SQLite 数据迁移脚本（阶段 4）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只报告不执行迁移",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制重新迁移（忽略已有数据）",
    )
    parser.add_argument(
        "--project-root",
        type=str,
        default=None,
        help="项目根目录（默认自动检测）",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root) if args.project_root else None

    try:
        reports = asyncio.run(
            run_migration(
                project_root=project_root,
                dry_run=args.dry_run,
                force=args.force,
            )
        )
        print(format_report(reports, args.dry_run))
        # 有警告返回 1，无警告返回 0
        return 1 if any(r.warnings for r in reports) else 0
    except KeyboardInterrupt:
        print("\n迁移已中断")
        return 130
    finally:
        # 释放引擎资源
        try:
            asyncio.run(dispose_engine())
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
