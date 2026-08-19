# 远程配置集成指南

本文档说明如何将独立的管理后台系统与 ESP-AI-Server 集成，通过 JSON API 实现配置管理。

## 架构概览

```
┌─────────────────┐         HTTP/JSON          ┌─────────────────┐
│   管理后台系统   │ ──────────────────────────► │  ESP-AI-Server  │
│                 │    GET /api/v1/devices/    │                 │
│  用户管理        │    GET /api/v1/users/     │  语音对话服务    │
│  设备管理        │ ◄──────────────────────── │                 │
│  配置管理        │      返回 JSON 配置        │  零数据库设计    │
└─────────────────┘                            └─────────────────┘
```

## 两种集成模式

### 模式 1：配置拉取（推荐）

ESP-AI-Server 主动从管理后台拉取配置。

### 模式 2：配置推送（WebSocket）

管理后台通过 WebSocket 主动推送配置更新。

## API 接口设计

### 管理后台需要实现的接口

```json
1. 获取设备配置
   GET /api/v1/devices/{device_key}/config

   返回：
   {
     "device_id": "device_001",
     "name": "客厅语音助手",
     "api_key": "sk_xxx",
     "asr_provider": "volcengine",
     "llm_model": "gpt-4",
     "llm_system_prompt": "你是小智...",
     "tts_voice_type": "BV700",
     "llm_memory_enabled": true,
     "llm_memory_max_messages": 20,
     "mcp_servers": {
       "weather": {
         "command": "npx",
         "args": ["-y", "@anthropic/mcp-server-weather"]
       }
     }
   }

2. 获取用户配置
   GET /api/v1/users/{user_id}/config

3. 获取 MCP 配置
   GET /api/v1/users/{user_id}/mcp

4. 获取所有设备（可选）
   GET /api/v1/devices

5. 上报设备状态
   POST /api/v1/devices/{device_key}/status
   {
     "device_key": "xxx",
     "status": "online",
     "timestamp": 1699999999,
     "metadata": {}
   }
```

## 快速集成步骤

### 步骤 1：配置环境变量

```bash
# .env 文件

# 远程配置（管理后台）
REMOTE_CONFIG_URL=http://localhost:3000
REMOTE_CONFIG_API_KEY=your_api_key

# 或使用完整配置
REMOTE_CONFIG_ENABLED=true
REMOTE_CONFIG_URL=http://localhost:3000
REMOTE_CONFIG_CACHE_TTL=300
REMOTE_CONFIG_REFRESH_INTERVAL=60
```

### 步骤 2：初始化远程配置提供者

```python
# src/main.py 或应用启动时

from src.infrastructure.remote_config import init_remote_config_provider

# 初始化
remote_config = init_remote_config_provider(
    api_base_url="http://localhost:3000",
    api_key="your_api_key",
    cache_ttl=300,  # 缓存 5 分钟
    refresh_interval=60,  # 每 60 秒刷新
)

# 启动后台刷新任务
await remote_config.start_background_refresh()
```

### 步骤 3：创建 AuthService 时注入

```python
from src.infrastructure.auth import AuthService
from src.infrastructure.remote_config import get_remote_config_provider

# 创建认证服务
auth_service = AuthService(
    config={"enabled": True},
    remote_config_provider=get_remote_config_provider(),
)
```

### 步骤 4：设备连接时自动获取配置

设备连接时，`AuthService.get_user_config()` 会自动：

1. 尝试从远程管理后台获取配置
2. 如果远程失败，回退到本地 `users.json`
3. 缓存配置，支持 TTL 过期自动刷新

## 配置字段说明

### 设备配置字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `device_id` | string | 设备唯一标识 |
| `name` | string | 设备名称 |
| `api_key` | string | API 密钥（可选） |
| `asr_provider` | string | ASR 提供商 (volcengine/tencent/aliyun/xunfei) |
| `llm_model` | string | LLM 模型名称 |
| `llm_api_key` | string | LLM API Key |
| `llm_base_url` | string | LLM API 地址（兼容代理） |
| `llm_system_prompt` | string | 系统提示词 |
| `tts_voice_type` | string | TTS 音色 |
| `tts_speed` | float | 语速 (0.5-2.0) |
| `llm_memory_enabled` | bool | 是否启用对话记忆 |
| `llm_memory_max_messages` | int | 最大记忆消息数 |
| `rate_limit_rpm` | int | 每分钟限流次数 |
| `mcp_servers` | object | MCP 服务器配置 |

### MCP 服务器配置示例

```json
{
  "mcp_servers": {
    "weather": {
      "command": "npx",
      "args": ["-y", "@anthropic/mcp-server-weather"]
    },
    "calculator": {
      "command": "python",
      "args": ["/path/to/calculator_server.py"]
    }
  }
}
```

## 管理后台实现示例

### Node.js/Express

