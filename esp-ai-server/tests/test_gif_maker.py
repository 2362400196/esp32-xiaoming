"""GIF 制作器接口测试（/api/v1/emos/maker/*）

覆盖：素材解析（帧/缩略图）、多素材合成 GIF、参数校验、错误分支。
"""
from __future__ import annotations

import io
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from unittest.mock import MagicMock

from src.infrastructure.gif_processor import MAX_SOURCES


def _make_gif(frames: int = 3, size: int = 200, duration: int = 100) -> bytes:
    """用 Pillow 生成一个多帧动画 GIF 字节。"""
    imgs = []
    for i in range(frames):
        im = Image.new("RGB", (size, size), (i * 40, 20, 200 - i * 30))
        imgs.append(im)
    buf = io.BytesIO()
    imgs[0].save(
        buf, format="GIF", save_all=True, append_images=imgs[1:],
        duration=duration, loop=0,
    )
    return buf.getvalue()


def _make_png(size: int = 100) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (size, size), (10, 200, 30)).save(buf, format="PNG")
    return buf.getvalue()


class TestGifMakerRoutes:
    """GIF 制作器路由测试"""

    @pytest.fixture
    def app(self):
        from src.infrastructure.routes.emos import router
        from src.infrastructure.security_jwt import get_current_user
        application = FastAPI()
        application.include_router(router)
        # 制作器接口走 JWT 认证；单元测试直接放行
        application.dependency_overrides[get_current_user] = lambda: MagicMock(id="u1")
        return application

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_sources_animated_gif(self, client):
        """解析动画 GIF：帧数、尺寸、缩略图"""
        gif = _make_gif(frames=3, size=200)
        resp = client.post(
            "/api/v1/emos/maker/sources",
            files=[("files", ("a.gif", gif, "image/gif"))],
        )
        body = resp.json()
        assert body["code"] == 0
        sources = body["data"]["sources"]
        assert len(sources) == 1
        s = sources[0]
        assert s["valid"] is True
        assert s["animated"] is True
        assert s["w"] == 200 and s["h"] == 200
        assert len(s["frames"]) == 3
        assert s["frames"][0]["d"] == 100
        assert s["frames"][0]["thumb"].startswith("data:image/png;base64,")

    def test_sources_static_image(self, client):
        """静态图片按单帧处理"""
        png = _make_png()
        resp = client.post(
            "/api/v1/emos/maker/sources",
            files=[("files", ("b.png", png, "image/png"))],
        )
        body = resp.json()
        assert body["code"] == 0
        s = body["data"]["sources"][0]
        assert s["animated"] is False
        assert len(s["frames"]) == 1

    def test_sources_invalid_file(self, client):
        """不可解码的素材返回错误"""
        resp = client.post(
            "/api/v1/emos/maker/sources",
            files=[("files", ("bad.txt", b"not an image", "text/plain"))],
        )
        assert resp.json()["code"] == 1

    def test_sources_no_files(self, client):
        resp = client.post("/api/v1/emos/maker/sources")
        assert resp.status_code == 422

    def test_sources_too_many(self, client):
        """超过素材数量上限"""
        gif = _make_gif(frames=1)
        files = [("files", (f"f{i}.gif", gif, "image/gif")) for i in range(MAX_SOURCES + 1)]
        resp = client.post("/api/v1/emos/maker/sources", files=files)
        assert resp.json()["code"] == 1

    def test_process_merge_and_resize(self, client):
        """合并两个素材并缩放到 240：帧数正确、输出为 GIF"""
        gif_a = _make_gif(frames=3, size=180)
        gif_b = _make_gif(frames=2, size=160)
        params = {
            "frames": [
                {"src": 0, "frame": 0},
                {"src": 0, "frame": 2},
                {"src": 1, "frame": 1},
            ],
            "size": 240,
            "delay": 80,
            "loop": 0,
            "fit": "crop",
        }
        resp = client.post(
            "/api/v1/emos/maker/process",
            files=[
                ("files", ("a.gif", gif_a, "image/gif")),
                ("files", ("b.gif", gif_b, "image/gif")),
            ],
            data={"params": json.dumps(params)},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/gif"
        assert resp.headers["x-gif-frames"] == "3"
        out = Image.open(io.BytesIO(resp.content))
        assert out.format == "GIF"
        assert getattr(out, "n_frames", 1) == 3
        assert out.size == (240, 240)

    def test_process_fit_mode(self, client):
        """fit 模式等比适配（不裁剪）"""
        png = _make_png(size=100)
        params = {
            "frames": [{"src": 0, "frame": 0}],
            "size": 240,
            "fit": "fit",
        }
        resp = client.post(
            "/api/v1/emos/maker/process",
            files=[("files", ("p.png", png, "image/png"))],
            data={"params": json.dumps(params)},
        )
        assert resp.status_code == 200
        out = Image.open(io.BytesIO(resp.content))
        assert out.size == (240, 240)

    def test_process_empty_frames(self, client):
        """未选择任何帧返回错误"""
        resp = client.post(
            "/api/v1/emos/maker/process",
            files=[("files", ("a.gif", _make_gif(), "image/gif"))],
            data={"params": json.dumps({"frames": []})},
        )
        assert resp.json()["code"] == 1

    def test_process_bad_frame_index(self, client):
        """帧索引超出范围返回错误"""
        gif = _make_gif(frames=2)
        params = {"frames": [{"src": 0, "frame": 99}]}
        resp = client.post(
            "/api/v1/emos/maker/process",
            files=[("files", ("a.gif", gif, "image/gif"))],
            data={"params": json.dumps(params)},
        )
        assert resp.json()["code"] == 1

    def test_process_bad_params_json(self, client):
        """非法 JSON 参数返回错误"""
        resp = client.post(
            "/api/v1/emos/maker/process",
            files=[("files", ("a.gif", _make_gif(), "image/gif"))],
            data={"params": "{not-json"},
        )
        assert resp.json()["code"] == 1