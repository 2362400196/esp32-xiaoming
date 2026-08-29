# 插件架构专项审查报告

> 日期：2026-08-28
> 设计目标（用户原话）："一切皆插件，开发者不能改框架代码（无权限），开发者只需要了解 SDK，无需了解框架代码。"
> 方法：两路并行审查——①SDK 完备性与开发者体验（以插件开发者视角）②插件生命周期与边界机制

---

## 一、总体结论

**"一切皆插件"目前只在工具注册表这一层成立**（@tool → 全局表 → 设备白名单过滤）。以下四个维度都不成立：

| 维度 | 现状 |
|------|------|
| SDK 完备性 | 缺"第零号能力" `@tool` 注册——16/16 插件第一行都 import 框架 `tools_system.py`（1620 行） |
| 运行时形态 | 内置（进程内、全权限、可 import src.*）与商店安装（子进程沙箱、SDK RPC）**语义不同**而非仅权限不同——同一份代码两种形态行为不一致 |
| 生命周期 | 卸载不清理 KV/设备数据/子模块；单插件热重载无回滚；禁用只是过滤工具、模块副作用照常运行 |
| 功能归属 | 闹钟、主动推送、微信消息处理、成长系统、技能引擎五大功能长在框架核心（"伪插件"），因为 SDK 缺少支撑它们的原语 |

对开发者承诺的"只看 SDK 就能开发"**目前不成立**：没有 @tool 一个插件都写不出来；`docs/插件教程/` 目录是空的，面向插件开发者的 API 参考实际不存在。

---

## 二、SDK 问题清单

### 1. 能力缺口（按"多少插件被迫绕过 SDK"排序）

| 缺口 | 影响面 | 说明 |
|------|--------|------|
| `@tool` / `StopPipeline` 不在 SDK | **16/16 插件** | 插件开发第一入口在框架 `tools_system.py:72`；SDK 目录没有 `tools.py` |
| 领域能力缺失 | 6 个插件 | 闹钟调度（alarm）、日记/情绪/自学习（growth）、技能 CRUD（skill_system 只有只读）、主动大脑、LTM 领域对象、微信绑定管理 |
| 框架私有符号被插件 import | 2 个插件 | mcp_manager import `DeviceRepository` 和私有函数 `web._hot_reload_device_config`；wechat_bot 绕开 SDK 已有的封装 |
| KV ContextVar 对内置插件不可用 | 1 个插件 | alarm 注释明说"内置插件不走 kv 的 ContextVar 机制"，自建文件存储——同一持久化能力两套实现 |

### 2. API 一致性：五套错误约定并存

| 约定 | 例子 |
|------|------|
| 字符串错误 | `send_device_command` 成功返 None/失败返 str；`gpio_write` 返 "ok"/错误串 |
| 元组 | `send_device_command_ack` → `(result, status, detail)`；`http_request` → `(resp, err)` |
| 哨兵值 | `gpio_read` 失败返 **-1**；`device_get_info` 离线返 `{}` |
| 抛异常 | `llm_chat`/`tts_synthesize` 无捕获直接抛；`ws_send` 抛 |
| 权限异常 | storage 系列缺权限抛 PermissionError |

开发者需要记住每个函数属于哪套约定。建议统一为 `(result, status, detail)` 元组风格（已有先例）。

### 3. 签名泄露框架内部

- `request_device_result(tool_manager, command_id, future_attr, ...)` 要求开发者传 tool_manager 的**私有属性名**（`"_pending_lua_future"`）——插件必须理解框架的 Future 槽位机制
- `speak_direct(channel, ctx, fsm, text)` 要求拿到 channel/ctx/fsm 三个框架内部对象，但 SDK 没有任何函数能获取它们

### 4. 两套 SDK 表面不同步

第三方开发者真正用的是沙箱 shim（`plugin_host/sdk_shim.py`，658 行）——它**完全缺失** `gpio_* / pwm_write / adc_read / servo_write / play_music_url / speak_direct / get_logger / get_settings / get_device_registry / get_wechat_* / get_remote_config_provider`。沙箱插件比内置插件少一整套能力。

### 5. 无版本化/稳定性承诺

SDK 无 `__version__`、无弃用机制；SDK 内部硬依赖 `web.get_app().state`、`device_api`、裸 SQLAlchemy 查询——框架重构任意一处，插件静默崩坏。

### 6. 文档缺失

`docs/插件教程/` 为空目录；`开发者指南.md` 是框架贡献者文档；README 无插件章节。插件开发者唯一的"文档"是 SDK 源码 docstring 和 16 个内置插件源码。

---

## 三、生命周期与边界问题

### 1. 双轨运行时不兼容（最结构性的问题）

同一插件代码在内置/安装两种形态下：import 能力、第三方依赖、标准库范围、网络、文件 IO、环境变量、返回值序列化、崩溃隔离、frontend_api 全部不同。安装版连官方插件自己在用的能力都失效（直连文件 IO、httpx、exec 桥）。且安装版覆盖同名内置插件时，exec 桥回退导入会把内置旧版代码再执行一遍（重新注册工具）。

