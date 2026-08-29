# 插件生命周期与事件

插件不只是"被动等待 LLM 调用的工具集合"。通过**生命周期钩子**和**事件订阅**，插件可以拥有自己的后台逻辑：启动定时任务、响应设备上下线、监听微信消息等。

## 生命周期钩子

插件可以在 `plugin.py` 中定义两个可选的模块级函数：

### `on_startup()`

**插件加载成功后自动调用**（同步或 async 均可）。适合：启动后台任务、初始化连接、恢复持久化状态。

```python
# plugin.py 顶层（与 @tool 定义同级）
import asyncio

_task = None

def on_startup():
    """插件加载后启动后台循环。"""
    global _task
    _task = asyncio.create_task(my_background_loop())

async def my_background_loop():
    while True:
        await asyncio.sleep(60)
        # 周期性工作……
```

### `on_shutdown()`

**插件卸载或热重载前自动调用**。适合：停止后台任务、释放资源、保存状态。

```python
def on_shutdown():
    """插件卸载前清理。"""
    global _task
    if _task:
        _task.cancel()
        _task = None
```

::: tip 真实示例：alarm 插件
闹钟引擎的启停由生命周期钩子持有——插件加载时启动调度循环，卸载时停止：

```python
def on_startup():
    from src.use_cases.alarm_manager import get_alarm_manager
    get_alarm_manager().start()

def on_shutdown():
    from src.use_cases.alarm_manager import get_alarm_manager
    get_alarm_manager().stop()
```
:::

::: warning 注意事项
- 钩子中的异常只会记日志，**不会影响**插件的加载或卸载
- 钩子的幂等性由插件自行保证（框架不阻止重复加载）
- 当前仅**内置插件**（进程内运行）生效；沙箱插件（子进程随调用生灭）暂不支持
:::

## 事件订阅

框架在关键节点发布事件，插件可订阅并在事件发生时收到回调。

### 订阅 API

```python
from src.use_cases.sdk.events import (
    subscribe, unsubscribe, publish,
    EVENT_DEVICE_ONLINE, EVENT_DEVICE_OFFLINE,
    EVENT_SESSION_START, EVENT_SESSION_END, EVENT_WECHAT_MESSAGE,
)

def on_device_online(device_id=""):
    print(f"设备 {device_id} 上线了")

# 订阅（返回订阅 id）
sub_id = subscribe(EVENT_DEVICE_ONLINE, on_device_online, plugin_name="my_plugin")

# 退订
unsubscribe(sub_id)
```

### 可用事件

| 事件常量 | 触发时机 | 回调参数 |
|----------|---------|---------|
| `EVENT_DEVICE_ONLINE` | 设备注册成功 | `device_id` |
| `EVENT_DEVICE_OFFLINE` | 设备注销 | `device_id` |
| `EVENT_SESSION_START` | 设备唤醒（收到 start 命令） | `device_key` |
| `EVENT_SESSION_END` | 会话清理完成 | `device_key` |
| `EVENT_WECHAT_MESSAGE` | 微信回复发送成功 | `chat_id`, `text` |

### 保证

- 回调异常被捕获并记日志，**不影响**事件发布方和其他订阅者
- 协程回调自动包装为后台任务，不阻塞发布方
- `publish()` 也可以由插件主动调用，向其他订阅者广播自定义事件

::: warning 适用范围
事件系统当前仅**内置插件**（进程内运行）可用；沙箱插件的 RPC 通道尚未接入。
:::

## 典型模式：后台定时任务插件

结合生命周期钩子 + 事件订阅，实现一个"设备上线时打招呼、每小时做一次巡检"的插件：

```python
from src.use_cases.sdk.tools import tool
from src.use_cases.sdk.events import subscribe, EVENT_DEVICE_ONLINE
from src.use_cases.sdk.infrastructure import speak_to_device

_hourly_task = None
_online_sub = None

def on_startup():
    global _hourly_task, _online_sub
    _hourly_task = asyncio.create_task(_hourly_loop())
    _online_sub = subscribe(EVENT_DEVICE_ONLINE, _greet, plugin_name="greeter")

async def _greet(device_id=""):
    await speak_to_device(device_id, "欢迎回来！")

async def _hourly_loop():
    while True:
        await asyncio.sleep(3600)
        # 巡检逻辑……

def on_shutdown():
    global _hourly_task, _online_sub
    if _hourly_task:
        _hourly_task.cancel()
        _hourly_task = None
    if _online_sub:
        from src.use_cases.sdk.events import unsubscribe
        unsubscribe(_online_sub)
        _online_sub = None

@tool(description="手动触发一次巡检")
async def run_check(tool_manager=None) -> str:
    """执行一次巡检并返回结果。"""
    # ……巡检逻辑
    return "巡检完成"
```

## 相关文件

| 文件 | 说明 |
|------|------|
| `src/use_cases/sdk/events.py` | 事件系统实现 |
| `src/infrastructure/plugin_loader.py` | 生命周期钩子的调用方（加载/卸载） |
| `src/plugins/alarm/plugin.py` | 钩子真实示例（闹钟引擎启停） |
| `src/plugins/proactive_brain/engine.py` | 后台循环真实示例（主动推送引擎） |
