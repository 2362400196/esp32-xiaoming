# 插件系统

设计目标：一切皆插件；开发者只 import SDK（`src/use_cases/sdk/`），不改框架代码。

## SDK 能力地图（src/use_cases/sdk/）

| 模块 | 关键 API |
|------|---------|
| `tools.py` | `@tool` / `StopPipeline` / `ToolDefinition`（插件第一入口，re-export 自 tools_system） |
| `device.py` | `send_device_command`、**`lua_execute` / `get_device_state` / `device_command_ack`**（推荐，隐藏 future 机制）、`request_device_result`（底层，已废弃标注） |
| `events.py` | `subscribe/unsubscribe/publish` + `EVENT_DEVICE_ONLINE/OFFLINE/SESSION_START/SESSION_END/WECHAT_MESSAGE` |
| `infrastructure.py` | `speak_to_device(device_key, text)`（主动播报，勿用废弃的 speak_direct）、`get_device_registry` |
| `storage.py` | `kv_*`（按设备隔离、原子写、进程锁）、`plugin_data_*`（文件持久化，防路径穿越） |
| `io.py` / `music.py` / `http.py` / `services.py` / `ws.py` / `utils.py` | GPIO/PWM/ADC/舵机、play_music_url、http_request、llm_chat/tts_synthesize、ws 三件套、工具函数 |
| `_plugin_helpers.py` | 兼容导出层（旧导入路径），与 sdk/ 同源 |

错误约定详见 `sdk/__init__.py` 顶部文档（新约定 `(result, status, detail)`）。

## 生命周期

- 插件可定义模块级 `on_startup()` / `on_shutdown()`（同步/async 均可，异常只记日志）——loader 加载成功/卸载前调用（仅内置插件生效，沙箱插件跳过）
- 真实示例：alarm 插件（钩子持有闹钟引擎启停）；主动推送引擎在 `plugins/proactive_brain/engine.py`（on_startup 启动后台循环）
- 卸载/重载会清理：工具注册、sys.modules 主模块与子模块、KV、设备 enabled_plugins 引用

## 双运行时（重要差异）

| | 内置插件（src/plugins/） | 安装插件（data/plugins/installed/） |
|---|---|---|
| 加载 | 进程内 exec_module（合成模块名 `esp_ai_plugins_*`，已注册进 sys.modules） | 子进程沙箱 + JSON 行 RPC |
| import src.* | 允许 | 拒绝（只能走 SDK 桩） |
| 权限 | manifest 声明 + SDK 入口 require_permission | 另有 import 钩子/audit hook/裁决器 |
| frontend_api exec 桥 | 可用 | 不可用（无进程内模块） |
| 生命周期钩子/事件 | 生效 | 暂不生效 |

## 高频坑（全部踩过）

1. **二次实例化**：任何代码要拿插件模块，一律 `plugin_loader.get_plugin_module(name)`；直接 `importlib.import_module("src.plugins.X.plugin")` 会重复执行 @tool、撞"插件不允许覆盖系统工具"
2. **tool() 的 builtin 判定**：靠 sys.modules 解析模块路径 + `esp_ai_plugins_*` 模块名前缀兜底；新增加载路径时两处都要顾
3. **CORE_TOOLS**：常驻 LLM schema 的工具白名单（tools_system.py），高危工具（execute_lua）不得加入；`DANGEROUS_TOOLS` + `dangerous_tools_enabled=False` 可按通道禁用（微信通道已禁用设备控制四件套）
4. **沙箱 shim**（plugin_host/sdk_shim.py）：沙箱插件的真 SDK。新增主进程 SDK 能力时需同步 protocol.py（op 定义）→ adjudicator.py（处理器+权限）→ sdk_shim.py（RPC 桩）三处，缺失即"内置能用、安装即坏"
5. **框架不要硬编码点名插件**：音乐续播等走 `tool_mgr.call_tool("play_music", ...)`（受设备白名单约束），不要直接 import 插件函数
6. **KV 清理**：按设备存于 `data/plugins/kv/{device_id}/{plugin_id}.json`——卸载/解绑清理时必须 glob 设备目录，只删全局文件是 bug（踩过）
7. **微信绑定**：`wechat_binding.create_pairing_code/consume_pairing_code`；任何"未绑定自动绑到 registry[0]"的写法都是 P0 漏洞回归
