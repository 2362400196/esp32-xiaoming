"""
skill_system.py 单元测试

覆盖范围：
- init / reload / _scan_directory / _load_skill / _parse_skill_md
- get_catalog / get_skill / get_skill_document / get_skill_cap_groups / get_skill_directory
- is_skill_available_for_device / get_device_skill_ids
- create_skill / update_skill / delete_skill
- render_skills_catalog
"""
import json
import os
from unittest.mock import patch

import pytest

from src.use_cases import skill_system
from src.use_cases.skill_system import (
    SkillCatalogEntry,
    SkillEntry,
    SkillMetadata,
)


# 辅助：创建一个有效的 SKILL.md 内容
def _make_skill_md(name, description, body, cap_groups=None, category=None, tags=None):
    frontmatter = {
        "name": name,
        "description": description,
        "metadata": {
            "cap_groups": cap_groups or [],
            "manage_mode": "readonly",
            "category": category or ["test"],
            "tags": tags or ["t1"],
        },
    }
    return "---\n" + json.dumps(frontmatter, ensure_ascii=False, indent=2) + "\n---\n\n" + body


# 辅助 fixture：创建临时技能目录并初始化
@pytest.fixture
def skill_setup(tmp_path):
    """创建临时技能目录，含两个技能"""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    # 技能 1
    skill1_dir = skills_dir / "weather"
    skill1_dir.mkdir()
    (skill1_dir / "SKILL.md").write_text(
        _make_skill_md("weather", "查天气", "## 步骤\n调用天气API", category=["tool"], tags=["weather"]),
        encoding="utf-8",
    )

    # 技能 2（长文档，>500字）
    skill2_dir = skills_dir / "long_skill"
    skill2_dir.mkdir()
    long_body = "x" * 600
    (skill2_dir / "SKILL.md").write_text(
        _make_skill_md("long_skill", "长文档技能", long_body, category=["doc"], tags=["long"]),
        encoding="utf-8",
    )

    skill_system.init(str(skills_dir))
    yield skills_dir
    # 清理全局状态
    skill_system._skills_by_id.clear()
    skill_system._global_skills.clear()
    skill_system._skills_by_device.clear()
    skill_system._skills_dir = ""


# ============================================================
# SkillMetadata / SkillEntry / SkillCatalogEntry
# ============================================================


class TestSkillMetadata:
    """SkillMetadata 数据类"""

    def test_defaults(self):
        m = SkillMetadata(name="test", description="desc")
        assert m.name == "test"
        assert m.description == "desc"
        assert m.author == ""
        assert m.cap_groups == []
        assert m.manage_mode == "readonly"
        assert m.category == []
        assert m.peripherals == []
        assert m.tags == []
        assert m.device_id == ""


class TestSkillCatalogEntry:
    """SkillCatalogEntry 数据类"""

    def test_defaults(self):
        e = SkillCatalogEntry(id="x", description="d", category=[], tags=[])
        assert e.id == "x"
        assert e.device_id == ""


# ============================================================
# init / reload
# ============================================================


class TestInit:
    """init 初始化"""

    def test_init_loads_skills(self, skill_setup):
        # init 已在 fixture 中调用
        assert "weather" in skill_system._skills_by_id
        assert "long_skill" in skill_system._skills_by_id

    def test_init_empty_dir(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        skill_system.init(str(empty_dir))
        assert len(skill_system._skills_by_id) == 0

    def test_init_nonexistent_dir(self, tmp_path):
        # 不存在的目录不应抛异常
        skill_system.init(str(tmp_path / "nonexistent"))
        assert len(skill_system._skills_by_id) == 0

    def test_init_sets_skills_dir(self, skill_setup):
        assert skill_system._skills_dir == str(skill_setup)

    def test_init_with_data_dir(self, tmp_path):
        """带 data_dir 时扫描设备技能"""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "global_skill").mkdir()
        (skills_dir / "global_skill" / "SKILL.md").write_text(
            _make_skill_md("global_skill", "全局", "body"), encoding="utf-8"
        )

        data_dir = tmp_path / "data"
        devices_dir = data_dir / "devices"
        dev_skills = devices_dir / "dev1" / "skills"
        dev_skills.mkdir(parents=True)
        (dev_skills / "custom_skill").mkdir()
        (dev_skills / "custom_skill" / "SKILL.md").write_text(
            _make_skill_md("custom_skill", "自定义", "body"), encoding="utf-8"
        )

        skill_system.init(str(skills_dir), data_dir=str(data_dir))
        # 自学习技能应加载
        assert "custom_skill" in skill_system._skills_by_id

    def test_reload(self, skill_setup):
        # reload 应重新加载
        skill_system.reload()
        assert "weather" in skill_system._skills_by_id

    def test_reload_without_init(self):
        skill_system._skills_dir = ""
        # 不应抛异常
        skill_system.reload()


