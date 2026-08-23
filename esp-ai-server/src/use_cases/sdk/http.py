"""SDK HTTP 请求 - 网络请求工具"""

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
            resp = await client.request(method, url, params=params, headers=req_headers, content=content)
            resp.raise_for_status()
            return resp, None
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