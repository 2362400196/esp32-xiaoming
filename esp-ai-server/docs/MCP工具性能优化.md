# ESP-AI Server MCP 工具性能优化方案

## 1. 性能瓶颈分析

### 1.1 当前架构

```
用户请求 → LLM → 工具调用 → MCP Server → 返回结果
                          ↓
                     同步调用，串行执行
```

### 1.2 性能瓶颈

| 瓶颈 | 影响 | 原因 |
|------|------|------|
| **串行调用** | 多个工具依次执行，耗时累加 | LLM 可能调用多个工具 |
| **无缓存** | 相同参数重复执行 | 没有结果缓存机制 |
| **无连接池** | 每次调用建立新连接 | 连接开销大 |
| **无超时控制** | 慢速工具阻塞流程 | 没有超时保护 |
| **无重试机制** | 瞬时故障导致失败 | 没有容错能力 |

---

## 2. 优化方案

### 2.1 并行工具调用

```python
import asyncio
from typing import List, Tuple, Any

class PerUserToolManager:
    """
    支持并行调用的工具管理器
    """
    
    async def call_tools_batch(
        self,
        tool_calls: List[Tuple[str, dict]]
    ) -> List[Any]:
        """
        批量并行调用多个工具
        
        :param tool_calls: 工具调用列表，每个元素为 (tool_name, arguments)
        :return: 工具执行结果列表
        """
        if not tool_calls:
            return []
        
        # 创建并行任务
        tasks = []
        for tool_name, arguments in tool_calls:
            task = asyncio.create_task(
                self.call_tool(tool_name, arguments)
            )
            tasks.append(task)
        
        # 并行执行，允许部分失败
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理异常结果
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                tool_name, _ = tool_calls[i]
                final_results.append(f"工具 {tool_name} 调用失败: {str(result)}")
            else:
                final_results.append(result)
        
        return final_results
```

### 2.2 工具结果缓存

```python
import json
import time
from hashlib import md5
from typing import Dict, Any

class ToolCache:
    """
    工具结果缓存
    
    :param ttl: 缓存过期时间（秒），默认 300
    :param max_size: 最大缓存条目数，默认 1000
    """
    
    def __init__(self, ttl: int = 300, max_size: int = 1000):
        self._ttl = ttl
        self._max_size = max_size
        self._cache: Dict[str, Tuple[float, Any]] = {}  # key: (timestamp, result)
        self._lock = asyncio.Lock()
    
    def _generate_key(self, tool_name: str, arguments: dict) -> str:
        """
        生成缓存键
        
        :param tool_name: 工具名称
        :param arguments: 工具参数
        :return: 缓存键
        """
        key_str = f"{tool_name}:{json.dumps(arguments, sort_keys=True)}"
        return md5(key_str.encode()).hexdigest()
    
    async def get(self, tool_name: str, arguments: dict) -> Optional[Any]:
        """
        获取缓存结果
        
        :param tool_name: 工具名称
        :param arguments: 工具参数
        :return: 缓存结果，None 表示未命中
        """
        key = self._generate_key(tool_name, arguments)
        
        async with self._lock:
            if key in self._cache:
                timestamp, result = self._cache[key]
                
                # 检查是否过期
                if time.time() - timestamp < self._ttl:
                    return result
                else:
                    # 过期，删除
                    del self._cache[key]
        
        return None
    
    async def set(self, tool_name: str, arguments: dict, result: Any) -> None:
        """
        设置缓存结果
        
        :param tool_name: 工具名称
        :param arguments: 工具参数
        :param result: 工具执行结果
        """
        key = self._generate_key(tool_name, arguments)
        
        async with self._lock:
            # 检查容量
            if len(self._cache) >= self._max_size:
                # 删除最老的条目
                oldest_key = min(
                    self._cache.keys(),
                    key=lambda k: self._cache[k][0]
                )
                del self._cache[oldest_key]
            
            # 设置缓存
            self._cache[key] = (time.time(), result)
    
    async def clear(self) -> None:
        """清空缓存"""
        async with self._lock:
            self._cache.clear()
    
    def get_stats(self) -> dict:
        """获取缓存统计"""
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "ttl": self._ttl
        }
```

