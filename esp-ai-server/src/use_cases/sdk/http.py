"""SDK HTTP 请求 - 网络请求工具"""

import asyncio
import time
import uuid

import httpx

from src.infrastructure.plugin_security import require_permission


async def http_request(method: str, url: str, *, params: dict | None = None, headers: dict | None = None,
                       content=None, timeout: float = 10.0, pin_ip: str | None = None):
    """发起 HTTP 请求。成功返回 (response, None)；失败返回 (None, error)。

    Args:
        pin_ip: 校验时解析的 IP，用于 pin 连接防止 DNS 重绑定。
                设置后会在 URL 中替换主机名为该 IP，并通过 Host header 保留原主机名。
    """
    require_permission("network", f"发起 HTTP {method.upper()} 请求 {url}")
    try:
        req_headers = dict(headers or {})
        if pin_ip:
            import urllib.parse as _up
            parsed = _up.urlparse(url)
            host = parsed.hostname or ""
            if host and host != pin_ip and parsed.scheme == "http":
                port = f":{parsed.port}" if parsed.port else ""
                url = _up.urlunparse((
                    parsed.scheme, f"{pin_ip}{port}",
                    parsed.path, parsed.params, parsed.query, parsed.fragment
                ))
                req_headers.setdefault("Host", host)
        async with httpx.AsyncClient(timeout=timeout) as client:
            # 用 asyncio.wait_for 兜底，防止 httpx 在某些网络环境下超时不生效
            resp = await asyncio.wait_for(
                client.request(method, url, params=params, headers=req_headers, content=content),
                timeout=timeout + 2,
            )
            resp.raise_for_status()
            return resp, None
    except asyncio.TimeoutError:
        return None, TimeoutError(f"请求超时 ({timeout}s)")
    except Exception as e:
        return None, e


async def http_get_json(url: str, params: dict | None = None, headers: dict | None = None,
                        timeout: float = 8.0, pin_ip: str | None = None):
    """GET 请求并解析 JSON。成功返回 (data, None)；失败返回 (None, error)。"""
    resp, err = await http_request("GET", url, params=params, headers=headers, timeout=timeout, pin_ip=pin_ip)
    if err:
        return None, err
    try:
        return resp.json(), None
    except Exception as e:
        return None, e


# ════════════════════════════════════════════════════════════
# 流式 HTTP（SSE）支持
# ════════════════════════════════════════════════════════════

# stream_id → {"client", "response", "queue", "task", "last_read_at"}
_http_streams: dict[str, dict] = {}
_STREAM_TTL = 120.0


async def _stream_reader(stream_id: str, entry: dict) -> None:
    """后台任务：持续读取响应行，放入队列，供 http_stream_read 消费。"""
    try:
        async for line in entry["response"].aiter_lines():
            await entry["queue"].put(("line", line))
    except asyncio.CancelledError:
        raise
    except Exception as e:
        await entry["queue"].put(("error", str(e)))
    finally:
        await entry["queue"].put(("done", None))


async def http_stream_open(method: str, url: str, *, headers: dict | None = None,
                           content=None, timeout: float = 30.0, pin_ip: str | None = None):
    """打开流式 HTTP 请求（SSE），返回 (stream_id, None) 或 (None, error)。

    请求发送后立即返回，响应体由后台任务逐行读取，调用方通过
    http_stream_read 按需拉取，实现真流式。
    """
    require_permission("network", f"发起流式 HTTP {method.upper()} 请求 {url}")
    try:
        req_headers = dict(headers or {})
        if pin_ip:
            import urllib.parse as _up
            parsed = _up.urlparse(url)
            host = parsed.hostname or ""
            if host and host != pin_ip and parsed.scheme == "http":
                port = f":{parsed.port}" if parsed.port else ""
                url = _up.urlunparse((
                    parsed.scheme, f"{pin_ip}{port}",
                    parsed.path, parsed.params, parsed.query, parsed.fragment
                ))
                req_headers.setdefault("Host", host)
        client = httpx.AsyncClient(timeout=timeout)
        req = client.build_request(method, url, headers=req_headers, content=content)
        response = await asyncio.wait_for(client.send(req, stream=True), timeout=timeout + 2)
        if response.status_code >= 400:
            body = (await response.aread()).decode("utf-8", "replace")[:500]
            await response.aclose()
            await client.aclose()
            return None, RuntimeError(f"HTTP {response.status_code}: {body}")
        stream_id = uuid.uuid4().hex[:12]
        entry = {
            "client": client,
            "response": response,
            "queue": asyncio.Queue(),
            "last_read_at": time.time(),
        }
        _http_streams[stream_id] = entry
        entry["task"] = asyncio.create_task(_stream_reader(stream_id, entry))
        return stream_id, None
    except asyncio.TimeoutError:
        return None, TimeoutError(f"请求超时 ({timeout}s)")
    except Exception as e:
        return None, e


async def http_stream_read(stream_id: str, timeout: float = 0.5):
    """从流式响应读取下一行。返回 (line, None)；超时返回 (None, None)；出错返回 (None, err)。"""
    entry = _http_streams.get(stream_id)
    if not entry:
        return None, RuntimeError("stream not found")
    if time.time() - entry["last_read_at"] > _STREAM_TTL:
        await http_stream_close(stream_id)
        return None, RuntimeError("stream expired")
    try:
        kind, payload = await asyncio.wait_for(entry["queue"].get(), timeout=timeout)
    except asyncio.TimeoutError:
        return None, None
    entry["last_read_at"] = time.time()
    if kind == "line":
        return payload, None
    if kind == "error":
        return None, RuntimeError(payload)
    return None, None  # done


async def http_stream_close(stream_id: str) -> None:
    """关闭流式响应并清理资源。"""
    entry = _http_streams.pop(stream_id, None)
    if not entry:
        return
    task = entry.get("task")
    if task:
        task.cancel()
    try:
        await entry["response"].aclose()
    except Exception:
        pass
    try:
        await entry["client"].aclose()
    except Exception:
        pass