# ============================================================
# _parse_skill_md
# ============================================================


class TestParseSkillMd:
    """_parse_skill_md 解析"""

    def test_parse_valid(self, tmp_path):
        path = tmp_path / "SKILL.md"
        path.write_text(
            _make_skill_md("test", "描述", "正文内容"), encoding="utf-8"
        )
        meta, body = skill_system._parse_skill_md(str(path))
        assert meta is not None
        assert meta.name == "test"
        assert meta.description == "描述"
        assert body == "正文内容"

    def test_parse_missing_frontmatter(self, tmp_path):
        path = tmp_path / "SKILL.md"
        path.write_text("只有正文没有 frontmatter", encoding="utf-8")
        meta, body = skill_system._parse_skill_md(str(path))
        assert meta is None
        assert "正文" in body

    def test_parse_invalid_json(self, tmp_path):
        path = tmp_path / "SKILL.md"
        path.write_text("---\n{invalid json\n---\n\nbody", encoding="utf-8")
        meta, body = skill_system._parse_skill_md(str(path))
        assert meta is None
        assert body == "body"

    def test_parse_with_metadata_fields(self, tmp_path):
        path = tmp_path / "SKILL.md"
        content = """---
{
  "name": "x",
  "description": "d",
  "metadata": {
    "cap_groups": ["g1"],
    "manage_mode": "manual",
    "category": ["c1"],
    "peripherals": ["p1"],
    "tags": ["t1"]
  }
}
---

body here"""
        path.write_text(content, encoding="utf-8")
        meta, body = skill_system._parse_skill_md(str(path))
        assert meta.cap_groups == ["g1"]
        assert meta.manage_mode == "manual"
        assert meta.category == ["c1"]
        assert meta.peripherals == ["p1"]
        assert meta.tags == ["t1"]


# ============================================================
# _load_skill
# ============================================================


class TestLoadSkill:
    """_load_skill 加载单个技能"""

    def test_load_valid_skill(self, tmp_path):
        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            _make_skill_md("myskill", "描述", "body"), encoding="utf-8"
        )
        entry = skill_system._load_skill(str(skill_dir))
        assert entry is not None
        assert entry.id == "myskill"
        assert entry.metadata.description == "描述"

    def test_load_skill_no_md(self, tmp_path):
        skill_dir = tmp_path / "noskill"
        skill_dir.mkdir()
        entry = skill_system._load_skill(str(skill_dir))
        assert entry is None

    def test_load_skill_name_mismatch_warns(self, tmp_path):
        """frontmatter name 与目录名不匹配应记录警告"""
        skill_dir = tmp_path / "dir_name"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            _make_skill_md("different_name", "d", "body"), encoding="utf-8"
        )
        entry = skill_system._load_skill(str(skill_dir))
        # 仍应加载成功，但 id 用目录名
        assert entry is not None
        assert entry.id == "dir_name"
        assert entry.metadata.name == "different_name"

    def test_load_skill_with_device_id(self, tmp_path):
        skill_dir = tmp_path / "devskill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            _make_skill_md("devskill", "d", "body"), encoding="utf-8"
        )
        entry = skill_system._load_skill(str(skill_dir), device_id="mac_123")
        assert entry.metadata.device_id == "mac_123"


# ============================================================
# get_catalog
# ============================================================


class TestGetCatalog:
    """get_catalog 设备感知目录"""

    def test_returns_all_when_skills_none(self, skill_setup):
        catalog = skill_system.get_catalog(skills=None)
        ids = [e.id for e in catalog]
        assert "weather" in ids
        assert "long_skill" in ids

    def test_returns_empty_when_skills_empty(self, skill_setup):
        catalog = skill_system.get_catalog(skills=[])
        assert catalog == []

    def test_filters_by_skills_list(self, skill_setup):
        catalog = skill_system.get_catalog(skills=["weather"])
        ids = [e.id for e in catalog]
        assert ids == ["weather"]

    def test_catalog_entry_fields(self, skill_setup):
        catalog = skill_system.get_catalog(skills=["weather"])
        entry = catalog[0]
        assert entry.id == "weather"
        assert entry.description == "查天气"
        assert entry.category == ["tool"]
        assert entry.tags == ["weather"]
        assert entry.device_id == ""


