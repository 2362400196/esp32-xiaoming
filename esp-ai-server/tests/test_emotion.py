"""
emotion.py 单元测试

覆盖范围：
- EmotionDetector：detect_emotion 情绪关键词检测
- EmotionRenderer：get_emotion_gif_path、render_emotion_rgb565_b64、_rgb_to_565
"""
import base64
import io
import os
from unittest.mock import MagicMock, patch

import pytest

from src.use_cases.emotion import EmotionDetector, EmotionRenderer


# ============================================================
# EmotionDetector
# ============================================================


class TestEmotionDetectorDetect:
    """EmotionDetector.detect_emotion 情绪检测"""

    def test_detect_happy(self):
        det = EmotionDetector()
        assert det.detect_emotion("哈哈今天真开心") == "快乐"

    def test_detect_sad(self):
        det = EmotionDetector()
        assert det.detect_emotion("我好难过想哭") == "伤心"

    def test_detect_angry(self):
        det = EmotionDetector()
        assert det.detect_emotion("气死我了讨厌") == "愤怒"

    def test_detect_surprised(self):
        det = EmotionDetector()
        assert det.detect_emotion("真的假的居然这样") == "意外"

    def test_detect_negative(self):
        det = EmotionDetector()
        assert det.detect_emotion("我拒绝否认") == "否定"

    def test_detect_no_emotion_returns_empty(self):
        det = EmotionDetector()
        # 确保文本不含任何情绪关键词
        assert det.detect_emotion("今天天气还可以") == ""

    def test_detect_empty_text(self):
        det = EmotionDetector()
        assert det.detect_emotion("") == ""

    def test_detect_with_device_id(self):
        det = EmotionDetector()
        # device_id 不影响检测结果
        result = det.detect_emotion("哈哈", device_id="d1")
        assert result == "快乐"

    def test_detect_case_insensitive(self):
        # 关键词小写匹配，中文不受影响；英文 nice 应匹配快乐
        det = EmotionDetector()
        assert det.detect_emotion("so nice") == "快乐"

    def test_detect_case_insensitive_upper(self):
        det = EmotionDetector()
        assert det.detect_emotion("NICE GOOD") == "快乐"

    def test_detect_picks_highest_score(self):
        # 多个情绪命中时，按 score（关键词长度之和）取最大
        det = EmotionDetector()
        # "开心" (2) + "棒" (1) = 快乐 3 ; "讨厌" (2) = 愤怒 2
        result = det.detect_emotion("开心棒讨厌")
        assert result == "快乐"

    def test_detect_multiple_keywords_same_emotion_accumulate(self):
        det = EmotionDetector()
        # 快乐: 哈哈(2) + 开心(2) = 4
        result = det.detect_emotion("哈哈开心")
        assert result == "快乐"


# ============================================================
# EmotionRenderer
# ============================================================


class TestEmotionRendererColors:
    """EmotionRenderer 颜色与中文映射常量"""

    def test_emotion_colors_has_all(self):
        for e in ["快乐", "伤心", "愤怒", "意外", "否定", "无情绪"]:
            assert e in EmotionRenderer.EMOTION_COLORS

    def test_emotion_zh_has_all(self):
        for e in ["快乐", "伤心", "愤怒", "意外", "否定", "无情绪"]:
            assert e in EmotionRenderer.EMOTION_ZH

    def test_no_emotion_zh_is_empty(self):
        assert EmotionRenderer.EMOTION_ZH["无情绪"] == ""


class TestRgbTo565:
    """EmotionRenderer._rgb_to_565"""

    def test_basic_white(self):
        # (255,255,255) -> 全 1
        val = EmotionRenderer._rgb_to_565(255, 255, 255)
        assert val == 0xFFFF

    def test_basic_black(self):
        val = EmotionRenderer._rgb_to_565(0, 0, 0)
        assert val == 0x0000

    def test_basic_red(self):
        # r=255: (31<<11)
        val = EmotionRenderer._rgb_to_565(255, 0, 0)
        assert val == (31 << 11)

    def test_basic_green(self):
        val = EmotionRenderer._rgb_to_565(0, 255, 0)
        assert val == (63 << 5)

    def test_basic_blue(self):
        val = EmotionRenderer._rgb_to_565(0, 0, 255)
        assert val == 31