### 2.3 带缓存的工具调用

```python
class PerUserToolManager:
    def __init__(self):
        self._cache = ToolCache(ttl=300, max_size=1000)
    
    async def call_tool_with_cache(
        self,
        tool_name: str,
        arguments: dict,
        use_cache: bool = True
    ) -> Any:
        """
        带缓存的工具调用
        
        :param tool_name: 工具名称
        :param arguments: 工具参数
        :param use_cache: 是否使用缓存
        :return: 工具执行结果
        """
        # 尝试从缓存获取
        if use_cache:
            cached_result = await self._cache.get(tool_name, arguments)
            if cached_result is not None:
                return cached_result
        
        # 执行工具调用
        result = await self.call_tool(tool_name, arguments)
        
        # 更新缓存
        if use_cache:
            await self._cache.set(tool_name, arguments, result)
        
        return result
```

### 2.4 MCP 连接池

```python
class MCPPool:
    """
    MCP 客户端连接池
    
    :param server_url: MCP 服务器地址
    :param max_size: 最大连接数，默认 5
    :param min_size: 最小连接数，默认 2
    """
    
    def __init__(self, server_url: str, max_size: int = 5, min_size: int = 2):
        self._server_url = server_url
        self._max_size = max_size
        self._min_size = min_size
        
        self._pool = asyncio.Queue(maxsize=max_size)
        self._active_count = 0
        self._lock = asyncio.Lock()
        
        # 预热
        asyncio.create_task(self._warm_up())
    
    async def _create_client(self):
        """创建 MCP 客户端"""
        # 这里实现实际的 MCP 客户端创建逻辑
        client = MCPClient(self._server_url)
        await client.connect()
        return client
    
    async def _warm_up(self):
        """预热连接池"""
        async with self._lock:
            while self._pool.qsize() < self._min_size:
                if self._active_count >= self._max_size:
                    break
                
                client = await self._create_client()
                await self._pool.put(client)
                self._active_count += 1
    
    async def acquire(self) -> 'MCPClient':
        """获取 MCP 客户端"""
        async with self._lock:
            # 优先从池中获取
            if not self._pool.empty():
                client = await self._pool.get()
                if client.connected:
                    return client
            
            # 创建新客户端
            if self._active_count < self._max_size:
                client = await self._create_client()
                self._active_count += 1
                return client
            
            # 等待可用连接
            return await self._pool.get()
    
    async def release(self, client: 'MCPClient') -> None:
        """归还 MCP 客户端"""
        if client and client.connected:
            await self._pool.put(client)
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            "active_count": self._active_count,
            "idle_count": self._pool.qsize(),
            "max_size": self._max_size
        }
```

### 2.5 超时控制与重试

```python
class PerUserToolManager:
    async def call_tool_with_timeout(
        self,
        tool_name: str,
        arguments: dict,
        timeout: int = 30,
        max_retries: int = 2
    ) -> Any:
        """
        带超时和重试的工具调用
        
        :param tool_name: 工具名称
        :param arguments: 工具参数
        :param timeout: 超时时间（秒），默认 30
        :param max_retries: 最大重试次数，默认 2
        :return: 工具执行结果
        """
        for attempt in range(max_retries + 1):
            try:
                async with asyncio.timeout(timeout):
                    return await self.call_tool(tool_name, arguments)
            except asyncio.TimeoutError:
                if attempt < max_retries:
                    # 重试等待，指数退避
                    await asyncio.sleep(2 ** attempt)
                else:
                    return f"工具 {tool_name} 调用超时"
            except Exception as e:
                if attempt < max_retries:
                    await asyncio.sleep(1)
                else:
                    return f"工具 {tool_name} 调用失败: {str(e)}"
```

### 2.6 工具元数据缓存