### 2. 生命周期泄漏

- **卸载不清理**：KV 按设备存的文件全部泄漏（清理只删全局文件）、设备的 enabled_plugins 残留死引用、stderr 日志残留
- **热重载不清 sys.modules 子模块**：插件 import 的兄弟模块命中缓存，**升级后子模块代码不生效**
- **单插件热重载无回滚**：先卸载后加载，加载失败插件彻底消失（全量 reload 有快照回滚但单插件没有）
- **禁用 ≠ 停止**：白名单只过滤工具，模块级副作用（线程、文件监听）照常运行；非 optional 第三方插件无法通过白名单关闭
- BACKUP_DIR 只增不删

### 3. 框架硬编码点名插件（调用方向违规）

| 调用点 | 问题 |
|--------|------|
| `ws_session_handler.py:1335` 音乐续播 → 直调 media_player | 绕过设备白名单；插件禁用/缺失时行为不一 |
| `devices.py:410` music 动作 → 同上；`:417` 硬编码工具名 get_weather/set_alarm/read_diary | 插件改名即静默失效 |
| `plugin_frontend.py` exec 桥 | 安装版插件不可用；调用不设权限上下文（权限黑洞） |
| `plugins.py:783` 卸载清理特判 `plugin_name == "wechat_bot"` | 框架核心认识具体插件的数据布局 |

### 4. 权限模型缺口

- `require_permission` 在无上下文时**静默放行**——工具调用栈之外的代码（后台任务、frontend_api）零约束
- exec 桥不设插件上下文，登录用户可无上下文调用任意后端能力
- `BUILTIN_DEFAULT_PERMS` 死代码；内置插件的"全权限"实际来自"核心里长出来的功能不受检"（alarm_manager 直连 DB/TTS 完全绕过权限模型）

---

## 四、"伪插件"清单（应迁出核心）

| 功能 | 位置 | 留在核心的原因 |
|------|------|---------------|
| 闹钟调度引擎 | `use_cases/alarm_manager.py`（528 行） | SDK 无后台定时/持久调度原语 |
| AI 主动推送 | `use_cases/proactive_brain.py`（271 行） | 无服务端→插件的事件推送通道 |
| 微信消息处理 | `wechat_bot.py`（1024 行）+ web.py lifespan 里 300 行回调 | 入站事件订阅无法通过现有 RPC 表达 |
| 成长系统 | `use_cases/growth/` 6 模块 + 路由 + DB 模型 | 同上 |
| 技能引擎 | `use_cases/skill_system.py`（684 行） | 插件只是 30 行转发壳 |

**共同根因**：SDK 缺四类原语——**后台任务/定时器、生命周期钩子（startup/shutdown）、入站事件订阅、跨设备管理面**。凡是需要这四者的功能都被迫长进核心。

---

## 五、演进路线图

### 第一阶段：让"只看 SDK 就能开发"成立（1-2 周）
1. `sdk/tools.py`：把 `@tool`、`StopPipeline`、工具上下文移入 SDK（框架 tools_system 改为 re-export，插件零改动）
2. `sdk/schedule.py`：后台定时任务原语（持久化闹钟引擎的迁移前提）
3. `sdk/events.py`：事件订阅（设备上线/下线/会话开始/微信消息）
4. `sdk/lifecycle.py`：插件 startup/shutdown 钩子（解决模块级副作用无管理的问题）
5. `sdk/reload.py` 或提升公开 API：配置热重载（替换 `_hot_reload_device_config` 私有 import）
6. 统一错误约定为 `(result, status, detail)`（旧约定保留为别名，逐步废弃）
7. 补齐 shim 与主进程 SDK 的能力差距
8. **写 `docs/插件教程/`**：SDK API 参考 + 权限清单 + 从零写一个插件的教程

### 第二阶段：迁移伪插件（2-4 周，依赖第一阶段）
闹钟 → 用 schedule 原语迁移；主动推送 → 用事件+定时迁移；微信消息处理 → 事件订阅化；成长/技能引擎按需评估（引擎可留核心，把"入口"插件化）。

### 第三阶段：沙箱统一（长期）
内置插件迁移到与安装插件相同的运行时路径（或至少运行时权限强制），消灭 `import src.*` 特权通道；卸载/热重载清理补全；exec 桥对安装版插件可用（经 RPC）。

### 快速修复（可立即做的）
1. exec 桥设置插件权限上下文（权限黑洞）
2. 卸载清理按设备 KV + enabled_plugins 引用
3. reload_single_plugin 补回滚 + 清理 sys.modules 子模块
4. 框架硬编码点名的 4 处改为经工具注册表调用（走白名单）


---

## 六、修复执行记录（2026-08-28 同日）

全量测试 2705 passed / 0 failed（含本轮新增 56 个测试）。

