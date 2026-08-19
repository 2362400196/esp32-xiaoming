# MCP 工具集成

## 概述

系统通过 **MCP（Model Context Protocol）** 协议集成外部工具服务器，允许设备在对话过程中调用远端工具。客户端基于 `fastmcp` 实现，每个 MCP 服务器对应一个独立的客户端实例，通过连接池复用连接。工具体系在内置工具与 MCP 工具之上叠加了缓存、熔断、多级禁用等机制，形成共享工具管理器与每用户工具管理器两层结构。

## 核心组件

| 类 | 职责 |
|---|---|
| `StopPipeline`（Exception） | 工具调用终止管道信号 |
| `ToolDefinition` | 工具定义，`to_openai_schema()` 生成 OpenAI 工具 schema |
| `@tool` 装饰器 | 从函数签名自动生成参数 schema（int/float/bool/list/dict 映射） |
| `auto_discover()` | 扫描 `src/use_cases` 及 `custom/` 子目录自动注册工具 |
| `ToolCache` | TTL=300s，max_size=1000，MD5 key（`tool_name:args_json`） |
| `CircuitBreaker` | 熔断器，CLOSED/OPEN/HALF_OPEN 状态机 |
| `CircuitBreakerManager` | 单例管理熔断器 |
| `MCPClient` | 单 MCP 服务器客户端（fastmcp） |
| `MCPPool` | MCP 连接池（asyncio.Queue，max_size=5/min_size=2） |
| `ToolManager` | 共享工具管理器（内置工具 schema 缓存） |
| `PerUserToolManager` | 每用户工具管理器（含 MCP、缓存、熔断、disabled 机制） |

## MCP 配置格式

设备表 `mcp_servers` 为 JSON 列，记录该设备可用的 MCP 服务器清单，格式如下：

```python
{
    "server_name_1": {
        "url": "http://...",
        "headers": {"k": "v"},
        "auth": {"Authorization": "Bearer <token>"}   # auth 为 dict，与原 headers 合并
    },
    "server_name_2": {"url": "..."}
}
```

每个服务器条目以服务器名为键，`url` 为必填，`headers` 与 `auth` 为可选（`auth` 为 dict 类型，与原 `headers` 合并后作为请求头）。配套的禁用配置在 `DeviceModel` 中定义：

| 字段 | 类型 | 说明 |
|---|---|---|
| `disabled_mcp_servers` | `list[str]` | 禁用的服务器名，整服务器跳过 |
| `disabled_mcp_tools` | `dict[str, list[str]]` | `{server_name: [tool_name, ...]}`，按服务器禁用工具 |

## 并行初始化

`initialize_mcp` 中通过 `asyncio.gather` 并行初始化所有服务器：

```python
if servers:
    await asyncio.gather(*[_init_single_server(s) for s in servers], return_exceptions=True)
```

`return_exceptions=True` 让单个服务器初始化失败不影响其他服务器。`_init_single_server(server_config)` 在启用连接池分支下的流程如下：

1. 创建 `MCPPool(url, name, headers, auth, max_size=5, min_size=2)`
2. `await pool.initialize()`，预热 `min_size` 个连接
3. 创建熔断器 `CircuitBreaker(name="mcp_{name}", failure_threshold=5, recovery_timeout=60, half_open_max_calls=3)`
4. `client = await pool.acquire()`
5. `all_schemas = client.get_tools_schema()`
6. 过滤 `disabled_tools`：将 `disabled_tools.get(name, [])` 中的工具从 schema 列表移除
7. 建立 `_mcp_tool_map[func_name] = (name, pool)`
8. `await pool.release(client)`

性能优化注释指出，串行初始化每个服务器需 200-800ms，N 个服务器总耗时为 `N*200-800ms`；并行化后降为 `max(200-800ms)`，初始化时间不再随服务器数量线性增长。

## 双超时机制

工具调用采用外层与内层双重超时，两层各司其职：

| 层级 | 位置 | 超时 | 说明 |
|---|---|---|---|
| 外层 | `PerUserToolManager.call_tool`（tools_system.py:997） | 15s（`tool_timeout` 默认） | `asyncio.wait_for(self._call_tool_internal(...), timeout=15)` |
| 内层 | `MCPClient.call_tool`（tools_system.py:551） | 14s | `asyncio.wait_for(self._client.call_tool(...), timeout=14.0)` |

内层比外层短 1s，留出余量给重连逻辑。内层超时后主动 `disconnect()`，若错误信息含 `"not connected"` 则重连一次再试，重试仍受 14s 超时约束。这种设计避免了内层超时被外层提前打断，让重连有机会在剩余的 1s 窗口内完成。