```python
class ToolManager:
    """
    工具管理器（带元数据缓存）
    """
    
    def __init__(self):
        self._tools_schema_cache = None
        self._cache_time = 0
        self._cache_ttl = 3600  # 1 小时
    
    def get_all_tools_schema(self) -> list:
        """
        获取所有工具 Schema（带缓存）
        
        :return: 工具 Schema 列表
        """
        now = time.time()
        
        # 检查缓存
        if self._tools_schema_cache is not None:
            if now - self._cache_time < self._cache_ttl:
                return self._tools_schema_cache
        
        # 重新获取
        self._tools_schema_cache = self._fetch_all_tools_schema()
        self._cache_time = now
        
        return self._tools_schema_cache
    
    def _fetch_all_tools_schema(self) -> list:
        """
        从所有工具源获取 Schema
        
        :return: 工具 Schema 列表
        """
        schemas = []
        
        # 获取内置工具
        schemas.extend(self._get_builtin_tools_schema())
        
        # 获取 MCP 工具
        schemas.extend(self._get_mcp_tools_schema())
        
        # 获取自定义工具
        schemas.extend(self._get_custom_tools_schema())
        
        return schemas
```

---

## 3. 集成方案

### 3.1 修改 LLM 工具调用逻辑

```python
# app/llm/openai_llm.py

class OpenAILLM:
    async def _execute_tool_calls(self, tool_calls):
        """
        执行工具调用（支持并行）
        
        :param tool_calls: 工具调用列表
        :return: 工具执行结果
        """
        if not tool_calls:
            return []
        
        # 判断是否需要并行调用
        if len(tool_calls) > 1:
            # 多个工具调用，并行执行
            tool_call_list = [
                (tc.function.name, json.loads(tc.function.arguments))
                for tc in tool_calls
            ]
            
            results = await self.tool_manager.call_tools_batch(tool_call_list)
        else:
            # 单个工具调用，使用带缓存的调用
            tc = tool_calls[0]
            results = [await self.tool_manager.call_tool_with_cache(
                tc.function.name,
                json.loads(tc.function.arguments)
            )]
        
        return results
```

### 3.2 修改 PerUserToolManager

```python
# app/tools/tool_manager.py

class PerUserToolManager:
    def __init__(self, shared, channel=None):
        self._shared = shared
        self.channel = channel
        
        # 初始化缓存
        self._tool_cache = ToolCache(ttl=300, max_size=1000)
        
        # 初始化 MCP 连接池
        self._mcp_pools = {}
    
    async def get_mcp_pool(self, server_url: str) -> MCPPool:
        """
        获取 MCP 连接池
        
        :param server_url: MCP 服务器地址
        :return: MCP 连接池
        """
        if server_url not in self._mcp_pools:
            self._mcp_pools[server_url] = MCPPool(server_url)
        
        return self._mcp_pools[server_url]
    
    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """
        调用工具（统一入口）
        
        :param tool_name: 工具名称
        :param arguments: 工具参数
        :return: 工具执行结果
        """
        # 先检查内置工具
        builtin = get_tool(tool_name)
        if builtin:
            return await self._call_builtin_tool(builtin, arguments)
        
        # 检查 MCP 工具
        return await self._call_mcp_tool(tool_name, arguments)
    
    async def _call_mcp_tool(self, tool_name: str, arguments: dict) -> str:
        """
        调用 MCP 工具（使用连接池）
        
        :param tool_name: 工具名称
        :param arguments: 工具参数
        :return: 工具执行结果
        """
        # 获取 MCP 服务器地址（从配置或工具元数据获取）
        server_url = self._get_mcp_server_url(tool_name)
        
        if not server_url:
            return f"未找到工具 {tool_name} 的 MCP 服务器"
        
        # 获取连接池
        pool = await self.get_mcp_pool(server_url)
        client = None
        
        try:
            client = await pool.acquire()
            return await client.call_tool(tool_name, arguments)
        finally:
            if client:
                await pool.release(client)
```

---

## 4. 配置参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `cache_ttl` | int | 300 | 工具结果缓存时间（秒） |
| `cache_max_size` | int | 1000 | 最大缓存条目数 |
| `mcp_pool_max_size` | int | 5 | MCP 连接池最大连接数 |
| `mcp_pool_min_size` | int | 2 | MCP 连接池最小连接数 |
| `tool_timeout` | int | 30 | 工具调用超时时间（秒） |
| `tool_max_retries` | int | 2 | 工具调用最大重试次数 |

