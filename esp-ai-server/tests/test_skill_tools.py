"""
skill_tools.py 单元测试

覆盖范围：
- list_skills：列出设备可用技能、过滤禁用、空目录
- read_skill_document：读取技能文档、禁用检测、不存在时返回可用列表
"""
from unittest.mock import MagicMock, patch

import pytest

from src.use_cases import skill_system
from src.use_cases.skill_tools import list_skills, read_skill_document


# 辅助：构造 SkillCatalogEntry
def _make_catalog_entry(eid="skill_a", desc="测试技能", tags=None, device_id=""):
    from src.use_cases.skill_system import SkillCatalogEntry

    return SkillCatalogEntry(
        id=eid,
        description=desc,
        category=["test"],
        tags=tags or [],
        device_id=device_id,
    )


# 辅助：构造 SkillEntry（含完整文档）
def _make_skill_entry(eid="skill_a", desc="测试技能", body="这是技能文档内容。"):
    from src.use_cases.skill_system import SkillEntry, SkillMetadata

    meta = SkillMetadata(name=eid, description=desc, category=["test"], tags=["t1"])
    return SkillEntry(
        id=eid,
        metadata=meta,
        body=body,
        file_path=f"/tmp/{eid}/SKILL.md",
        directory=f"/tmp/{eid}",
    )


# ============================================================
# list_skills
# ============================================================


class TestListSkills:
    """list_skills 工具函数"""

    def test_empty_catalog(self):
        """无可用技能时返回提示"""
        tm = MagicMock()
        tm.device_id = ""
        tm.user_config = None

        with patch.object(skill_system, "get_catalog", return_value=[]):
            result = list_skills(tool_manager=tm)

        assert "当前没有可用的技能" in result

    def test_list_with_entries(self):
        """列出技能包含 id 与描述"""
        tm = MagicMock()
        tm.device_id = ""
        tm.user_config = None

        entries = [
            _make_catalog_entry("weather", "查天气"),
            _make_catalog_entry("light", "控制灯"),
        ]
        with patch.object(skill_system, "get_catalog", return_value=entries):
            result = list_skills(tool_manager=tm)

        assert "weather" in result
        assert "查天气" in result
        assert "light" in result
        assert "控制灯" in result

    def test_list_includes_tags(self):
        """技能带 tags 时显示标签"""
        tm = MagicMock()
        tm.device_id = ""
        tm.user_config = None

        entry = _make_catalog_entry("skill_a", "desc", tags=["home", "iot"])
        with patch.object(skill_system, "get_catalog", return_value=[entry]):
            result = list_skills(tool_manager=tm)

        assert "home" in result
        assert "iot" in result

    def test_list_device_specific_badge(self):
        """设备专属技能显示 [设备专属] 标记"""
        tm = MagicMock()
        tm.device_id = "d1"
        tm.user_config = None

        entry = _make_catalog_entry("skill_a", "desc", device_id="d1")
        with patch.object(skill_system, "get_catalog", return_value=[entry]):
            result = list_skills(tool_manager=tm)

        assert "设备专属" in result

    def test_list_filters_disabled_skills(self):
        """禁用的技能被过滤"""
        tm = MagicMock()
        tm.device_id = ""
        uc = MagicMock()
        uc.disabled_skills = ["skill_b"]
        tm.user_config = uc

        entries = [
            _make_catalog_entry("skill_a", "可用"),
            _make_catalog_entry("skill_b", "被禁用"),
        ]
        with patch.object(skill_system, "get_catalog", return_value=entries):
            result = list_skills(tool_manager=tm)

        assert "skill_a" in result
        assert "skill_b" not in result

    def test_list_with_none_tool_manager(self):
        """tool_manager 为 None 时仍能调用"""
        with patch.object(skill_system, "get_catalog", return_value=[]):
            result = list_skills(tool_manager=None)
        assert "当前没有可用的技能" in result

    def test_list_uses_device_key_from_tool_manager(self):
        """调用 get_catalog 时传入 device_key（来自 tool_manager.user_config.key）"""
        tm = MagicMock()
        uc = MagicMock()
        uc.key = "dev_123"
        uc.disabled_skills = None
        tm.user_config = uc

        with patch.object(skill_system, "get_catalog", return_value=[]) as mock_get:
            list_skills(tool_manager=tm)

        mock_get.assert_called_once_with(device_id="dev_123")

    def test_list_no_disabled_when_user_config_none(self):
        """user_config 为 None 时不报错"""
        tm = MagicMock()
        tm.device_id = ""
        tm.user_config = None

        entry = _make_catalog_entry("skill_a", "desc")
        with patch.object(skill_system, "get_catalog", return_value=[entry]):
            result = list_skills(tool_manager=tm)
        assert "skill_a" in result

    def test_list_hint_includes_read_skill_document(self):
        """结果中包含使用 read_skill_document 的提示"""
        tm = MagicMock()
        tm.device_id = ""
        tm.user_config = None

        with patch.object(skill_system, "get_catalog", return_value=[_make_catalog_entry()]):
            result = list_skills(tool_manager=tm)
        assert "read_skill_document" in result