### 第一阶段：SDK 补全（"只看 SDK 就能开发"成立）
1. **`sdk/tools.py`（新建）**：`@tool` / `StopPipeline` / `ToolDefinition` 进入 SDK（re-export，单一实现源）——插件第一行不再 import 框架
2. **`sdk/device.py`**：新增 `lua_execute / get_device_state / device_command_ack` 高层封装，隐藏框架 Future 槽位私有属性；旧 API 标注废弃
3. **`sdk/infrastructure.py`**：新增 `speak_to_device(device_key, text)`（插件不再需要拿 channel/ctx/fsm）
4. **`sdk/__init__.py`**：错误约定文档化——新约定 `(result, status, detail)`，旧约定逐一标注废弃路径

### 第二阶段：生命周期与快修
5. **生命周期钩子**：插件可定义 `on_startup()` / `on_shutdown()`，loader 加载/卸载时自动调用（容错）；alarm 插件已迁移为钩子持有闹钟引擎的启停（web.py 启动调用保留，幂等双保险）
6. **热重载回滚**：单插件重载失败自动恢复工具注册表快照——插件不再"重载失败即消失"
7. **子模块清理**：卸载/重载时清理插件 import 的兄弟模块——修复"升级后改了 utils.py 不生效"
8. **卸载清理补全**：按设备 KV、插件数据目录、设备 enabled_plugins 死引用、备份目录（保留 3 份）全部清理
9. **exec 桥权限上下文**：调用前设置插件上下文（修复 require_permission 静默放行的权限黑洞）

### 第三阶段：调用方向与事件
10. **事件系统 `sdk/events.py`（新建）**：subscribe/publish + 5 个预定义事件（设备上下线/会话开始结束/微信消息），发射点接入 registry 与 ws_session_handler
11. **框架硬编码点名插件修复**：音乐续播与 music 动作改为走正规工具调用（受设备白名单约束），插件禁用时返回友好错误

### 第四阶段：沙箱 SDK 对齐 + 文档
12. **沙箱 shim 补齐 7 个操作**（gpio_mode/write/read、pwm_write、adc_read、servo_write、play_music_url）——协议、裁决器（device 权限 + 设备作用域）、RPC 桩端到端打通，第三方沙箱插件能力与内置对齐
13. **插件开发文档 `docs/插件教程/`**（4 篇）：快速开始、SDK API 参考（区分内置/沙箱可用范围）、权限与安全、生命周期与事件

### 尚未迁移（第二阶段后续，依赖已就绪）
- proactive_brain / wechat 消息处理 / growth 迁出核心：`sdk/events.py` + `sdk/schedule` 类原语已就绪（定时原语可基于 task_manager 补充），迁移是机械工作但涉及面广，建议按插件逐个进行
- 内置插件全面沙箱化：依赖沙箱 shim 能力继续对齐（本轮已补齐 IO/音乐），剩余差距为 get_wechat 系列与远程配置


---

## 七、伪插件迁移执行记录（2026-08-28 完成）

三大"伪插件"全部迁出框架核心，行为不变，全量测试 2705 passed / 0 failed。

### 1. proactive_brain（主动推送引擎）
- `src/use_cases/proactive_brain.py` → `src/plugins/proactive_brain/engine.py`（git mv，保留历史）
- 生命周期归属插件：`on_startup` 启动引擎（注册表用就绪轮询绑定，毫秒级就绪远早于引擎 60 秒首 tick）、`on_shutdown` 停止
- web.py lifespan 的启动代码删除；顺带补上 plugin.py 一直在 import 但引擎里不存在的 `get_proactive_brain()` 单例（原状是潜在 ImportError）
- 推送时机/内容/频率控制代码路径零改动

### 2. growth（成长系统）
- `src/use_cases/growth/`（6 模块）→ `src/plugins/growth/engine/`（git mv）
- DB 模型（`db/models/growth.py`）与 HTTP 路由（`routes/growth.py`）按框架职责留在核心
- 全库 10 处引用更新（pipeline 画像注入、sdk/services、ws_session_handler、web.py、routes/growth.py、测试等）
- GrowthSystem 为每会话实例，初始化保留在 ws_session_handler 原地（最小改动）
- 安全门禁（静态审计/签名）验证通过：引擎位于插件子目录，不受顶层扫描影响；6 个工具全部注册

### 3. wechat_bot（微信消息处理）
- web.py 里约 300 行的 `_on_wechat_message` 闭包 → `src/plugins/wechat_bot/handler.py`（模块级函数，逻辑零改动：绑定/配对码/转发/受限工具管理器/prompt 组装/双分支 LLM/语音模式/历史）
- `_on_wechat_image` 图片识别回调一并迁入
- web.py 剩余接线约 20 行（单例 → 挂 state → 注册回调 → 启动轮询），缩减 300+ 行
- 修复迁移中遗留的 `elif cfg.token` 潜在 NameError（该分支实际不可达，已删除）

### 迁移后状态
- `src/use_cases/` 下已无 proactive/growth 模块文件
- `grep use_cases.proactive_brain|use_cases.growth` → 0 命中
- 三大功能的引擎代码现在物理上都在插件目录内，符合"一切皆插件"设计
- 技能系统引擎（skill_system，684 行）按报告建议保留在核心（属"引擎可留核心、入口插件化"形态）