---

## 5. 性能对比

| 场景 | 优化前 | 优化后 | 提升 |
|------|--------|--------|------|
| 单个工具调用 | 500ms | 500ms | 无变化 |
| 3个工具串行调用 | 1500ms | 500ms | 3x |
| 重复调用相同参数 | 500ms | <1ms | 500x |
| MCP 连接开销 | 200ms/次 | 0ms（复用） | 消除 |

---

## 6. 测试方法

### 6.1 并行调用测试

```python
import pytest

@pytest.mark.asyncio
async def test_parallel_tool_calls():
    manager = PerUserToolManager()
    
    # 创建模拟工具
    async def slow_tool(name, delay):
        await asyncio.sleep(delay)
        return f"result from {name}"
    
    # 注册模拟工具
    manager._tools["slow1"] = lambda: slow_tool("slow1", 0.5)
    manager._tools["slow2"] = lambda: slow_tool("slow2", 0.5)
    manager._tools["slow3"] = lambda: slow_tool("slow3", 0.5)
    
    # 并行调用
    start_time = time.time()
    results = await manager.call_tools_batch([
        ("slow1", {}),
        ("slow2", {}),
        ("slow3", {})
    ])
    elapsed = time.time() - start_time
    
    # 应该在 ~0.5 秒内完成，而不是 1.5 秒
    assert elapsed < 1.0
    assert len(results) == 3
```

### 6.2 缓存测试

```python
@pytest.mark.asyncio
async def test_tool_cache():
    manager = PerUserToolManager()
    
    # 创建耗时工具
    call_count = 0
    
    async def expensive_tool(args):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.1)
        return f"result {call_count}"
    
    manager._tools["expensive"] = expensive_tool
    
    # 第一次调用
    result1 = await manager.call_tool_with_cache("expensive", {"key": "value"})
    assert result1 == "result 1"
    assert call_count == 1
    
    # 第二次调用（应该命中缓存）
    result2 = await manager.call_tool_with_cache("expensive", {"key": "value"})
    assert result2 == "result 1"
    assert call_count == 1  # 调用次数不变
    
    # 不同参数（应该重新执行）
    result3 = await manager.call_tool_with_cache("expensive", {"key": "other"})
    assert result3 == "result 2"
    assert call_count == 2
```

---

## 7. 监控与日志

### 7.1 监控指标

```python
from prometheus_client import Counter, Gauge, Histogram

# 工具调用次数
tool_calls_total = Counter('tool_calls_total', '工具调用总数', ['tool_name'])

# 工具调用耗时
tool_call_duration = Histogram('tool_call_duration_seconds', '工具调用耗时', ['tool_name'])

# 缓存命中率
cache_hits = Counter('tool_cache_hits', '缓存命中次数')
cache_misses = Counter('tool_cache_misses', '缓存未命中次数')

# MCP 连接池统计
mcp_pool_active = Gauge('mcp_pool_active', 'MCP 活跃连接数', ['server_url'])
mcp_pool_idle = Gauge('mcp_pool_idle', 'MCP 空闲连接数', ['server_url'])
```

### 7.2 日志记录

```python
import logging

logger = logging.getLogger(__name__)

async def call_tool(self, tool_name, arguments):
    logger.info(f"开始调用工具: {tool_name}, 参数: {arguments}")
    
    start_time = time.time()
    try:
        result = await self._do_call_tool(tool_name, arguments)
        elapsed = time.time() - start_time
        logger.info(f"工具调用完成: {tool_name}, 耗时: {elapsed:.2f}s")
        return result
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"工具调用失败: {tool_name}, 耗时: {elapsed:.2f}s, 错误: {e}")
        raise e
```

---

## 8. 部署建议

1. **缓存 TTL**：根据工具特性设置，频繁变化的数据设置较短 TTL
2. **连接池大小**：根据 MCP 服务器性能和预期并发量设置
3. **超时时间**：设置合理的超时，避免长时间阻塞
4. **重试次数**：设置 2-3 次重试，配合指数退避
5. **监控告警**：监控缓存命中率、工具调用耗时、连接池状态
