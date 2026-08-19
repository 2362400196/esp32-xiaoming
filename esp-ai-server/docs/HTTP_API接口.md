# HTTP API 接口文档

本文档介绍 ESP-AI 服务器的 HTTP API 接口。

## 基础信息

- **Base URL**: `http://localhost:8088`
- **Content-Type**: `application/json`
- **鉴权**: 在 `users.json` 中配置 `key`，WebSocket 连接时通过 `?key=xxx` 传入

---

## 统一响应格式

所有接口返回统一的 JSON 结构：

```json
// 成功
{"code": 0, "message": "ok", "data": {...}}

// 失败
{"code": 404, "message": "设备未找到: xxx", "data": null}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | int | 0=成功，非0=失败 |
| `message` | string | 状态描述 |
| `data` | object/array/null | 业务数据 |

---

## 接口列表

| 接口 | 方法 | 鉴权 | 说明 |
|------|------|------|------|
| `/api/health` | GET | 否 | 健康检查 |
| `/api/devices` | GET | 是 | 获取所有已连接设备 |
| `/api/devices/{device_id}` | GET | 是 | 获取单个设备详情 |
| `/api/wakeup` | POST | 是 | 唤醒指定设备 |
| `/api/wakeup/all` | POST | 是 | 唤醒所有设备 |
| `/api/speak` | POST | 是 | 让指定设备说话 |
| `/api/speak/all` | POST | 是 | 让所有设备说话 |
| `/api/stop` | POST | 是 | 让指定设备进入待机 |
| `/api/stop/all` | POST | 是 | 让所有设备进入待机 |

---

## 接口详情

### 1. 健康检查

```
GET /api/health
```

**响应示例：**
```json
{
    "code": 0,
    "message": "ok",
    "data": {"status": "healthy"}
}
```

---

### 2. 获取所有设备

```
GET /api/devices
```

**响应示例：**
```json
{
    "code": 0,
    "message": "ok",
    "data": {
        "count": 2,
        "devices": [
            {
                "device_id": "D8:3B:DA:6D:D9:3C",
                "name": "客厅设备",
                "connected": true,
                "state": "asr",
                "session_id": "64111d92"
            },
            {
                "device_id": "A1:B2:C3:D4:E5:F6",
                "name": "卧室设备",
                "connected": true,
                "state": "idle",
                "session_id": "a8486629"
            }
        ]
    }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `device_id` | string | 设备的MAC地址（对外标识） |
| `name` | string | 设备名称（来自 users.json） |
| `connected` | bool | 是否在线 |
| `state` | string | 当前状态：`idle` / `asr` / `llm` / `tts` |
| `session_id` | string | 当前会话ID |

---

### 3. 获取单个设备

```
GET /api/devices/{device_id}
```

`{device_id}` 为**MAC地址**，如 `D8:3B:DA:6D:D9:3C`。

**响应示例：**
```json
{
    "code": 0,
    "message": "ok",
    "data": {
        "device_id": "D8:3B:DA:6D:D9:3C",
        "name": "客厅设备",
        "connected": true,
        "state": "asr",
        "session_id": "64111d92",
        "tts_playing": false
    }
}
```

| 新增字段 | 类型 | 说明 |
|----------|------|------|
| `tts_playing` | bool | 是否正在播放TTS语音 |

---

### 4. 唤醒指定设备

```
POST /api/wakeup
Content-Type: application/json
```

**请求体：**
```json
{
    "device_id": "D8:3B:DA:6D:D9:3C"
}
```

**响应示例：**
```json
{
    "code": 0,
    "message": "唤醒成功",
    "data": {"device_id": "D8:3B:DA:6D:D9:3C"}
}
```

---

### 5. 唤醒所有设备

```
POST /api/wakeup/all
```

无请求体。

**响应示例：**
```json
{
    "code": 0,
    "message": "已唤醒 2 台设备",
    "data": {
        "count": 2,
        "devices": ["D8:3B:DA:6D:D9:3C", "A1:B2:C3:D4:E5:F6"]
    }
}
```

---

### 6. 让指定设备说话

```
POST /api/speak
Content-Type: application/json
```

**请求体：**
```json
{
    "device_id": "D8:3B:DA:6D:D9:3C",
    "text": "你好，欢迎使用"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `device_id` | string | 是 | 设备MAC地址 |
| `text` | string | 是 | 要合成的文本 |

**响应示例：**
```json
{
    "code": 0,
    "message": "播放成功",
    "data": {
        "device_id": "D8:3B:DA:6D:D9:3C",
        "text": "你好，欢迎使用"
    }
}
```

**失败响应：**
```json
{
    "code": 500,
    "message": "说话失败，设备未连接或不在线",
    "data": null
}
```

---

### 7. 让所有设备说话

```
POST /api/speak/all
Content-Type: application/json
```

**请求体：**
```json
{
    "text": "各位早上好"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `text` | string | 是 | 要合成的文本 |

**响应示例：**
```json
{
    "code": 0,
    "message": "已向 2 台设备播放",
    "data": {
        "count": 2,
        "devices": ["D8:3B:DA:6D:D9:3C", "A1:B2:C3:D4:E5:F6"],
        "text": "各位早上好"
    }
}
```

---

### 8. 让指定设备进入待机

```
POST /api/stop
Content-Type: application/json
```

**请求体：**
```json
{
    "device_id": "D8:3B:DA:6D:D9:3C"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `device_id` | string | 是 | 设备MAC地址 |

**响应示例：**
```json
{
    "code": 0,
    "message": "设备已进入待机",
    "data": {"device_id": "D8:3B:DA:6D:D9:3C"}
}
```

> 停止效果：如果设备正在播放 TTS 或处理对话，立即中断；清除 ASR 状态，发送 `session_end` 让设备进入待机。

---

### 9. 让所有设备进入待机

```
POST /api/stop/all
```

无请求体。

**响应示例：**
```json
{
    "code": 0,
    "message": "已停止 2 台设备",
    "data": {
        "count": 2,
        "devices": ["D8:3B:DA:6D:D9:3C", "A1:B2:C3:D4:E5:F6"]
    }
}
```

---

## curl 示例

```bash
# 健康检查
curl http://localhost:8088/api/health

# 获取设备列表
curl http://localhost:8088/api/devices

# 获取单个设备
curl http://localhost:8088/api/devices/D8:3B:DA:6D:D9:3C

# 唤醒指定设备
curl -X POST http://localhost:8088/api/wakeup \
  -H "Content-Type: application/json" \
  -d '{"device_id":"D8:3B:DA:6D:D9:3C"}'

# 唤醒所有设备
curl -X POST http://localhost:8088/api/wakeup/all

# 让指定设备说话
curl -X POST http://localhost:8088/api/speak \
  -H "Content-Type: application/json" \
  -d '{"device_id":"D8:3B:DA:6D:D9:3C","text":"你好，当前时间已到"}'

# 让所有设备说话
curl -X POST http://localhost:8088/api/speak/all \
  -H "Content-Type: application/json" \
  -d '{"text":"各位，准备开饭了"}'

# 让指定设备进入待机
curl -X POST http://localhost:8088/api/stop \
  -H "Content-Type: application/json" \
  -d '{"device_id":"D8:3B:DA:6D:D9:3C"}'

# 让所有设备进入待机
curl -X POST http://localhost:8088/api/stop/all
```

---

## Python 调用示例

### 基础封装类

```python
import requests


class EspAI:
    """ESP-AI Server API 客户端"""

    def __init__(self, base_url: str = "http://localhost:8088"):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def _get(self, path: str) -> dict:
        resp = self.session.get(f"{self.base_url}{path}")
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: dict | None = None) -> dict:
        resp = self.session.post(f"{self.base_url}{path}", json=body or {})
        resp.raise_for_status()
        return resp.json()

    # ── 健康检查 ──
    def health(self) -> dict:
        return self._get("/api/health")

    # ── 设备管理 ──
    def list_devices(self) -> list[dict]:
        """获取所有已连接设备"""
        r = self._get("/api/devices")
        return r["data"]["devices"]

    def get_device(self, device_id: str) -> dict:
        """获取单个设备详情"""
        r = self._get(f"/api/devices/{device_id}")
        return r["data"]

    def device_ids(self) -> list[str]:
        """获取所有设备的 MAC 地址列表"""
        return [d["device_id"] for d in self.list_devices()]

    # ── 唤醒 ──
    def wakeup(self, device_id: str) -> dict:
        """唤醒指定设备"""
        return self._post("/api/wakeup", {"device_id": device_id})

    def wakeup_all(self) -> dict:
        """唤醒所有设备"""
        return self._post("/api/wakeup/all")

    # ── 说话 ──
    def speak(self, device_id: str, text: str) -> dict:
        """让指定设备 TTS 播放文本"""
        return self._post("/api/speak", {"device_id": device_id, "text": text})

    def speak_all(self, text: str) -> dict:
        """让所有设备 TTS 播放文本"""
        return self._post("/api/speak/all", {"text": text})

    # ── 停止 ──
    def stop(self, device_id: str) -> dict:
        """让指定设备进入待机"""
        return self._post("/api/stop", {"device_id": device_id})

    def stop_all(self) -> dict:
        """让所有设备进入待机"""
        return self._post("/api/stop/all")
```

### 使用示例

```python
# 初始化客户端
esp = EspAI("http://localhost:8088")

# 1. 健康检查
print(esp.health())
# → {"code": 0, "message": "ok", "data": {"status": "healthy"}}

# 2. 获取所有在线设备
devices = esp.list_devices()
print(devices)
# → [{"device_id": "D8:3B:DA:6D:D9:3C", "name": "客厅设备", ...}, ...]

# 3. 查看某个设备状态
device = esp.get_device("D8:3B:DA:6D:D9:3C")
print(device["state"])       # → "idle"
print(device["tts_playing"]) # → False

# 4. 唤醒客厅设备
esp.wakeup("D8:3B:DA:6D:D9:3C")

# 5. 让客厅设备说话
esp.speak("D8:3B:DA:6D:D9:3C", "你好，现在是晚上十点，该休息了")

# 6. 向所有设备广播
esp.speak_all("各位，有人按门铃了")

# 7. 遍历所有设备并分别说话
for d in esp.list_devices():
    esp.speak(d["device_id"], f"你好{d['name']}，系统已就绪")

# 8. 让指定设备进入待机
esp.stop("D8:3B:DA:6D:D9:3C")

# 9. 让所有设备进入待机（静默）
esp.stop_all()
```

### 异步版本（asyncio + httpx）

```python
import asyncio
import httpx


class AsyncEspAI:
    def __init__(self, base_url: str = "http://localhost:8088"):
        self.base_url = base_url.rstrip("/")

    async def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(
                method, f"{self.base_url}{path}",
                json=body,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            return resp.json()

    async def list_devices(self) -> list[dict]:
        r = await self._request("GET", "/api/devices")
        return r["data"]["devices"]

    async def speak(self, device_id: str, text: str) -> dict:
        return await self._request("POST", "/api/speak", {"device_id": device_id, "text": text})

    async def wakeup(self, device_id: str) -> dict:
        return await self._request("POST", "/api/wakeup", {"device_id": device_id})

    async def speak_all(self, text: str) -> dict:
        return await self._request("POST", "/api/speak/all", {"text": text})

    async def stop(self, device_id: str) -> dict:
        return await self._request("POST", "/api/stop", {"device_id": device_id})

    async def stop_all(self) -> dict:
        return await self._request("POST", "/api/stop/all")


# 使用
async def main():
    esp = AsyncEspAI()
    devices = await esp.list_devices()
    for d in devices:
        await esp.speak(d["device_id"], f"你好{d.get('name', '')}")


asyncio.run(main())
```