# ============================================================
# read_skill_document
# ============================================================


class TestReadSkillDocument:
    """read_skill_document 工具函数"""

    def test_read_existing_skill(self):
        """读取存在的技能文档"""
        tm = MagicMock()
        tm.user_config = None

        with patch.object(skill_system, "get_skill_document", return_value="技能详细说明"):
            result = read_skill_document("skill_a", tool_manager=tm)

        assert result == "技能详细说明"

    def test_read_nonexistent_skill(self):
        """读取不存在的技能时返回可用列表提示"""
        tm = MagicMock()
        tm.device_id = "d1"
        tm.user_config = None

        entries = [_make_catalog_entry("skill_a", "desc")]
        with patch.object(skill_system, "get_skill_document", return_value=None), \
             patch.object(skill_system, "get_catalog", return_value=entries):
            result = read_skill_document("nonexistent", tool_manager=tm)

        assert "不存在" in result
        assert "skill_a" in result

    def test_read_disabled_skill(self):
        """被禁用的技能返回禁用提示"""
        tm = MagicMock()
        uc = MagicMock()
        uc.disabled_skills = ["skill_a"]
        tm.user_config = uc

        result = read_skill_document("skill_a", tool_manager=tm)
        assert "已被禁用" in result

    def test_read_with_none_tool_manager(self):
        """tool_manager 为 None 时仍能调用"""
        with patch.object(skill_system, "get_skill_document", return_value="doc"):
            result = read_skill_document("skill_a", tool_manager=None)
        assert result == "doc"

    def test_read_nonexistent_no_tool_manager(self):
        """tool_manager 为 None 且技能不存在"""
        entries = [_make_catalog_entry("skill_a", "desc")]
        with patch.object(skill_system, "get_skill_document", return_value=None), \
             patch.object(skill_system, "get_catalog", return_value=entries):
            result = read_skill_document("missing", tool_manager=None)
        assert "不存在" in result

    def test_read_skill_document_replaces_cur_skill_dir(self):
        """文档中的 {CUR_SKILL_DIR} 占位符已被替换（get_skill_document 内部处理）"""
        tm = MagicMock()
        tm.user_config = None

        doc = "路径: /tmp/skill_a"
        with patch.object(skill_system, "get_skill_document", return_value=doc):
            result = read_skill_document("skill_a", tool_manager=tm)
        assert "/tmp/skill_a" in result

    def test_read_disabled_takes_precedence_over_existence(self):
        """禁用检查优先于文档读取"""
        tm = MagicMock()
        uc = MagicMock()
        uc.disabled_skills = ["skill_a"]
        tm.user_config = uc

        # 即使文档存在，禁用检查应先返回
        with patch.object(skill_system, "get_skill_document", return_value="should_not_return"):
            result = read_skill_document("skill_a", tool_manager=tm)
        assert "已被禁用" in result
        assert "should_not_return" not in result
