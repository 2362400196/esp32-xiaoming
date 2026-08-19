"""volc_openapi 单元测试:火山 OpenAPI 签名、复刻音色列表调用与缓存"""
import json
import struct
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infrastructure import volc_openapi
from src.infrastructure.volc_openapi import (
    OPENAPI_ACTION,
    OPENAPI_HOST,
    _sign_request,
    fetch_clone_voices,
    get_clone_voices_cached,
)
from src.infrastructure.device_api import _fix_wav_header


class TestSignRequest:
    """火山 OpenAPI v4 签名"""

    def test_authorization_structure(self):
        auth = _sign_request(
            "AK_TEST", "SK_TEST", "POST", "/",
            {"Action": OPENAPI_ACTION, "Version": "2025-05-21"},
            {"ProjectName": "default", "State": "Active"},
            "cn-beijing", "speech_saas_prod", "20250711T035336Z",
        )
        assert auth.startswith(
            "HMAC-SHA256 Credential=AK_TEST/20250711/cn-beijing/speech_saas_prod/request, "
            "SignedHeaders=host;x-content-sha256;x-date, Signature="
        )
        assert len(auth.split("Signature=")[1]) == 64

    def test_deterministic(self):
        args = dict(
            method="POST", path="/",
            query={"Action": OPENAPI_ACTION, "Version": "2025-05-21"},
            body={"ProjectName": "default", "State": "Active"},
            region="cn-beijing", service="speech_saas_prod",
            xdate="20250711T035336Z",
        )
        a = _sign_request("AK", "SK", **args)
        b = _sign_request("AK", "SK", **args)
        assert a == b
        # 密钥不同签名必须不同
        c = _sign_request("AK", "SK_OTHER", **args)
        assert a != c


