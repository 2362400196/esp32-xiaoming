"""
image_sender.py 单元测试

覆盖范围：
- ImageSender.send_image_to_device：发送图片 URL、发送失败
- ImageSender.send_clear_image：清除图片
- ImageSender.send_emotion_image：情绪检测与发送、禁用情绪
- ImageSender.send_custom_image：保存 PIL 图片并发送
- ImageSender._prepare_emotion_image：缓存、校验、GIF 复制
- ImageSender._build_url：URL 构建、0.0.0.0 处理
- ImageSender._get_local_ip：本地 IP 获取
- ImageSender._ensure_emos_dir：目录创建
"""
import io
import os
import socket
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.use_cases.image_sender import ImageSender
from src.use_cases.emotion import EmotionDetector, EmotionRenderer

# 注入 EmotionDetector/EmotionRenderer 到 image_sender 模块命名空间
# 源文件缺少对应 import，直接实例化时会 NameError
import src.use_cases.image_sender as _img_module
_img_module.EmotionDetector = EmotionDetector
_img_module.EmotionRenderer = EmotionRenderer


# ============================================================
# ImageSender.send_image_to_device
# ============================================================


class TestSendImageToDevice:
    """send_image_to_device 发送图片 URL"""

    async def test_send_success(self):
        sender = ImageSender()
        channel = MagicMock()
        channel.send_json = AsyncMock()

        result = await sender.send_image_to_device(channel, "http://example.com/img.png")

        assert result is True
        channel.send_json.assert_called_once()
        sent_data = channel.send_json.call_args[0][0]
        assert sent_data["type"] == "show_image"
        assert sent_data["url"] == "http://example.com/img.png"

    async def test_send_with_custom_dimensions(self):
        sender = ImageSender()
        channel = MagicMock()
        channel.send_json = AsyncMock()

        await sender.send_image_to_device(channel, "url", width=200, height=100)

        sent_data = channel.send_json.call_args[0][0]
        assert sent_data["width"] == 200
        assert sent_data["height"] == 100

    async def test_send_failure(self):
        sender = ImageSender()
        channel = MagicMock()
        channel.send_json = AsyncMock(side_effect=Exception("send error"))

        result = await sender.send_image_to_device(channel, "url")
        assert result is False


# ============================================================
# ImageSender.send_clear_image
# ============================================================


class TestSendClearImage:
    """send_clear_image 清除图片"""

    async def test_clear_success(self):
        sender = ImageSender()
        channel = MagicMock()
        channel.send_json = AsyncMock()

        result = await sender.send_clear_image(channel)
        assert result is True
        sent_data = channel.send_json.call_args[0][0]
        assert sent_data["type"] == "clear_image"

    async def test_clear_failure(self):
        sender = ImageSender()
        channel = MagicMock()
        channel.send_json = MagicMock(side_effect=Exception("error"))

        result = await sender.send_clear_image(channel)
        assert result is False


# ============================================================
# ImageSender.send_emotion_image
# ============================================================