```javascript
const express = require('express');
const app = express();

app.get('/api/v1/devices/:deviceKey/config', async (req, res) => {
  const { deviceKey } = req.params;

  try {
    // 从数据库获取设备配置
    const device = await db.devices.findOne({
      where: { device_key: deviceKey }
    });

    if (!device) {
      return res.status(404).json({ error: 'Device not found' });
    }

    // 返回配置
    res.json({
      device_id: device.id,
      name: device.name,
      api_key: device.api_key,
      llm_model: device.llm_model,
      llm_system_prompt: device.system_prompt,
      tts_voice_type: device.tts_voice,
      llm_memory_enabled: true,
      llm_memory_max_messages: 20,
      mcp_servers: JSON.parse(device.mcp_config || '{}')
    });
  } catch (error) {
    console.error('Error fetching device config:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

app.post('/api/v1/devices/:deviceKey/status', async (req, res) => {
  const { deviceKey } = req.params;
  const { status, metadata } = req.body;

  // 记录设备状态
  await db.device_logs.create({
    device_key: deviceKey,
    status,
    metadata,
    timestamp: Date.now()
  });

  res.json({ success: true });
});

app.listen(3000);
```

### Python/FastAPI

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
import httpx

app = FastAPI()

class DeviceStatus(BaseModel):
    device_key: str
    status: str
    metadata: Optional[Dict[str, Any]] = None

@app.get("/api/v1/devices/{device_key}/config")
async def get_device_config(device_key: str):
    # 从数据库获取
    device = await db.devices.get(device_key=device_key)

    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    return {
        "device_id": device.id,
        "name": device.name,
        "api_key": device.api_key,
        "llm_model": device.llm_model,
        "llm_system_prompt": device.system_prompt,
        "tts_voice_type": device.tts_voice,
        "llm_memory_enabled": True,
        "llm_memory_max_messages": 20,
        "mcp_servers": device.mcp_config or {}
    }

@app.post("/api/v1/devices/{device_key}/status")
async def report_device_status(device_key: str, status: DeviceStatus):
    # 记录状态
    await db.device_logs.create(
        device_key=status.device_key,
        status=status.status,
        metadata=status.metadata
    )
    return {"success": True}
```

## 认证与安全

### API Key 认证

```bash
curl -H "Authorization: Bearer YOUR_API_KEY" \
     http://localhost:3000/api/v1/devices/device_001/config
```

### HTTPS

生产环境建议使用 HTTPS：

```bash
REMOTE_CONFIG_URL=https://your-admin-backend.com
```

## 缓存策略

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `cache_ttl` | 300 | 缓存有效期（秒） |
| `refresh_interval` | 60 | 后台刷新间隔（秒） |

### 手动刷新

```python
from src.infrastructure.remote_config import get_remote_config_provider

remote_config = get_remote_config_provider()

# 清除所有缓存
await remote_config.clear_cache()

# 更新配置
remote_config.update_config(
    api_base_url="http://new-url.com",
    api_key="new_key"
)
```

## 错误处理

远程配置失败时的处理策略：

1. **首次连接失败**：返回 `None`，使用本地 `users.json`
2. **缓存有效**：继续使用缓存配置
3. **缓存过期且刷新失败**：使用过期缓存 + 记录警告日志

```python
# 实际行为
async def get_user_config(self, device_key: str):
    # 1. 尝试远程
    if remote_config and remote_config.is_enabled:
        config = await remote_config.get_device_config(device_key)
        if config:
            return config

    # 2. 回退本地
    return self._find_user_config(device_key)
```

## 监控与日志

```python
# 日志示例
[RemoteConfig] 已获取设备配置: device_001
[RemoteConfig] 使用缓存配置: device_002
[RemoteConfig] 上报设备状态: device_001 -> online
[RemoteConfig] 获取配置失败: device_003 (HTTP 500)
[Auth] 远程配置获取失败: Connection timeout
```

## 完整集成示例

```python
# src/main.py

import asyncio
from src.infrastructure.config import get_settings
from src.infrastructure.remote_config import init_remote_config_provider
from src.infrastructure.auth import AuthService

async def main():
    settings = get_settings()

    # 1. 初始化远程配置
    remote_config = init_remote_config_provider(
        api_base_url=settings.remote_config_url,
        api_key=settings.remote_config_api_key,
        cache_ttl=300,
        refresh_interval=60,
    )

    # 2. 启动后台刷新（可选）
    if remote_config.is_enabled:
        await remote_config.start_background_refresh()
        print(f"[Config] 远程配置已启用: {settings.remote_config_url}")

    # 3. 创建认证服务
    auth_service = AuthService(
        config={"enabled": True},
        remote_config_provider=remote_config,
    )

    # 4. 设备连接时会自动获取配置
    # config = await auth_service.get_user_config("device_key")
```

## 常见问题

### Q: 远程配置和管理后台网络断开怎么办？

A: 自动回退到本地 `users.json` 配置，保证服务可用性。

### Q: 如何热更新设备配置？

A:
1. 通过管理后台修改配置
2. ESP-AI-Server 会在 `cache_ttl` 后自动刷新
3. 或调用 `remote_config.clear_cache()` 立即刷新

### Q: 如何区分不同环境的配置？

A: 通过 `REMOTE_CONFIG_URL` 环境变量指向不同的管理后台。

### Q: 支持多少设备？

A: 理论上无限制，配置按需拉取，不占用大量内存。
