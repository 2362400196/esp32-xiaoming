---
name: esp-ai-server
description: >
  esp32-xiaoming 仓库服务端（esp-ai-server，FastAPI 语音 AI 服务器）的开发技能。
  凡是涉及 esp-ai-server 的任何工作都必须使用本技能：修改 API/路由、插件开发、
  pipeline/会话引擎、数据库、微信集成、设备 WS 协议、写测试、排查报错——
  即使用户只说"改一下服务端""加个功能""修个 bug"。加载后可跳过项目分析直接动手。
---

# esp-ai-server 服务端开发

本技能让你免于重新分析项目。先读本文件，再按任务读对应 reference。

## 环境与命令（Windows Git Bash）

- 仓库根：`C:\Users\23624\Desktop\esp\esp32-xiaoming`
- 服务端：`esp-ai-server/`（Python 3.10，venv 在 `esp-ai-server/.venv`）
- **运行测试必须从 esp-ai-server 目录**：
  ```bash
  cd esp-ai-server && .venv/Scripts/python.exe -m pytest tests/ -q -p no:cacheprovider
  ```
- 全量约 2700 用例、~3 分钟；当前基线 0 failed——**提交前必须保持全绿**
- 固件在 `esp-ai-idf-client/`（ESP-IDF，一般不动）；**文档站在 `vuepress-starter/`**（功能变更需同步更新对应页面，`npm run docs:build` 验证）

## 架构速览（分层与数据流）

```
设备 WS ─→ interfaces/websocket_handler.py   （鉴权：JWT/key/MAC 校验）
        ─→ interfaces/ws_session_handler.py  （主消息循环、唤醒、ASR 会话）
        ─→ use_cases/session.py              （会话编排：ASR 循环/看门狗/中断）
        ─→ use_cases/pipeline.py             （4-Worker：LLM→分句→TTS→发送）
                                     └→ interfaces/llm_gateways.py / tts_gateways.py
HTTP  ─→ infrastructure/routes/*.py ─→ use_cases 或 repository ─→ SQLite(aiosqlite)
插件   ─→ infrastructure/plugin_loader.py 加载；工具注册表在 use_cases/tools_system.py
```

- 分层：`domain`（实体/异常）→ `use_cases`（业务）→ `infrastructure`（web/db/路由/插件宿主）→ `interfaces`（WS 处理器、网关）。SDK 在 `use_cases/sdk/`，内置插件在 `src/plugins/`
- 状态机：`use_cases/session_fsm.py`（IDLE/LLM/TTS/ASR）；会话生命周期与轮次防串扰逻辑在 ws_session_handler（`_wake_audio_round`、`_pending_out_audio_over`、unregister 属主校验——**改 WS 逻辑前必须理解这三者**，见 references/conventions.md）
- 数据库：SQLAlchemy 2.0 声明式，模型在 `infrastructure/db/models/`，仓储在 `db/repositories/`。**加列必须走 `db/migrations/schema.py` 的 `_ensure_column` 模式**，禁止 DROP TABLE
- 微信：单例 `wechat_bot.get_or_create_bot()`（绝不允许直接 `WeChatBot(config)`，双实例会 -14 互踢）；消息回调在 `plugins/wechat_bot/handler.py`；绑定走配对码（**禁止任何形式的自动绑定**）

## 硬性规则（违反即事故，都有历史教训）

1. **错误处理**：路由只 `raise HTTPException`，由 web.py 全局 handler 收口；禁止 `except: return {"code":1,...}`；禁止裸 `except: pass`（要记日志或显式 suppress）
2. **异步纪律**：async 函数里禁止同步 DB/文件 IO/大 JSON 解析——用 `asyncio.to_thread`；fire-and-forget 一律 `task_manager.background_task`，禁止裸 `asyncio.create_task`
3. **插件工具注册**：插件只 import SDK（`from src.use_cases.sdk.tools import tool`）；获取插件模块一律 `plugin_loader.get_plugin_module(name)`——`importlib.import_module("src.plugins.X")` 会二次实例化、工具注册冲突（踩过）
4. **tool() 装饰器依赖真实类型注解**推断 schema：插件文件**禁止** `from __future__ import annotations`
5. **不要全局 patch `asyncio.sleep`**（测试中也不行）——连接池 cleanup loop 会忙等死循环卡死整个测试进程（踩过）
6. **安全不变量**：微信通道禁用 execute_lua 等设备控制工具；refresh 查库校验 is_active/token_version；zip 解压后大小上限；上传图标扩展名+magic 白名单；MAC 入库必须过 `_is_valid_mac`
7. **关机顺序**（web.py lifespan）：停微信 → cancel_all 后台任务 → 关设备会话（Session.close 里 aclose LLM/TTS 网关）→ 关网关池 → 关线程池。改任何一段前先读现状——顺序错了会出现"离线通知打在已关闭的 httpx 上"的报错刷屏
8. **测试基线**：`tests/test_web.py` 会加载已安装插件污染 `_service_registry`（test_ws_session_handler 有隔离 fixture）；`test_device_repository.py` 曾因 GBK 乱码损坏——**所有文件 UTF-8，写中文注释**

## 按任务读对应 reference

| 任务类型 | 先读 |
|---------|------|
| 加/改 HTTP 接口、设备绑定、鉴权 | references/conventions.md §路由与鉴权 |
| 加数据库字段/表、写仓储 | references/conventions.md §数据库 |
| 插件相关（新工具、SDK、生命周期钩子、事件） | references/plugins.md |
| pipeline/会话/WS 时序、打断与轮次 | references/architecture.md |
| 排查奇怪报错（乱码/挂起/GC 报错/双实例） | references/gotchas.md |
| 用户可见功能变更 | 同步更新 `vuepress-starter/docs/` 对应页 |

## 文档

- 审查与修复记录：`esp-ai-server/docs/`（server-code-audit / server-audit-round2 / plugin-architecture-review）
- 面向用户的文档站：`vuepress-starter/docs/`（guide=用户，dev/server=服务端开发，plugin=插件开发；plugin-sdk.md 是 SDK API 参考）
