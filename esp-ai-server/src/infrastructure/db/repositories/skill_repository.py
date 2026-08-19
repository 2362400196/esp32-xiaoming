"""技能仓储（SQL 实现，阶段 2：仓储层）

替代 ``SKILL.md`` 的 frontmatter + body 读写。frontmatter 拍平为列，body 存 Markdown 正文。
``file_path`` 和 ``directory`` 保留文件系统链接（过渡期双写）。

替代项：
- ``src/use_cases/skill_system.py`` 中的内存注册表（``_skills_by_id`` / ``_global_skills``）
  及 ``_parse_skill_md`` / ``init`` / ``get_catalog`` / ``get_skill`` 等
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from src.infrastructure.db.compat.sync_session import get_sync_session
from src.infrastructure.db.models.skill import SkillModel
from src.infrastructure.db.session import get_session_ctx
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


# ============================================================
# 辅助函数
# ============================================================

def _now_ts() -> float:
    """当前 UTC 时间戳（秒）"""
    return datetime.now(timezone.utc).timestamp()


def _parse_skill_md(path: str) -> tuple[Optional[dict], str]:
    """解析 SKILL.md 文件，返回 ``(frontmatter_dict, body)``。

    frontmatter 为 ``---\\n{json}\\n---\\n`` 格式的 JSON 对象。
    解析失败时 frontmatter 返回 None，body 返回去 frontmatter 后的正文（或全文）。
    """
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    fm_pattern = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
    m = fm_pattern.match(content)
    if not m:
        return None, content

    raw_json = m.group(1).strip()
    body = content[m.end():].strip()

    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        return None, body

    return data, body


def _frontmatter_to_fields(frontmatter: dict) -> dict:
    """将 frontmatter dict 拍平为 SkillModel 字段字典（不含 skill_id 主键）。

    frontmatter 结构（与 SKILL.md 一致）：
    ::
        {
            "name": str,
            "description": str,
            "author": str,
            "metadata": {
                "cap_groups": list,
                "manage_mode": str,
                "category": list,
                "peripherals": list,
                "tags": list,
            }
        }
    """
    metadata = frontmatter.get("metadata", {}) or {}
    return {
        "name": frontmatter.get("name", "") or "",
        "description": frontmatter.get("description", "") or "",
        "author": frontmatter.get("author", "") or "",
        "cap_groups": list(metadata.get("cap_groups", []) or []),
        "category": list(metadata.get("category", []) or []),
        "peripherals": list(metadata.get("peripherals", []) or []),
        "tags": list(metadata.get("tags", []) or []),
        "manage_mode": metadata.get("manage_mode", "readonly") or "readonly",
    }


def _model_to_skill_dict(model: SkillModel) -> dict:
    """将 SkillModel 转换为 skill dict（frontmatter + body 结构）。"""
    return {
        "skill_id": model.skill_id,
        "frontmatter": {
            "name": model.name or "",
            "description": model.description or "",
            "author": model.author or "",
            "metadata": {
                "cap_groups": list(model.cap_groups or []),
                "manage_mode": model.manage_mode or "readonly",
                "category": list(model.category or []),
                "peripherals": list(model.peripherals or []),
                "tags": list(model.tags or []),
            },
        },
        "body": model.body or "",
        "device_id": model.device_id or "",
        "file_path": model.file_path or "",
        "directory": model.directory or "",
        "source": model.source or "builtin",
    }


def _model_to_catalog_entry(model: SkillModel) -> dict:
    """将 SkillModel 转换为精简版目录条目（给 LLM / API 用）。"""
    return {
        "id": model.skill_id,
        "description": model.description or "",
        "category": list(model.category or []),
        "tags": list(model.tags or []),
        "device_id": model.device_id or "",
    }


# ============================================================
# SkillRepository
# ============================================================

class SkillRepository:
    """技能仓储

    异步方法供路由层使用（``get_session_ctx``），
    ``init_sync`` 供启动时从磁盘同步 SKILL.md 到 DB（``get_sync_session``）。

    存储布局：
    - ``skills`` 表：frontmatter 拍平为列，body 存 Markdown 正文
    - ``file_path`` / ``directory`` 保留文件系统链接（过渡期双写）
    - ``device_id`` 为空表示全局技能
    """

    # ============================================================
    # 异步方法
    # ============================================================

    async def get_skill(self, skill_id: str) -> Optional[dict]:
        """按 ID 获取技能，返回 frontmatter + body 结构的 dict。

        未找到返回 None。
        """
        if not skill_id:
            return None
        async with get_session_ctx() as session:
            result = await session.execute(
                select(SkillModel).where(SkillModel.skill_id == skill_id)
            )
            model = result.scalar_one_or_none()
            if model is None:
                return None
            return _model_to_skill_dict(model)

    async def get_catalog(
        self,
        device_id: Optional[str] = None,
        skills_filter: Optional[list[str]] = None,
    ) -> list[dict]:
        """获取设备可见的技能目录。

        过滤逻辑（与 ``skill_system.get_catalog`` 一致）：
        - 设备自学习的技能（``device_id`` 匹配）自动包含
        - ``skills_filter=None``：返回所有全局技能
        - ``skills_filter=[]``：不返回全局技能（仅设备自学习的）
        - ``skills_filter=["skill_a"]``：只返回列表中的全局技能

        返回 ``[{"id", "description", "category", "tags", "device_id"}]``。
        """
        async with get_session_ctx() as session:
            result = await session.execute(select(SkillModel))
            models = result.scalars().all()

        catalog = []
        for m in models:
            # 设备自学习的技能（device_id 匹配）自动包含
            if device_id and (m.device_id or "") == device_id:
                catalog.append(_model_to_catalog_entry(m))
            # 全局技能或在 skills 列表中的技能
            elif skills_filter is None or m.skill_id in skills_filter:
                catalog.append(_model_to_catalog_entry(m))
        return catalog

    async def upsert_skill(
        self,
        skill_id: str,
        frontmatter: dict,
        body: str,
    ) -> None:
        """插入或更新技能（SQLite ``INSERT ... ON CONFLICT DO UPDATE``）。

        - 新技能：插入（``file_path`` / ``directory`` / ``source`` / ``device_id``
          使用默认值）
        - 已存在：更新 frontmatter 派生字段 + body + ``updated_at``，
          **不覆盖** ``file_path`` / ``directory`` / ``source`` / ``device_id``
        """
        if not skill_id:
            return
        fields = _frontmatter_to_fields(frontmatter or {})
        # 插入时的默认值（冲突时不更新这些字段）
        insert_values = {
            "skill_id": skill_id,
            **fields,
            "body": body or "",
            "file_path": "",
            "directory": "",
            "source": "builtin",
            "device_id": "",
        }
        stmt = sqlite_insert(SkillModel).values(**insert_values)
        # ON CONFLICT DO UPDATE：仅更新 frontmatter 字段 + body + updated_at
        update_cols = {k: getattr(stmt.excluded, k) for k in fields.keys()}
        update_cols["body"] = stmt.excluded.body
        update_cols["updated_at"] = _now_ts()
        stmt = stmt.on_conflict_do_update(
            index_elements=["skill_id"],
            set_=update_cols,
        )
        async with get_session_ctx() as session:
            await session.execute(stmt)

    async def delete_skill(self, skill_id: str) -> bool:
        """删除技能。

        返回 True 表示存在并已删除，False 表示不存在。
        注意：仅删除 DB 记录，不删除磁盘文件（由调用方处理）。
        """
        if not skill_id:
            return False
        async with get_session_ctx() as session:
            result = await session.execute(
                delete(SkillModel).where(SkillModel.skill_id == skill_id)
            )
            return (result.rowcount or 0) > 0

    async def list_skills_by_device(self, device_id: str) -> list[dict]:
        """列出指定设备的全部自学习技能（``device_id`` 匹配）。

        返回 ``[{"id", "description", "category", "tags", "device_id"}]``。
        """
        if not device_id:
            return []
        async with get_session_ctx() as session:
            result = await session.execute(
                select(SkillModel).where(SkillModel.device_id == device_id)
            )
            return [_model_to_catalog_entry(m) for m in result.scalars().all()]

    # ============================================================
    # 同步方法
    # ============================================================

    def init_sync(self, skills_root_dir: str, data_dir: str = "") -> None:
        """从磁盘扫描 SKILL.md 并 UPSERT 到 DB（同步）。

        扫描逻辑（与 ``skill_system.init`` 一致）：
        1. 扁平扫描 ``skills_root_dir`` 下所有子目录 → 全局技能（``device_id=""``）
        2. 若提供 ``data_dir``，扫描 ``data_dir/devices/*/skills/*`` → 设备自学习技能
           - 从 DB 建立 key → MAC 映射，找不到则用目录名作为 device_id

        每个技能目录内须有 ``SKILL.md`` 文件，frontmatter 解析失败则跳过。
        """
        synced = 0

        # 1. 扫描全局技能
        if skills_root_dir and os.path.isdir(skills_root_dir):
            for entry in os.scandir(skills_root_dir):
                if not entry.is_dir():
                    continue
                if self._sync_one_from_disk(entry.path, device_id=""):
                    synced += 1

        # 2. 扫描设备自学习技能
        if data_dir:
            devices_dir = os.path.join(data_dir, "devices")
            if os.path.isdir(devices_dir):
                key_to_mac = self._load_key_to_mac_mapping()
                for device_entry in os.scandir(devices_dir):
                    if not device_entry.is_dir():
                        continue
                    device_key = device_entry.name
                    device_mac = key_to_mac.get(device_key, device_key)
                    skills_dir = os.path.join(device_entry.path, "skills")
                    if not os.path.isdir(skills_dir):
                        continue
                    for skill_entry in os.scandir(skills_dir):
                        if not skill_entry.is_dir():
                            continue
                        if self._sync_one_from_disk(
                            skill_entry.path, device_id=device_mac
                        ):
                            synced += 1

        logger.info(f"[SkillRepository] init_sync: 已同步 {synced} 个技能")

    # ============================================================
    # 内部辅助
    # ============================================================

    def _sync_one_from_disk(
        self,
        skill_dir: str,
        device_id: str = "",
    ) -> bool:
        """从磁盘读取单个技能目录的 SKILL.md 并 UPSERT 到 DB（同步）。

        返回 True 表示成功同步，False 表示跳过（无 SKILL.md 或解析失败）。
        """
        skill_id = os.path.basename(skill_dir)
        skill_md_path = os.path.join(skill_dir, "SKILL.md")
        if not os.path.isfile(skill_md_path):
            return False

        try:
            frontmatter, body = _parse_skill_md(skill_md_path)
        except Exception as e:
            logger.warning(f"[SkillRepository] 解析 {skill_md_path} 失败: {e}")
            return False

        if not frontmatter or not frontmatter.get("name"):
            return False

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
        # ON CONFLICT DO UPDATE：更新所有字段（含 file_path / directory / device_id）
        stmt = sqlite_insert(SkillModel).values(**insert_values)
        update_cols = {k: getattr(stmt.excluded, k) for k in insert_values if k != "skill_id"}
        update_cols["updated_at"] = _now_ts()
        stmt = stmt.on_conflict_do_update(
            index_elements=["skill_id"],
            set_=update_cols,
        )

        with get_sync_session() as session:
            session.execute(stmt)

        return True

    @staticmethod
    def _load_key_to_mac_mapping() -> dict[str, str]:
        """从 DB 建立 ``device_key → mac`` 映射。

        DB 不可用时返回空 dict（回退到用目录名作为 device_id）。
        """
        mapping: dict[str, str] = {}
        try:
            from src.infrastructure.db.repositories.device_repository import DeviceRepository
            all_devices = DeviceRepository().load_all_devices_sync() or {}
            for device_id, cfg in all_devices.items():
                key = cfg.get("key", "") if isinstance(cfg, dict) else ""
                mac = cfg.get("mac", "") or device_id
                if key:
                    mapping[key] = mac
        except Exception as e:
            logger.error(f"[SkillRepository] 从 DB 读取设备配置失败: {e}")
        return mapping


__all__ = ["SkillRepository"]