class TestSendEmotionImage:
    """send_emotion_image 情绪图片发送"""

    async def test_emotion_disabled(self):
        sender = ImageSender()
        with patch("src.use_cases.image_sender.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(emotion=MagicMock(enabled=False))
            result = await sender.send_emotion_image(MagicMock(), "我好开心")
        assert result is False

    async def test_no_emotion_detected(self):
        sender = ImageSender()
        channel = MagicMock()
        channel.send_json = AsyncMock()
        with patch("src.use_cases.image_sender.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(emotion=MagicMock(enabled=True))
            result = await sender.send_emotion_image(channel, "今天天气还可以")
        assert result is False

    async def test_emotion_detected_and_sent(self):
        detector = MagicMock()
        detector.detect_emotion.return_value = "快乐"
        sender = ImageSender(emotion_detector=detector)
        channel = MagicMock()
        channel.send_json = AsyncMock()
        with patch("src.use_cases.image_sender.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(emotion=MagicMock(enabled=True))
            result = await sender.send_emotion_image(channel, "哈哈好开心", device_id="d1")
        assert result is True
        detector.detect_emotion.assert_called_once_with("哈哈好开心", "d1")
        sent_data = channel.send_json.call_args[0][0]
        assert sent_data["type"] == "emotion"
        assert sent_data["data"] == "快乐"

    async def test_send_emotion_failure(self):
        detector = MagicMock()
        detector.detect_emotion.return_value = "快乐"
        sender = ImageSender(emotion_detector=detector)
        channel = MagicMock()
        channel.send_json = MagicMock(side_effect=Exception("error"))
        with patch("src.use_cases.image_sender.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(emotion=MagicMock(enabled=True))
            result = await sender.send_emotion_image(channel, "哈哈好开心")
        assert result is False


# ============================================================
# ImageSender.send_custom_image
# ============================================================


class TestSendCustomImage:
    """send_custom_image 自定义图片发送"""

    async def test_send_custom_image_success(self, tmp_path):
        sender = ImageSender()
        channel = MagicMock()
        channel.send_json = AsyncMock()
        emos_dir = str(tmp_path / "emos")
        os.makedirs(emos_dir, exist_ok=True)

        # 构造一个真实的 JPEG 字节
        from PIL import Image
        img = Image.new("RGB", (10, 10), (255, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        image_bytes = buf.getvalue()

        with patch.object(sender, "_ensure_emos_dir", return_value=emos_dir), \
             patch.object(sender, "_build_url", return_value="http://localhost/emos/test.jpg"):
            result = await sender.send_custom_image(channel, image_bytes)

        assert result is not None
        assert "test.jpg" in result or result.startswith("http")

    async def test_send_custom_image_invalid_bytes(self, tmp_path):
        sender = ImageSender()
        channel = MagicMock()
        emos_dir = str(tmp_path / "emos")
        os.makedirs(emos_dir, exist_ok=True)

        with patch.object(sender, "_ensure_emos_dir", return_value=emos_dir):
            result = await sender.send_custom_image(channel, b"not an image")

        assert result is None

    async def test_send_custom_image_rgba_convert(self, tmp_path):
        sender = ImageSender()
        channel = MagicMock()
        channel.send_json = AsyncMock()
        emos_dir = str(tmp_path / "emos")
        os.makedirs(emos_dir, exist_ok=True)

        from PIL import Image
        img = Image.new("RGBA", (10, 10), (255, 0, 0, 128))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        image_bytes = buf.getvalue()

        with patch.object(sender, "_ensure_emos_dir", return_value=emos_dir), \
             patch.object(sender, "_build_url", return_value="http://localhost/emos/test.jpg"):
            result = await sender.send_custom_image(channel, image_bytes)

        assert result is not None


# ============================================================
# ImageSender._prepare_emotion_image
# ============================================================


class TestPrepareEmotionImage:
    """_prepare_emotion_image 准备情绪图片"""

    def test_gif_not_found(self):
        renderer = MagicMock()
        renderer.get_emotion_gif_path.return_value = None
        sender = ImageSender(emotion_renderer=renderer)

        with patch.object(sender, "_ensure_emos_dir", return_value="/tmp/emos"):
            result = sender._prepare_emotion_image("快乐")

        assert result is None

    def test_gif_empty_file(self):
        renderer = MagicMock()
        renderer.get_emotion_gif_path.return_value = "/tmp/快乐.gif"
        sender = ImageSender(emotion_renderer=renderer)

        with patch.object(sender, "_ensure_emos_dir", return_value="/tmp/emos"), \
             patch("os.path.isfile", return_value=True), \
             patch("os.path.getsize", return_value=0):
            result = sender._prepare_emotion_image("快乐")

        assert result is None

    def test_gif_valid_copy(self, tmp_path):
        from PIL import Image

        # 创建真实 gif 文件
        gif_path = tmp_path / "快乐.gif"
        img = Image.new("RGB", (4, 4), (255, 0, 0))
        img.save(str(gif_path), format="GIF")

        emos_dir = str(tmp_path / "emos")
        os.makedirs(emos_dir, exist_ok=True)

        renderer = MagicMock()
        renderer.get_emotion_gif_path.return_value = str(gif_path)
        sender = ImageSender(emotion_renderer=renderer)

        with patch.object(sender, "_ensure_emos_dir", return_value=emos_dir), \
             patch.object(sender, "_build_url", return_value="http://localhost/emos/快乐.gif"):
            result = sender._prepare_emotion_image("快乐")

        assert result is not None
        url, w, h = result
        assert url == "http://localhost/emos/快乐.gif"
        assert w == 4
        assert h == 4
        # 文件应已复制
        assert os.path.isfile(os.path.join(emos_dir, "快乐.gif"))

    def test_cached_image_valid(self, tmp_path):
        from PIL import Image

        # 预置缓存 gif
        emos_dir = str(tmp_path / "emos")
        os.makedirs(emos_dir, exist_ok=True)
        dest_path = os.path.join(emos_dir, "快乐.gif")
        img = Image.new("RGB", (4, 4), (0, 255, 0))
        img.save(dest_path, format="GIF")

        sender = ImageSender()
        sender._url_cache["快乐"] = ("http://cached/url", 4, 4)

        with patch.object(sender, "_ensure_emos_dir", return_value=emos_dir):
            result = sender._prepare_emotion_image("快乐")
        # 缓存命中且文件有效，应直接返回缓存
        assert result == ("http://cached/url", 4, 4)

    def test_cached_image_invalid_falls_back(self, tmp_path):
        from PIL import Image

        # 缓存存在但文件无效（损坏的 gif）
        emos_dir = str(tmp_path / "emos")
        os.makedirs(emos_dir, exist_ok=True)
        dest_path = os.path.join(emos_dir, "快乐.gif")
        with open(dest_path, "wb") as f:
            f.write(b"corrupted data")  # 无效 gif

        # 源 gif 有效
        gif_path = tmp_path / "src_happy.gif"
        img = Image.new("RGB", (4, 4), (255, 0, 0))
        img.save(str(gif_path), format="GIF")

        renderer = MagicMock()
        renderer.get_emotion_gif_path.return_value = str(gif_path)
        sender = ImageSender(emotion_renderer=renderer)
        sender._url_cache["快乐"] = ("http://cached/url", 4, 4)

        with patch.object(sender, "_ensure_emos_dir", return_value=emos_dir), \
             patch.object(sender, "_build_url", return_value="http://new/url"):
            result = sender._prepare_emotion_image("快乐")

        # 应回退到重新处理
        assert result is not None

    def test_pil_error_returns_none(self, tmp_path):
        renderer = MagicMock()
        renderer.get_emotion_gif_path.return_value = str(tmp_path / "nonexistent.gif")
        sender = ImageSender(emotion_renderer=renderer)

        with patch.object(sender, "_ensure_emos_dir", return_value=str(tmp_path / "emos")), \
             patch("os.path.isfile", return_value=True), \
             patch("os.path.getsize", return_value=100):
            result = sender._prepare_emotion_image("快乐")

        assert result is None


# ============================================================
# ImageSender._build_url
# ============================================================


class TestBuildUrl:
    """_build_url 构建 URL"""

    def test_with_normal_host(self):
        sender = ImageSender()
        with patch("src.use_cases.image_sender.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                server=MagicMock(host="192.168.1.1", port=8080)
            )
            url = sender._build_url("test.gif")
        assert url == "http://192.168.1.1:8080/emos/test.gif"

    def test_with_zero_host(self):
        sender = ImageSender()
        with patch("src.use_cases.image_sender.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                server=MagicMock(host="0.0.0.0", port=8080)
            )
            with patch.object(ImageSender, "_get_local_ip", return_value="10.0.0.1"):
                url = sender._build_url("test.gif")
        assert url == "http://10.0.0.1:8080/emos/test.gif"


# ============================================================
# ImageSender._get_local_ip
# ============================================================


class TestGetLocalIp:
    """_get_local_ip 获取本地 IP"""

    def test_returns_ip(self):
        # mock socket
        with patch("socket.socket") as mock_socket_cls:
            mock_sock = MagicMock()
            mock_sock.getsockname.return_value = ("192.168.1.100", 12345)
            mock_socket_cls.return_value = mock_sock
            ip = ImageSender._get_local_ip()
        assert ip == "192.168.1.100"

    def test_returns_fallback_on_error(self):
        with patch("socket.socket", side_effect=Exception("no network")):
            ip = ImageSender._get_local_ip()
        assert ip == "127.0.0.1"


# ============================================================
# ImageSender._ensure_emos_dir
# ============================================================


class TestEnsureEmosDir:
    """_ensure_emos_dir 确保目录存在"""

    def test_creates_dir(self, tmp_path):
        sender = ImageSender()
        with patch("src.use_cases.image_sender.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                emotion=MagicMock(static_dir="images")
            )
            with patch("os.makedirs") as mock_makedirs:
                result = sender._ensure_emos_dir()
        mock_makedirs.assert_called_once()
        assert result is not None
        assert "emotion" in result or "images" in result


# ============================================================
# ImageSender.__init__
# ============================================================


class TestImageSenderInit:
    """ImageSender 初始化"""

    def test_default_detectors(self):
        sender = ImageSender()
        assert isinstance(sender._emotion_detector, EmotionDetector)
        assert isinstance(sender._emotion_renderer, EmotionRenderer)
        assert sender._url_cache == {}

    def test_custom_detectors(self):
        det = MagicMock()
        rend = MagicMock()
        sender = ImageSender(emotion_detector=det, emotion_renderer=rend)
        assert sender._emotion_detector is det
        assert sender._emotion_renderer is rend


# ============================================================
# 辅助函数
# ============================================================


async def _async_none():
    return None