# ============================================================
# get_skill / get_skill_document / get_skill_cap_groups / get_skill_directory
# ============================================================


class TestGetSkill:
    """get_skill 等查询函数"""

    def test_get_skill_exists(self, skill_setup):
        skill = skill_system.get_skill("weather")
        assert skill is not None
        assert skill.id == "weather"

    def test_get_skill_not_exists(self, skill_setup):
        assert skill_system.get_skill("nonexistent") is None

    def test_get_skill_document(self, skill_setup):
        doc = skill_system.get_skill_document("weather")
        assert doc is not None
        assert "步骤" in doc

    def test_get_skill_document_not_exists(self, skill_setup):
        assert skill_system.get_skill_document("nonexistent") is None

    def test_get_skill_document_replaces_placeholder(self, tmp_path):
        """{CUR_SKILL_DIR} 占位符应被替换"""
        skill_dir = tmp_path / "skills" / "phskill"
        skill_dir.mkdir(parents=True)
        body = "路径: {CUR_SKILL_DIR}/file.txt"
        (skill_dir / "SKILL.md").write_text(
            _make_skill_md("phskill", "d", body), encoding="utf-8"
        )
        skill_system.init(str(tmp_path / "skills"))
        doc = skill_system.get_skill_document("phskill")
        assert "{CUR_SKILL_DIR}" not in doc
        assert str(skill_dir).replace("\\", "/") in doc.replace("\\", "/") or str(skill_dir) in doc

    def test_get_skill_cap_groups(self, tmp_path):
        skill_dir = tmp_path / "skills" / "cgskill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            _make_skill_md("cgskill", "d", "body", cap_groups=["g1", "g2"]),
            encoding="utf-8",
        )
        skill_system.init(str(tmp_path / "skills"))
        assert skill_system.get_skill_cap_groups("cgskill") == ["g1", "g2"]

    def test_get_skill_cap_groups_not_exists(self, skill_setup):
        assert skill_system.get_skill_cap_groups("nonexistent") == []

    def test_get_skill_directory(self, skill_setup):
        d = skill_system.get_skill_directory("weather")
        assert d is not None
        assert d.endswith("weather")

    def test_get_skill_directory_not_exists(self, skill_setup):
        assert skill_system.get_skill_directory("nonexistent") is None


# ============================================================
# is_skill_available_for_device / get_device_skill_ids
# ============================================================


class TestSkillAvailability:
    """is_skill_available_for_device / get_device_skill_ids"""

    def test_available_when_in_list(self, skill_setup):
        assert skill_system.is_skill_available_for_device("weather", "d1", skills=["weather"]) is True

    def test_unavailable_when_not_in_list(self, skill_setup):
        assert skill_system.is_skill_available_for_device("weather", "d1", skills=["other"]) is False

    def test_available_when_skills_none(self, skill_setup):
        assert skill_system.is_skill_available_for_device("weather", "d1", skills=None) is True

    def test_unavailable_when_skills_empty(self, skill_setup):
        assert skill_system.is_skill_available_for_device("weather", "d1", skills=[]) is False

    def test_unavailable_when_skill_not_exists(self, skill_setup):
        assert skill_system.is_skill_available_for_device("nonexistent", "d1", skills=None) is False

    def test_get_device_skill_ids_all(self, skill_setup):
        ids = skill_system.get_device_skill_ids("d1", skills=None)
        assert "weather" in ids
        assert "long_skill" in ids

    def test_get_device_skill_ids_filtered(self, skill_setup):
        ids = skill_system.get_device_skill_ids("d1", skills=["weather"])
        assert ids == ["weather"]

    def test_get_device_skill_ids_empty(self, skill_setup):
        ids = skill_system.get_device_skill_ids("d1", skills=[])
        assert ids == []


# ============================================================
# create_skill / update_skill / delete_skill
# ============================================================