class TestGetEmotionGifPath:
    """EmotionRenderer.get_emotion_gif_path"""

    def test_returns_none_when_file_not_found(self):
        with patch("src.use_cases.emotion.get_settings") as mock_settings:
            settings = MagicMock()
            settings.emotion.gif_dir = "emos"
            mock_settings.return_value = settings
            renderer = EmotionRenderer()
            # 不存在的 gif 应返回 None
            result = renderer.get_emotion_gif_path("快乐")
            assert result is None

    def test_returns_path_when_file_exists(self):
        with patch("src.use_cases.emotion.get_settings") as mock_settings:
            settings = MagicMock()
            settings.emotion.gif_dir = "emos"
            mock_settings.return_value = settings
            renderer = EmotionRenderer()
            # mock os.path.isfile 返回 True
            with patch("os.path.isfile", return_value=True):
                result = renderer.get_emotion_gif_path("快乐")
            assert result is not None
            assert result.endswith("快乐.gif")


class TestRenderEmotionRgb565:
    """EmotionRenderer.render_emotion_rgb565_b64"""

    def test_render_with_valid_gif(self):
        """存在有效 gif 文件时返回 base64 字符串"""
        with patch("src.use_cases.emotion.get_settings") as mock_settings:
            settings = MagicMock()
            settings.emotion.gif_dir = "emos"
            mock_settings.return_value = settings
            renderer = EmotionRenderer()

            # 构造一个真实的小 PIL 图像作为 gif 数据
            from PIL import Image

            img = Image.new("RGB", (4, 4), (255, 0, 0))
            buf = io.BytesIO()
            img.save(buf, format="GIF")
            gif_bytes = buf.getvalue()

            with patch("os.path.isfile", return_value=True), \
                 patch("builtins.open", mock_open_read(gif_bytes)):
                result = renderer.render_emotion_rgb565_b64("快乐", width=4, height=4)

            assert result is not None
            # 应为合法 base64
            decoded = base64.b64decode(result)
            # 4x4x2 = 32 bytes
            assert len(decoded) == 32

    def test_render_fallback_to_solid_color_when_no_gif(self):
        """无 gif 时回退到纯色绘制"""
        with patch("src.use_cases.emotion.get_settings") as mock_settings:
            settings = MagicMock()
            settings.emotion.gif_dir = "emos"
            mock_settings.return_value = settings
            renderer = EmotionRenderer()

            # get_emotion_gif_path 返回 None
            with patch.object(renderer, "get_emotion_gif_path", return_value=None):
                result = renderer.render_emotion_rgb565_b64("快乐", width=4, height=4)

            assert result is not None
            decoded = base64.b64decode(result)
            assert len(decoded) == 32

    def test_render_unknown_emotion_uses_default_color(self):
        """未知情绪使用默认灰色"""
        with patch("src.use_cases.emotion.get_settings") as mock_settings:
            settings = MagicMock()
            settings.emotion.gif_dir = "emos"
            mock_settings.return_value = settings
            renderer = EmotionRenderer()

            with patch.object(renderer, "get_emotion_gif_path", return_value=None):
                result = renderer.render_emotion_rgb565_b64("未知情绪", width=4, height=4)
            assert result is not None

    def test_render_no_emotion_empty_label(self):
        """无情绪标签为空，仍渲染纯色"""
        with patch("src.use_cases.emotion.get_settings") as mock_settings:
            settings = MagicMock()
            settings.emotion.gif_dir = "emos"
            mock_settings.return_value = settings
            renderer = EmotionRenderer()

            with patch.object(renderer, "get_emotion_gif_path", return_value=None):
                result = renderer.render_emotion_rgb565_b64("无情绪", width=4, height=4)
            assert result is not None


class TestRenderEmotionErrorHandling:
    """EmotionRenderer 异常处理"""

    def test_render_returns_none_on_pil_failure(self):
        """PIL 全部失败时返回 None"""
        with patch("src.use_cases.emotion.get_settings") as mock_settings:
            settings = MagicMock()
            settings.emotion.gif_dir = "emos"
            mock_settings.return_value = settings
            renderer = EmotionRenderer()

            # 让 PIL Image.new 抛异常
            with patch.object(renderer, "get_emotion_gif_path", return_value=None), \
                 patch("PIL.Image.new", side_effect=Exception("PIL broken")):
                result = renderer.render_emotion_rgb565_b64("快乐", width=4, height=4)
            assert result is None


# 辅助函数：构造 mock open 返回指定字节
def mock_open_read(data: bytes):
    from unittest.mock import mock_open as _mock_open
    m = _mock_open(read_data=data)
    return m
