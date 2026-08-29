"""市场插件 zip 安全测试

覆盖：
- zip 解压炸弹防护（单文件/累计解压后大小限额，skills 的 SKILL.md 同样受限）
- 插件图标存储安全（扩展名白名单 + magic bytes 校验，拒绝 svg/html）
"""
from __future__ import annotations

import asyncio
import io
import zipfile

import pytest

from src.infrastructure.routes.marketplace import (
    MAX_ZIP_MEMBER_SIZE,
    MAX_ZIP_TOTAL_UNCOMPRESSED,
    _read_manifest_from_zip,
    _read_source_from_zip,
    create_zip_read_state,
    read_zip_member_checked,
)
from src.infrastructure.routes.skills import _extract_skill_from_upload
from src.infrastructure import marketplace_storage


def _make_zip(files: dict[str, bytes]) -> bytes:
    """构建内存 zip 包。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


_MANIFEST = b'{"id": "demo", "name": "demo", "version": "1.0.0"}'


class TestZipBombProtection:
    """zip 解压炸弹防护"""

    def test_single_member_over_limit(self):
        """单成员解压后超过 5MB 拒绝读取"""
        big = b"\x00" * (MAX_ZIP_MEMBER_SIZE + 1)  # 压缩后极小，解压后超限
        data = _make_zip({"big.bin": big})
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            with pytest.raises(ValueError):
                read_zip_member_checked(zf, "big.bin", create_zip_read_state())

    def test_source_read_rejects_oversized_member(self):
        """_read_source_from_zip 对超限成员抛 ValueError"""
        big = b"\x00" * (MAX_ZIP_MEMBER_SIZE + 1)
        data = _make_zip({"manifest.json": _MANIFEST, "plugin.py": b"x = 1", "big.bin": big})
        with pytest.raises(ValueError):
            _read_source_from_zip(data)

    def test_total_uncompressed_over_limit(self):
        """多个合法成员累计解压后超过 20MB 拒绝"""
        chunk = b"\x00" * (4 * 1024 * 1024)  # 5 个 4MB（各低于单文件上限），累计 20MB+
        files = {f"part{i}.bin": chunk for i in range(5)}
        files["manifest.json"] = _MANIFEST
        files["plugin.py"] = b"x = 1"
        data = _make_zip(files)
        with pytest.raises(ValueError):
            _read_source_from_zip(data)

    def test_manifest_read_within_limit_ok(self):
        """正常大小的 zip 可读取 manifest"""
        data = _make_zip({"manifest.json": _MANIFEST, "plugin.py": b"x = 1"})
        manifest, names = _read_manifest_from_zip(data)
        assert manifest["id"] == "demo"
        assert "plugin.py" in names


class TestSkillZipLimit:
    """技能上传 zip 同样受限"""

    def test_skill_md_over_limit(self):
        """SKILL.md 解压后超过 5MB 抛 ValueError"""
        big = b"# skill\n" + b"\x00" * (MAX_ZIP_MEMBER_SIZE + 1)
        data = _make_zip({"SKILL.md": big})
        with pytest.raises(ValueError):
            _extract_skill_from_upload(data, "skill.zip")


class TestSaveIconValidation:
    """图标保存：扩展名白名单 + magic bytes 校验"""

    @pytest.fixture(autouse=True)
    def _tmp_storage(self, tmp_path, monkeypatch):
        # 重定向存储目录到临时路径，避免污染 data/
        monkeypatch.setattr(marketplace_storage, "MARKETPLACE_STORAGE_DIR", tmp_path)
        yield

    def _save(self, content: bytes, name: str, slug: str = "ticon") -> str:
        return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            marketplace_storage.save_icon(content, slug, name)
        )

    def test_reject_svg(self):
        """svg 图标（可携带 script）被拒绝"""
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        with pytest.raises(ValueError):
            self._save(svg, "icon.svg")

    def test_reject_html_ext(self):
        """html 扩展名被拒绝"""
        with pytest.raises(ValueError):
            self._save(b"<html><script>x</script></html>", "icon.html")

    def test_reject_magic_mismatch(self):
        """扩展名为 png 但内容非图片（magic 不符）被拒绝"""
        with pytest.raises(ValueError):
            self._save(b"<html><script>x</script></html>", "icon.png")

    def test_accept_valid_png(self, tmp_path):
        """合法 PNG 可保存"""
        # PNG 文件头 magic bytes
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
        name = self._save(png, "icon.png")
        assert name == "icon.png"
        assert (tmp_path / "ticon" / "icon.png").read_bytes() == png