## 连接池机制

`MCPPool` 基于 `asyncio.Queue` 实现，`max_size=5`、`min_size=2`。`initialize()` 时预热 `min_size` 个连接，避免首次调用时才建立连接的延迟。

- `acquire()` 返回一个空闲 `MCPClient`，池空时阻塞等待
- `release(client)` 归还客户端到队列；池已满则 `disconnect` 该客户端并减计数，防止连接泄漏
- `_call_mcp_with_circuit_breaker`（line 960）采用 `try/finally` 保证归还：

```python
try:
    client = await pool.acquire()
    return await client.call_tool(...)
finally:
    await pool.release(client)
```

泄漏防护贯穿整个调用链：`MCPClient.call_tool` 超时或异常时 `await self.disconnect()`；`PerUserToolManager.cleanup()` 关闭所有 pool、清空 client、清空熔断器；`MCPPool.close()` 取出所有 client 逐一 `disconnect`。

## 熔断器

`CircuitBreaker` 实现三态状态机，对每个 MCP 服务器独立计数：

```
CLOSED ── 失败达 failure_threshold ──> OPEN
  ^                                     │
  │ 探测成功                             │ recovery_timeout 到期
  │                                     v
HALF_OPEN <────────────────────────── OPEN
  │
  │ 探测失败
  v
OPEN
```

| 参数 | 值 | 说明 |
|---|---|---|
| `failure_threshold` | 5 | CLOSED 状态下连续失败 5 次后熔断 |
| `recovery_timeout` | 60 | OPEN 状态持续 60s 后进入 HALF_OPEN |
| `half_open_max_calls` | 3 | 半开状态最多允许 3 个探测请求 |

`CircuitBreakerManager` 以单例形式管理所有熔断器，按服务器名索引。熔断器包裹在 `_call_mcp_with_circuit_breaker` 的调用路径上，OPEN 状态下直接拒绝请求，避免对故障服务器持续施压。

## 工具缓存

`ToolCache` 用于缓存工具调用结果，减少对 MCP 服务器的重复请求：

| 配置项 | 值 |
|---|---|
| TTL | 300s（5 分钟） |
| max_size | 1000 |
| key | `MD5(f"{tool_name}:{args_json}")` |

缓存命中时直接返回结果，跳过熔断器与超时机制。这意味着缓存未过期前，即使底层服务器已熔断，相同参数的调用仍能正常返回。

## 多级禁用机制

系统提供多个粒度的工具禁用能力，覆盖从服务器到运行时的不同场景：

| 层级 | 位置 | 行为 |
|---|---|---|
| 服务器级 | `initialize_mcp` | `if name in disabled_servers: continue`，整服务器跳过 |
| 工具级（按服务器） | `_init_single_server` | 获取 schema 后过滤 `disabled_tools.get(name, [])` |
| 工具级（全局黑名单） | `PerUserToolManager.__init__` | 接收 `disabled_tools: list[str]`，`get_all_tools_schema()` 合并 schema 后过滤黑名单 |
| 运行时禁用 | `_call_tool_internal` | `if tool_name in self._disabled_tools: return "已被管理员禁用"` |
| 模块级全局禁用 | `disable_tool(name)` / `enable_tool(name)` / `set_disabled_tools(set)` | 操作 `_disabled_global` |

服务器级与工具级在初始化阶段生效，影响 schema 列表；全局黑名单影响 schema 合并结果；运行时禁用在调用入口拦截；模块级全局禁用作用于进程范围，所有 `PerUserToolManager` 实例共享。

## 调用链路

`call_tool` 的完整调用链如下：

```
PerUserToolManager.call_tool(name, args, use_cache=True, timeout=15, max_retries=1)
  │
  ├─ ToolCache.get (命中则直接返回)
  │
  └─ asyncio.wait_for(_call_tool_internal, timeout=15)
       │
       ├─ if builtin: 调用内置函数
       │     (注入 tool_manager / channel / ctx / fsm)
       │
       └─ elif in _mcp_tool_map: _call_mcp_with_circuit_breaker
            │
            └─ CircuitBreaker.call(_do_call)
                 │
                 ├─ pool.acquire → client.call_tool(name, args) → pool.release
                 │
                 └─ (内层 asyncio.wait_for timeout=14s)
```

内置工具与 MCP 工具走不同分支：内置工具直接调用 Python 函数并注入依赖；MCP 工具经熔断器包裹后从连接池获取客户端调用。两条分支的结果都会回写到 `ToolCache`，下次相同参数调用直接命中缓存。
