"""
Skill System — 让 LLM 能通过说明书学会使用工具的组合

目录结构：
  src/skills/
    <skill_id>/       ← 每个技能一个目录，内含 SKILL.md
      SKILL.md

每个设备在 DB 的 skills 列表中声明它拥有哪些技能。
不在列表中的技能对该设备不可见。
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from typing import Optional

from src.use_cases._plugin_helpers import json_dumps

from src.infrastructure.logging import get_logger

logger = get_logger(__name__)

# ── 数据模型 ─────────────────────────────────────────────────


@dataclass
class SkillMetadata:
    """从 SKILL.md frontmatter 解析出的元数据"""
    name: str
    description: str
    author: str = ""
    cap_groups: list[str] = field(default_factory=list)
    manage_mode: str = "readonly"
    category: list[str] = field(default_factory=list)
    peripherals: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    device_id: str = ""  # 为空表示全局技能


@dataclass
class SkillEntry:
    """一个已注册的 Skill"""
    id: str
    metadata: SkillMetadata
    body: str
    file_path: str
    directory: str


@dataclass
class SkillCatalogEntry:
    """LLM 看到的精简版技能信息"""
    id: str
    description: str
    category: list[str]
    tags: list[str]
    device_id: str = ""


# ── 全局注册表 ──────────────────────────────────────────────

_skills_by_id: dict[str, SkillEntry] = {}
_skills_by_device: dict[str, list[SkillEntry]] = {}  # device_id → [skills]
_global_skills: list[SkillEntry] = []
_skills_dir: str = ""
_data_dir: str = ""  # 设备自学习技能的数据目录
_skill_retriever: Optional["SkillRetriever"] = None  # 技能检索器（init/reload 时重建）


def init(skills_root_dir: str, data_dir: str = "") -> None:
    """
    初始化 Skill 系统。
    扁平扫描 skills_root_dir 下所有子目录，每个子目录为一个技能。
    同时扫描 data_dir/devices/*/skills 目录，加载设备自学习的技能。
    不再区分 global/devices，设备的技能归属完全由 DB 的 skills 列表控制。
    """
    global _skills_dir, _data_dir
    _skills_dir = skills_root_dir
    _data_dir = data_dir
    _skills_by_id.clear()
    _skills_by_device.clear()
    _global_skills.clear()

    # 扁平扫描所有子目录，全部作为全局技能加载
    _scan_directory(skills_root_dir, device_id="")

    # 扫描设备目录下的自学习技能
    if data_dir:
        _scan_device_skills(data_dir)

    total = len(_skills_by_id)
    logger.info(f"[SkillSystem] 已加载 {total} 个技能")

    _rebuild_retriever()


def reload() -> None:
    """重新加载所有技能（热更新用）"""
    if _skills_dir:
        init(_skills_dir, _data_dir)


def _scan_directory(directory: str, device_id: str = "") -> None:
    """扫描单个目录下的所有技能"""
    if not os.path.isdir(directory):
        return

    for entry in os.scandir(directory):
        if not entry.is_dir():
            continue
        _load_skill(entry.path, device_id)


def _scan_device_skills(data_dir: str) -> None:
    """扫描所有设备目录下的自学习技能"""
    devices_dir = os.path.join(data_dir, "devices")
    if not os.path.isdir(devices_dir):
        return

    # 从 DB 建立 key -> MAC 映射（DB 为唯一数据源）
    key_to_mac = {}
    try:
        from src.infrastructure.db.repositories.device_repository import DeviceRepository
        all_devices = DeviceRepository().load_all_devices_sync() or {}
        for device_id, cfg in all_devices.items():
            key = cfg.get("key", "")
            mac = cfg.get("mac", "") or device_id
            if key:
                key_to_mac[key] = mac
    except Exception as e:
        logger.error(f"[SkillSystem] 从 DB 读取设备配置失败: {e}")

    count = 0
    for device_entry in os.scandir(devices_dir):
        if not device_entry.is_dir():
            continue

        device_key = device_entry.name
        # 获取 MAC 地址，如果没有则用 key
        device_mac = key_to_mac.get(device_key, device_key)

        skills_dir = os.path.join(device_entry.path, "skills")
        if not os.path.isdir(skills_dir):
            continue

        # 扫描设备skills目录下的每个skill
        for skill_entry in os.scandir(skills_dir):
            if not skill_entry.is_dir():
                continue
            # 用 device_key 作为 device_id，与 pipeline/API 传入的 device_id 保持一致
            skill = _load_skill(skill_entry.path, device_id=device_key)
            if skill:
                count += 1

    if count > 0:
        logger.info(f"[SkillSystem] 从设备目录加载了 {count} 个自学习技能")





def _load_skill(skill_dir: str, device_id: str = "") -> Optional[SkillEntry]:
    """加载单个技能目录"""
    skill_id = os.path.basename(skill_dir)
    skill_md_path = os.path.join(skill_dir, "SKILL.md")
    if not os.path.isfile(skill_md_path):
        return None

    try:
        meta, body = _parse_skill_md(skill_md_path)
        if meta and meta.name:
            if meta.name != skill_id:
                logger.warning(
                    f"[SkillSystem] 技能 {skill_id} 的 frontmatter name "
                    f"({meta.name}) 与目录名不匹配"
                )
            meta.device_id = device_id

            entry = SkillEntry(
                id=skill_id,
                metadata=meta,
                body=body,
                file_path=skill_md_path,
                directory=skill_dir,
            )
            _skills_by_id[skill_id] = entry
            # 替换 _global_skills 中的旧条目
            for i, s in enumerate(_global_skills):
                if s.id == skill_id:
                    _global_skills[i] = entry
                    break
            else:
                _global_skills.append(entry)
            return entry
    except Exception as e:
        logger.error(f"[SkillSystem] 解析 {skill_md_path} 失败: {e}")

    return None


def _parse_skill_md(path: str) -> tuple[Optional[SkillMetadata], str]:
    """解析 SKILL.md 文件"""
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    return _parse_skill_content(content)


def _parse_skill_content(content: str) -> tuple[Optional[SkillMetadata], str]:
    """解析 SKILL.md 内容字符串（用户上传/市场安装共用）"""
    fm_pattern = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
    m = fm_pattern.match(content)
    if not m:
        logger.warning("[SkillSystem] 内容缺少 frontmatter")
        return None, content

    raw_json = m.group(1).strip()
    body = content[m.end():].strip()

    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as e:
        logger.error(f"[SkillSystem] 内容 JSON 解析失败: {e}")
        return None, body

    meta_data = data.get("metadata", {})

    meta = SkillMetadata(
        name=data.get("name", ""),
        description=data.get("description", ""),
        author=data.get("author", ""),
        cap_groups=meta_data.get("cap_groups", []),
        manage_mode=meta_data.get("manage_mode", "readonly"),
        category=meta_data.get("category", []),
        peripherals=meta_data.get("peripherals", []),
        tags=meta_data.get("tags", []),
    )
    return meta, body


# ── 设备感知 API ────────────────────────────────────────────


def get_catalog(device_id: str = "", skills: list[str] | None = None) -> list[SkillCatalogEntry]:
    """
    获取某个设备可见的技能目录。
    - skills=None → 返回所有技能（向后兼容）
    - skills=[] → 返回空列表
    - skills=["skill_a"] → 只返回列表中的技能
    - 设备自学习的技能（device_id 匹配）自动包含，无需在 skills 列表中配置
    """
    result = []
    for skill in _global_skills:
        # 设备自学习的技能（device_id 匹配）自动包含
        if device_id and skill.metadata.device_id == device_id:
            result.append(SkillCatalogEntry(
                id=skill.id,
                description=skill.metadata.description,
                category=skill.metadata.category,
                tags=skill.metadata.tags,
                device_id=skill.metadata.device_id,
            ))
        # 全局技能或在 skills 列表中的技能
        elif skills is None or skill.id in skills:
            result.append(SkillCatalogEntry(
                id=skill.id,
                description=skill.metadata.description,
                category=skill.metadata.category,
                tags=skill.metadata.tags,
                device_id="",
            ))
    return result


def get_skill(skill_id: str) -> Optional[SkillEntry]:
    """按 ID 获取技能（不限设备）"""
    return _skills_by_id.get(skill_id)


def get_skill_document(skill_id: str) -> Optional[str]:
    """获取技能的完整文档（含 body）"""
    skill = _skills_by_id.get(skill_id)
    if not skill:
        return None

    body = skill.body.replace("{CUR_SKILL_DIR}", skill.directory)
    return body


def get_skill_cap_groups(skill_id: str) -> list[str]:
    """获取技能需要的工具组"""
    skill = _skills_by_id.get(skill_id)
    if not skill:
        return []
    return skill.metadata.cap_groups


def get_skill_directory(skill_id: str) -> Optional[str]:
    """获取技能的目录路径"""
    skill = _skills_by_id.get(skill_id)
    if not skill:
        return None
    return skill.directory


def is_skill_available_for_device(skill_id: str, device_id: str, skills: list[str] | None = None) -> bool:
    """检查某个技能是否对指定设备可用。
    skills: 设备的 skills 列表，None=全部可用，[]=全部不可用。
    """
    if skills is not None and skill_id not in skills:
        return False
    return _skills_by_id.get(skill_id) is not None


def get_device_skill_ids(device_id: str, skills: list[str] | None = None) -> list[str]:
    """获取某设备的所有技能 ID。
    skills: 可选过滤列表，只返回列表中的技能 ID。
    """
    ids = set()
    for s in _global_skills:
        if skills is None or s.id in skills:
            ids.add(s.id)
    return list(ids)


# ── 技能检索器（按用户输入动态激活） ────────────────────────


class SkillRetriever:
    """技能检索器：按用户输入检索最相关的 Top-K 个技能。

    复用 tools_system.ToolRetriever 的关键词 n-gram 匹配机制，
    让提示词只注入当前相关的技能，避免随技能累积而膨胀。
    """

    def __init__(self, top_k: int = 5, min_result: int = 2):
        from src.use_cases.tools_system import ToolRetriever
        self._retriever = ToolRetriever(top_k=top_k, min_result=min_result)
        self._index_valid = False

    def update_index(self, catalog: list[SkillCatalogEntry]) -> None:
        schemas = []
        for entry in catalog:
            doc = get_skill_document(entry.id) or ""
            schemas.append({
                "function": {
                    "name": entry.id,
                    "description": f"{entry.description}\n{doc}",
                }
            })
        self._retriever.update_index(schemas)
        self._index_valid = True

    def retrieve(self, query: str, all_skill_ids: list[str]) -> list[str]:
        if not self._index_valid or not query or not query.strip():
            return all_skill_ids
        result = self._retriever.retrieve(query, set(all_skill_ids))
        return [sid for sid in all_skill_ids if sid in result]


def _rebuild_retriever() -> None:
    """重建技能检索索引（init/reload 时调用）"""
    global _skill_retriever
    try:
        _skill_retriever = SkillRetriever(top_k=5)
        _skill_retriever.update_index(get_catalog())
    except Exception as e:
        logger.warning(f"[SkillSystem] 技能检索索引重建失败: {e}")


def retrieve_relevant_skills(
    query: str,
    device_id: str = "",
    skills: list[str] | None = None,
    disabled_skills: list[str] | None = None,
    top_k: int = 5,
) -> list[SkillCatalogEntry]:
    """按用户输入检索最相关的技能（用于每轮动态注入提示词）。

    query 为空时返回全部可见技能（安全降级）。
    """
    catalog = get_catalog(device_id, skills)
    if disabled_skills:
        catalog = [e for e in catalog if e.id not in disabled_skills]
    if not catalog:
        return []
    visible_ids = [e.id for e in catalog]
    result_ids = _skill_retriever.retrieve(query, visible_ids) if _skill_retriever else visible_ids
    by_id = {e.id: e for e in catalog}
    return [by_id[sid] for sid in result_ids if sid in by_id]


def _render_core_personality(
    device_id: str = "",
    skills: list[str] | None = None,
    disabled_skills: list[str] | None = None,
    max_chars: int = 600,
) -> str:
    """合并 self_growth / user_profile 技能为一段紧凑的核心人格描述（始终在提示词）。

    self_growth 技能内容高度重复（自学习反复追加相似段落），
    每类只取第一个技能的开头核心指令，避免人格描述随技能数膨胀。
    """
    catalog = get_catalog(device_id, skills)
    if disabled_skills:
        catalog = [e for e in catalog if e.id not in disabled_skills]
    core = [e for e in catalog if e.category and ("self_growth" in e.category or "user_profile" in e.category)]
    if not core:
        return ""

    sections = []
    seen_categories: set[str] = set()
    for entry in core:
        cat = entry.category[0] if entry.category else "general"
        if cat in seen_categories:
            continue
        seen_categories.add(cat)
        doc = get_skill_document(entry.id) or ""
        text = doc.strip()
        if text:
            sections.append(text[:400].strip())

    if not sections:
        return ""
    merged = "\n\n".join(sections)
    if len(merged) > max_chars:
        merged = merged[:max_chars].rstrip() + "\n…（完整人格设定可用 read_skill_document 查看）"
    return "## 核心人格设定 (Core Personality)\n\n" + merged


# ── 技能管理 API ──────────────────────────────────────────


_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def create_skill(
    name: str,
    description: str,
    instructions: str,
    category: list[str] | None = None,
    tags: list[str] | None = None,
    cap_groups: list[str] | None = None,
) -> SkillEntry:
    """
    创建一个新技能。
    自动生成标准 SKILL.md 并注册到内存。
    """
    if not name or not _NAME_RE.match(name):
        raise ValueError("技能名称只能包含小写字母、数字和下划线，且必须以字母开头")

    if not description or not description.strip():
        raise ValueError("description 不能为空")

    if not instructions or not instructions.strip():
        raise ValueError("instructions 不能为空")

    if _skills_dir and os.path.isdir(os.path.join(_skills_dir, name)):
        raise ValueError(f"技能 '{name}' 已存在")

    skill_dir = os.path.join(_skills_dir, name) if _skills_dir else ""
    if not skill_dir:
        raise ValueError("技能目录未初始化")

    os.makedirs(skill_dir, exist_ok=True)

    frontmatter = {
        "name": name,
        "description": description.strip(),
        "metadata": {
            "cap_groups": cap_groups or [],
            "manage_mode": "readonly",
            "category": category or [],
            "tags": tags or [],
        },
    }

    body_lines = [
        f"# {name}",
        "",
        description.strip(),
        "",
        "## 执行步骤",
        "",
        instructions.strip(),
    ]

    content = "---\n" + json_dumps(frontmatter, indent=2) + "\n---\n\n" + "\n".join(body_lines) + "\n"

    md_path = os.path.join(skill_dir, "SKILL.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(content)

    entry = _load_skill(skill_dir)
    if not entry:
        raise RuntimeError(f"创建成功但加载失败: {md_path}")

    logger.info(f"[SkillSystem] 已创建技能: {name}")
    return entry


def import_skill_from_content(content: str) -> SkillEntry:
    """从 SKILL.md 内容导入技能（用户上传 / 市场安装共用）。

    技能 ID 取 frontmatter 的 name，校验合法性后写入技能目录并注册到内存。
    """
    if not content or not content.strip():
        raise ValueError("SKILL.md 内容不能为空")

    meta, _ = _parse_skill_content(content)
    if not meta or not meta.name:
        raise ValueError("SKILL.md 缺少有效的 frontmatter（name/description 必填）")

    skill_id = meta.name
    if not _NAME_RE.match(skill_id):
        raise ValueError("技能名称只能包含小写字母、数字和下划线，且必须以字母开头")

    if _skills_dir and os.path.isdir(os.path.join(_skills_dir, skill_id)):
        raise ValueError(f"技能 '{skill_id}' 已存在")

    skill_dir = os.path.join(_skills_dir, skill_id) if _skills_dir else ""
    if not skill_dir:
        raise ValueError("技能目录未初始化")
    os.makedirs(skill_dir, exist_ok=True)

    md_path = os.path.join(skill_dir, "SKILL.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(content)

    entry = _load_skill(skill_dir)
    if not entry:
        raise RuntimeError(f"导入成功但加载失败: {md_path}")

    logger.info(f"[SkillSystem] 已导入技能: {skill_id}")
    return entry


def parse_skill_content(content: str) -> dict:
    """解析 SKILL.md 内容，返回元信息 dict（供上传/发布校验用，不落盘）。"""
    meta, _ = _parse_skill_content(content)
    if not meta or not meta.name:
        raise ValueError("SKILL.md 缺少有效的 frontmatter（name/description 必填）")
    return {
        "id": meta.name,
        "name": meta.name,
        "description": meta.description,
        "author": meta.author,
        "category": meta.category,
        "tags": meta.tags,
    }


def update_skill(
    skill_id: str,
    description: str = "",
    instructions: str = "",
    category: list[str] | None = None,
    tags: list[str] | None = None,
    cap_groups: list[str] | None = None,
) -> SkillEntry:
    """更新已有技能的 SKILL.md 并重新加载。
    instructions 接收 body 全文，直接写入 frontmatter 之后。
    """
    entry = _skills_by_id.get(skill_id)
    if not entry:
        raise ValueError(f"技能不存在: {skill_id}")

    meta = entry.metadata
    if description:
        meta.description = description.strip()
    if category is not None:
        meta.category = category
    if tags is not None:
        meta.tags = tags
    if cap_groups is not None:
        meta.cap_groups = cap_groups

    frontmatter = {
        "name": skill_id,
        "description": meta.description,
        "metadata": {
            "cap_groups": meta.cap_groups,
            "manage_mode": meta.manage_mode,
            "category": meta.category,
            "tags": meta.tags,
        },
    }

    body = instructions.strip() if instructions else ""
    content = "---\n" + json_dumps(frontmatter, indent=2) + "\n---\n\n" + body + "\n"

    md_path = entry.file_path
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(content)

    _load_skill(entry.directory)
    logger.info(f"[SkillSystem] 已更新技能: {skill_id}")
    return _skills_by_id[skill_id]


def delete_skill(skill_id: str) -> bool:
    """
    删除一个技能（删除目录并从内存注销）。
    """
    entry = _skills_by_id.get(skill_id)
    if not entry:
        return False

    skill_dir = entry.directory
    if skill_dir and os.path.isdir(skill_dir):
        shutil.rmtree(skill_dir)
        logger.info(f"[SkillSystem] 已删除技能目录: {skill_dir}")

    _skills_by_id.pop(skill_id, None)
    _global_skills[:] = [s for s in _global_skills if s.id != skill_id]
    for device_skills in _skills_by_device.values():
        device_skills[:] = [s for s in device_skills if s.id != skill_id]

    logger.info(f"[SkillSystem] 已注销技能: {skill_id}")
    return True


# ── 渲染目录（给 LLM 用） ──────────────────────────────────


def render_skills_catalog(
    device_id: str = "",
    skills: list[str] | None = None,
    disabled_skills: list[str] | None = None,
    query: str = "",
) -> str:
    """
    渲染技能内容，注入到 LLM 系统提示词中。

    三层结构控制提示词体积（自学习技能会持续累积）：
    1. 核心人格层：self_growth/user_profile 技能合并为紧凑人格描述，始终内联；
    2. 动态检索层：按 query 检索 Top-K 相关技能，只注入这些技能的文档；
    3. 兜底说明：其余技能可通过 list_available_skills / read_skill_document 按需加载。
    """
    catalog = get_catalog(device_id, skills)
    if not catalog:
        return ""
    if disabled_skills:
        catalog = [e for e in catalog if e.id not in disabled_skills]
    if not catalog:
        return ""

    lines = [
        "## 技能规则 (Skill Rules)",
        "",
        "匹配触发条件时，必须严格按照技能执行步骤回复，不要自行发挥。",
        "",
    ]

    # 第 1 层：核心人格（始终内联）
    core = _render_core_personality(device_id, skills, disabled_skills)
    if core:
        lines.append(core)
        lines.append("")

    # 第 2 层：按用户输入检索 Top-K 相关技能
    relevant = retrieve_relevant_skills(query, device_id, skills, disabled_skills, top_k=5)
    for entry in relevant:
        # 核心人格已覆盖的技能不再重复内联
        if entry.category and ("self_growth" in entry.category or "user_profile" in entry.category):
            continue
        doc = get_skill_document(entry.id) or ""
        if len(doc) > 400:
            doc = doc[:400].rstrip() + "\n…（完整内容可用 read_skill_document 查看）"
        lines.append(f"### 技能: {entry.id}")
        lines.append(f"触发条件: {entry.description}")
        lines.append(f"执行规则:\n{doc}")
        lines.append("")

    # 第 3 层：兜底说明
    lines.append("### 其他技能")
    lines.append("可用 `list_available_skills` 查看全部，`read_skill_document(\"skill_id\")` 加载完整说明。")
    lines.append("")

    return "\n".join(lines)
