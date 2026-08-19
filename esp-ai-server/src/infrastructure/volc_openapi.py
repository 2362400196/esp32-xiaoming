"""
火山引擎 OpenAPI v4 签名与"查询复刻音色列表"调用。

接口:BatchListMegaTTSTrainStatus(分页查询 SpeakerID 状态)
  - 端点:https://open.volcengineapi.com/?Action=BatchListMegaTTSTrainStatus&Version=2025-05-21
  - 鉴权:火山 OpenAPI v4 签名(HMAC-SHA256,类似 AWS SigV4),使用火山云账号的
    AccessKeyID + SecretAccessKey(控制台 > 访问控制 > API访问密钥),与 TTS 合成的
    X-Api-Key 是两套不同的凭据。
  - 请求体:ProjectName(必选,火山项目名)、SpeakerIDs(可选,传空返回该项目全部)、
    State(必选,如 Success/Active)、PageNumber/PageSize 分页。
  - 响应:Statuses[] 中 SpeakerID / Alias / State / DemoAudio / CreateTime 等。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

from src.infrastructure.config import get_settings
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)

# BatchListMegaTTSTrainStatus 固定参数
OPENAPI_HOST = "open.volcengineapi.com"
OPENAPI_REGION = "cn-beijing"
OPENAPI_SERVICE = "speech_saas_prod"
OPENAPI_VERSION = "2025-05-21"
OPENAPI_ACTION = "BatchListMegaTTSTrainStatus"
# 可合成、应保留的音色状态(其余如 Unknown/Training/Reclaimed/Expired 一律过滤)
_USABLE_STATES = {"Success", "Active"}
# 缓存(秒):复刻音色列表不常变,避免每次打开配置都请求火山
_CACHE_TTL = 60.0
# 按 access_key_id 分 key 缓存(不同设备可能用不同的火山凭据)
_cache: dict[str, dict] = {}


def _hmac_sha256(key: bytes, msg: bytes) -> bytes:
    return hmac.new(key, msg, hashlib.sha256).digest()


def _sha256_hex(msg: bytes) -> str:
    return hashlib.sha256(msg).hexdigest()


def _quote(s: str, safe: str = "-_.~") -> str:
    """RFC3986 编码(保留字母数字与 -_.~)"""
    return quote(s, safe=safe)


def _build_canonical_query(query: dict[str, str]) -> str:
    return "&".join(
        f"{_quote(k)}={_quote(v)}" for k, v in sorted(query.items())
    )


def _sign_request(
    access_key_id: str,
    secret_access_key: str,
    method: str,
    path: str,
    query: dict[str, str],
    body: dict[str, Any],
    region: str,
    service: str,
    xdate: str,
) -> str:
    """计算火山 OpenAPI v4 Authorization 头(与 AWS SigV4 同构)"""
    payload_hash = _sha256_hex(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode())
    host = OPENAPI_HOST
    canonical_headers = (
        f"host:{host}\n"
        f"x-content-sha256:{payload_hash}\n"
        f"x-date:{xdate}\n"
    )
    signed_headers = "host;x-content-sha256;x-date"
    canonical_query = _build_canonical_query(query)
    canonical_request = "\n".join(
        [method, path, canonical_query, canonical_headers, signed_headers, payload_hash]
    )

    short_date = xdate[:8]
    scope = f"{short_date}/{region}/{service}/request"
    string_to_sign = "\n".join(
        ["HMAC-SHA256", xdate, scope, _sha256_hex(canonical_request.encode())]
    )

    k_date = _hmac_sha256(secret_access_key.encode(), short_date.encode())
    k_region = _hmac_sha256(k_date, region.encode())
    k_service = _hmac_sha256(k_region, service.encode())
    k_signing = _hmac_sha256(k_service, b"request")
    signature = _hmac_sha256(k_signing, string_to_sign.encode()).hex()

    return (
        f"HMAC-SHA256 Credential={access_key_id}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )


def _now_xdate() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


async def fetch_clone_voices(
    *,
    credentials: dict[str, Any] | None = None,
    project_name: str | None = None,
    state: str = "",
    timeout: float = 15.0,
) -> list[dict[str, Any]]:
    """调用 BatchListMegaTTSTrainStatus 查询账号下全部复刻音色。

    Args:
        credentials: 设备级火山 OpenAPI 凭据 {access_key_id, secret_access_key, project_name},
            优先使用;缺失时回退到环境变量(VOLC_ACCESS_KEY_ID 等)。
        project_name: 火山项目名(与 credentials 同时提供时覆盖其 project_name)
        state: 音色状态过滤(空字符串 = 不过滤,返回全部;常用取值
            Success/Active/Unknown/Training/Expired/Reclaimed)。
            注意:不能默认 Active——训练成功但未激活的音色是 Success 状态,
            会被 Active 过滤掉导致列表为空。
        timeout: 请求超时(秒)

    Returns:
        [{speaker_id, alias, state, demo_audio, create_time, available_training_times}]

    Raises:
        RuntimeError: 未配置 AK/SK、或火山接口返回错误
    """
    settings = get_settings()
    cred = credentials or {}
    ak = cred.get("access_key_id") or settings.volc_access_key_id
    sk = cred.get("secret_access_key") or settings.volc_secret_access_key
    if not ak or not sk:
        raise RuntimeError("未配置火山 OpenAPI 访问密钥(VOLC_ACCESS_KEY_ID / VOLC_SECRET_ACCESS_KEY)")

    project = project_name or cred.get("project_name") or settings.volc_project_name
    if not project:
        raise RuntimeError("未配置火山项目名(VOLC_PROJECT_NAME)")

    query = {
        "Action": OPENAPI_ACTION,
        "Version": OPENAPI_VERSION,
    }
    body = {
        "ProjectName": project,
        "SpeakerIDs": [],
        "State": state,
        "PageNumber": 1,
        "PageSize": 100,
    }
    xdate = _now_xdate()
    authorization = _sign_request(
        ak, sk, "POST", "/", query, body, OPENAPI_REGION, OPENAPI_SERVICE, xdate
    )
    payload_hash = _sha256_hex(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode())

    headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "X-Date": xdate,
        "X-Content-Sha256": payload_hash,
        "Authorization": authorization,
    }

    url = f"https://{OPENAPI_HOST}/"
    voices: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, params=query, json=body, headers=headers)
        if resp.status_code != 200:
            raise RuntimeError(f"火山查询复刻音色失败 HTTP {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        meta = data.get("ResponseMetadata", {})
        if meta.get("Error"):
            err = meta["Error"]
            msg = f"{err.get('Code')} {err.get('Message')}"
            if err.get("Code") == "InvalidAccessKey":
                msg += " (AK/SK 无效:请确认填的是访问控制(IAM)创建的 API 访问密钥,AccessKeyId 以 AKLT 开头;语音服务的 Access Token/Secret Key 不适用)"
            raise RuntimeError(f"火山查询复刻音色失败: {msg}")

        result = data.get("Result", {})
        statuses = result.get("Statuses") or []
        for s in statuses:
            st = s.get("State", "")
            # 只保留可合成的音色(Success/Active),Unknown/Training/Reclaimed/Expired 一律过滤
            if st not in _USABLE_STATES:
                continue
            voices.append(
                {
                    "speaker_id": s.get("SpeakerID", ""),
                    "alias": s.get("Alias", ""),
                    "state": st,
                    "demo_audio": s.get("DemoAudio", ""),
                    "create_time": s.get("CreateTime", 0),
                    "available_training_times": s.get("AvailableTrainingTimes", 0),
                }
            )
    logger.info(f"[VolcOpenAPI] 查询复刻音色列表成功: {len(voices)} 个")
    return voices


async def get_clone_voices_cached(
    *, credentials: dict[str, Any] | None = None, project_name: str | None = None, state: str = ""
) -> list[dict[str, Any]]:
    """带缓存的复刻音色列表查询(60s),state 默认空 = 返回全部。

    缓存按 access_key_id 区分,避免不同设备(不同凭据)串用缓存。
    """
    global _cache
    settings = get_settings()
    ak_key = (credentials or {}).get("access_key_id") or settings.volc_access_key_id or "default"
    entry = _cache.get(ak_key)
    now = time.time()
    if entry and entry.get("voices") and now - entry["ts"] < _CACHE_TTL:
        return list(entry["voices"])
    try:
        voices = await fetch_clone_voices(credentials=credentials, project_name=project_name, state=state)
        _cache[ak_key] = {"ts": time.time(), "voices": voices}
        return voices
    except Exception as e:
        logger.warning(f"[VolcOpenAPI] 查询复刻音色失败: {e}")
        # 失败时返回该凭据上次成功缓存(如果有),否则抛错由上层处理
        if entry and entry.get("voices"):
            return list(entry["voices"])
        raise


def clear_clone_voices_cache() -> None:
    global _cache
    _cache = {}