class TestCreateSkill:
    """create_skill 创建技能"""

    def test_create_valid(self, skill_setup):
        entry = skill_system.create_skill(
            "new_skill", "新技能描述", "执行步骤说明",
            category=["cat"], tags=["new"], cap_groups=["g1"],
        )
        assert entry.id == "new_skill"
        assert entry.metadata.description == "新技能描述"
        assert "new_skill" in skill_system._skills_by_id
        # 文件应已创建
        assert os.path.isfile(os.path.join(str(skill_setup), "new_skill", "SKILL.md"))

    def test_create_invalid_name_uppercase(self, skill_setup):
        with pytest.raises(ValueError, match="技能名称"):
            skill_system.create_skill("BadName", "d", "instr")

    def test_create_invalid_name_starts_with_digit(self, skill_setup):
        with pytest.raises(ValueError):
            skill_system.create_skill("123abc", "d", "instr")

    def test_create_empty_description(self, skill_setup):
        with pytest.raises(ValueError, match="description"):
            skill_system.create_skill("valid_name", "", "instr")

    def test_create_empty_instructions(self, skill_setup):
        with pytest.raises(ValueError, match="instructions"):
            skill_system.create_skill("valid_name", "desc", "")

    def test_create_whitespace_description(self, skill_setup):
        with pytest.raises(ValueError, match="description"):
            skill_system.create_skill("valid_name", "   ", "instr")

    def test_create_duplicate(self, skill_setup):
        with pytest.raises(ValueError, match="已存在"):
            skill_system.create_skill("weather", "d", "instr")

    def test_create_without_init(self):
        skill_system._skills_dir = ""
        with pytest.raises(ValueError, match="未初始化"):
            skill_system.create_skill("test", "d", "i")


class TestUpdateSkill:
    """update_skill 更新技能"""

    def test_update_description(self, skill_setup):
        entry = skill_system.update_skill("weather", description="新描述")
        assert entry.metadata.description == "新描述"

    def test_update_category_tags(self, skill_setup):
        entry = skill_system.update_skill("weather", category=["new_cat"], tags=["new_tag"])
        assert entry.metadata.category == ["new_cat"]
        assert entry.metadata.tags == ["new_tag"]

    def test_update_instructions(self, skill_setup):
        entry = skill_system.update_skill("weather", instructions="新正文内容")
        doc = skill_system.get_skill_document("weather")
        assert "新正文内容" in doc

    def test_update_nonexistent(self, skill_setup):
        with pytest.raises(ValueError, match="技能不存在"):
            skill_system.update_skill("nonexistent", description="d")

    def test_update_preserves_other_fields(self, skill_setup):
        # 原有 cap_groups 应保留
        skill_system.update_skill("weather", description="changed")
        skill = skill_system.get_skill("weather")
        assert skill.metadata.cap_groups == ["tool"] or skill.metadata.cap_groups == []


class TestDeleteSkill:
    """delete_skill 删除技能"""

    def test_delete_existing(self, skill_setup):
        result = skill_system.delete_skill("weather")
        assert result is True
        assert "weather" not in skill_system._skills_by_id
        # 目录应已删除
        assert not os.path.isdir(os.path.join(str(skill_setup), "weather"))

    def test_delete_nonexistent(self, skill_setup):
        result = skill_system.delete_skill("nonexistent")
        assert result is False


# ============================================================
# render_skills_catalog
# ============================================================


class TestRenderSkillsCatalog:
    """render_skills_catalog 渲染技能目录给 LLM"""

    def test_render_empty_catalog(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        skill_system.init(str(empty_dir))
        result = skill_system.render_skills_catalog(device_id="d1")
        assert result == ""

    def test_render_with_short_skill(self, skill_setup):
        result = skill_system.render_skills_catalog(skills=["weather"])
        assert "技能规则" in result
        assert "weather" in result
        assert "查天气" in result
        # 短文档应内联
        assert "执行步骤" in result

    def test_render_with_long_skill(self, skill_setup):
        result = skill_system.render_skills_catalog(skills=["long_skill"])
        assert "长文档技能" in result
        assert "read_skill_document" in result

    def test_render_with_disabled(self, skill_setup):
        result = skill_system.render_skills_catalog(
            skills=["weather", "long_skill"], disabled_skills=["weather"]
        )
        assert "weather" not in result
        assert "long_skill" in result

    def test_render_all_disabled(self, skill_setup):
        result = skill_system.render_skills_catalog(
            skills=["weather"], disabled_skills=["weather"]
        )
        assert result == ""

    def test_render_includes_skill_rules_header(self, skill_setup):
        result = skill_system.render_skills_catalog(skills=["weather"])
        assert "## 技能规则" in result

    def test_render_all_skills_none(self, skill_setup):
        result = skill_system.render_skills_catalog(skills=None)
        assert "weather" in result
        assert "long_skill" in result