class TestFetchCloneVoices:
    """fetch_clone_voices:mock 火山 OpenAPI 响应"""

    @pytest.fixture(autouse=True)
    def _settings(self, monkeypatch):
        settings = MagicMock()
        settings.volc_access_key_id = "AK_TEST"
        settings.volc_secret_access_key = "SK_TEST"
        settings.volc_project_name = "default"
        monkeypatch.setattr(volc_openapi, "get_settings", lambda: settings)

    @pytest.mark.asyncio
    async def test_missing_credentials(self, monkeypatch):
        settings = MagicMock()
        settings.volc_access_key_id = ""
        settings.volc_secret_access_key = ""
        settings.volc_project_name = "default"
        monkeypatch.setattr(volc_openapi, "get_settings", lambda: settings)
        with pytest.raises(RuntimeError, match="访问密钥"):
            await fetch_clone_voices()

    @pytest.mark.asyncio
    async def test_success_parses_voices(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.json = MagicMock(
            return_value={
                "ResponseMetadata": {"RequestId": "x"},
                "Result": {
                    "Statuses": [
                        {
                            "SpeakerID": "S_abc",
                            "Alias": "我的声音",
                            "State": "Active",
                            "DemoAudio": "https://example.com/a.mp3",
                            "CreateTime": 1700000000000,
                            "AvailableTrainingTimes": 5,
                        },
                        {"SpeakerID": "icl_xyz", "Alias": "", "State": "Success",
                         "DemoAudio": "", "CreateTime": 0, "AvailableTrainingTimes": 0},
                    ]
                },
            }
        )
        client = MagicMock()
        client.post = AsyncMock(return_value=resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(volc_openapi.httpx, "AsyncClient", return_value=client):
            voices = await fetch_clone_voices()

        assert len(voices) == 2
        assert voices[0]["speaker_id"] == "S_abc"
        assert voices[0]["alias"] == "我的声音"
        assert voices[0]["state"] == "Active"
        assert voices[1]["speaker_id"] == "icl_xyz"

        # 校验请求:端点、query、鉴权头、请求体
        call_args = client.post.await_args
        assert call_args.args[0] == f"https://{OPENAPI_HOST}/"
        call_kwargs = call_args.kwargs
        assert call_kwargs["params"]["Action"] == OPENAPI_ACTION
        assert call_kwargs["headers"]["Authorization"].startswith("HMAC-SHA256 Credential=AK_TEST/")
        assert "X-Date" in call_kwargs["headers"]
        assert call_kwargs["json"]["ProjectName"] == "default"
        # 默认 state 为空 = 返回全部状态
        assert call_kwargs["json"]["State"] == ""
        assert call_kwargs["json"]["SpeakerIDs"] == []

    @pytest.mark.asyncio
    async def test_filters_unusable_states(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.json = MagicMock(
            return_value={
                "ResponseMetadata": {"RequestId": "x"},
                "Result": {
                    "Statuses": [
                        {"SpeakerID": "S_success", "Alias": "可用1", "State": "Success",
                         "DemoAudio": "", "CreateTime": 0, "AvailableTrainingTimes": 5},
                        {"SpeakerID": "S_active", "Alias": "可用2", "State": "Active",
                         "DemoAudio": "", "CreateTime": 0, "AvailableTrainingTimes": 5},
                        {"SpeakerID": "S_unknown", "Alias": "", "State": "Unknown",
                         "DemoAudio": "", "CreateTime": 0, "AvailableTrainingTimes": 0},
                        {"SpeakerID": "S_rec", "Alias": "", "State": "Reclaimed",
                         "DemoAudio": "", "CreateTime": 0, "AvailableTrainingTimes": 0},
                        {"SpeakerID": "S_exp", "Alias": "", "State": "Expired",
                         "DemoAudio": "", "CreateTime": 0, "AvailableTrainingTimes": 0},
                        {"SpeakerID": "S_train", "Alias": "", "State": "Training",
                         "DemoAudio": "", "CreateTime": 0, "AvailableTrainingTimes": 0},
                    ]
                },
            }
        )
        client = MagicMock()
        client.post = AsyncMock(return_value=resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        with patch.object(volc_openapi.httpx, "AsyncClient", return_value=client):
            voices = await fetch_clone_voices()
        # 只保留 Success/Active,Unknown/Reclaimed/Expired/Training 全过滤
        assert [v["speaker_id"] for v in voices] == ["S_success", "S_active"]

    @pytest.mark.asyncio
    async def test_credentials_override_env(self):
        # 设备级凭据优先于环境变量
        resp = MagicMock()
        resp.status_code = 200
        resp.json = MagicMock(return_value={"ResponseMetadata": {}, "Result": {"Statuses": []}})
        client = MagicMock()
        client.post = AsyncMock(return_value=resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        creds = {"access_key_id": "AKLT_DEVICE", "secret_access_key": "DEVICE_SK", "project_name": "proj-x"}
        with patch.object(volc_openapi.httpx, "AsyncClient", return_value=client):
            await fetch_clone_voices(credentials=creds)
        call_kwargs = client.post.await_args.kwargs
        # 签名用的是设备级 AK
        assert call_kwargs["headers"]["Authorization"].startswith("HMAC-SHA256 Credential=AKLT_DEVICE/")
        assert call_kwargs["json"]["ProjectName"] == "proj-x"

    @pytest.mark.asyncio
    async def test_api_error_raises(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.json = MagicMock(
            return_value={
                "ResponseMetadata": {"Error": {"Code": "SignatureDoesNotMatch", "Message": "bad sig"}}
            }
        )
        client = MagicMock()
        client.post = AsyncMock(return_value=resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        with patch.object(volc_openapi.httpx, "AsyncClient", return_value=client):
            with pytest.raises(RuntimeError, match="SignatureDoesNotMatch"):
                await fetch_clone_voices()

    @pytest.mark.asyncio
    async def test_http_error_raises(self):
        resp = MagicMock()
        resp.status_code = 401
        resp.text = "Unauthorized"
        client = MagicMock()
        client.post = AsyncMock(return_value=resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        with patch.object(volc_openapi.httpx, "AsyncClient", return_value=client):
            with pytest.raises(RuntimeError, match="HTTP 401"):
                await fetch_clone_voices()


class TestFixWavHeader:
    """火山流式 WAV 头修复"""

    def test_fixes_streaming_sizes(self):
        # 构造 RIFF/data size 均为 0xFFFFFFFF 的流式 WAV
        wav = b"RIFF" + b"\xff\xff\xff\xff" + b"WAVE"
        wav += b"fmt " + struct.pack("<I", 16) + b"\x01\x00\x01\x00" + struct.pack("<IHHI", 24000, 48000, 2, 16)
        wav += b"data" + b"\xff\xff\xff\xff" + b"\x00" * 100
        fixed = _fix_wav_header(wav)
        assert fixed[:4] == b"RIFF"
        # RIFF size = 文件总长 - 8
        assert struct.unpack("<I", fixed[4:8])[0] == len(wav) - 8
        # data chunk size = 数据实际长度(100)
        idx = fixed.find(b"data")
        assert struct.unpack("<I", fixed[idx + 4 : idx + 8])[0] == 100

    def test_leaves_standard_wav_untouched(self):
        wav = b"RIFF" + struct.pack("<I", 44) + b"WAVE"
        wav += b"fmt " + struct.pack("<I", 16) + b"\x01\x00\x01\x00" + struct.pack("<IHHI", 24000, 48000, 2, 16)
        wav += b"data" + struct.pack("<I", 8) + b"\x00" * 8
        fixed = _fix_wav_header(wav)
        assert fixed == wav  # 标准 WAV 不变

    def test_non_riff_untouched(self):
        assert _fix_wav_header(b"not a wav file") == b"not a wav file"


class TestGetCloneVoicesCached:
    """缓存逻辑"""

    @pytest.mark.asyncio
    async def test_cached_after_first_call(self):
        with patch.object(volc_openapi, "fetch_clone_voices", new=AsyncMock(return_value=[{"speaker_id": "S_a"}])) as mock_fetch:
            v1 = await get_clone_voices_cached()
            v2 = await get_clone_voices_cached()
            assert v1 == v2 == [{"speaker_id": "S_a"}]
            assert mock_fetch.await_count == 1  # 第二次走缓存
        volc_openapi.clear_clone_voices_cache()

    @pytest.mark.asyncio
    async def test_failure_falls_back_to_cache(self):
        with patch.object(volc_openapi, "fetch_clone_voices", new=AsyncMock(side_effect=[RuntimeError("boom")])) as mock_fetch:
            # 无缓存时失败直接抛错
            volc_openapi.clear_clone_voices_cache()
            with pytest.raises(RuntimeError):
                await get_clone_voices_cached()

        # 先成功填充缓存,再失败应返回缓存
        with patch.object(volc_openapi, "fetch_clone_voices", new=AsyncMock(return_value=[{"speaker_id": "S_a"}])) as mock_fetch:
            volc_openapi.clear_clone_voices_cache()
            await get_clone_voices_cached()
        with patch.object(volc_openapi, "fetch_clone_voices", new=AsyncMock(side_effect=RuntimeError("boom"))):
            voices = await get_clone_voices_cached()
            assert voices == [{"speaker_id": "S_a"}]
        volc_openapi.clear_clone_voices_cache()
