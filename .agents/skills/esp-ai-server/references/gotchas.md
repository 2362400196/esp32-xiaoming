# 历史事故与排查指南

这些坑都真实踩过并修复过。遇到类似症状先对照本表，不要重新分析。

## 测试挂起 / 事件循环卡死

- **症状**：pytest 卡在某个用例不动、CPU 飙升
- **原因 1**：全局 patch `asyncio.sleep`（如 `patch("...asyncio.sleep", new=AsyncMock())`）——连接池 `_cleanup_loop` 的 `sleep(60)` 变忙等死循环
- **原因 2**：mock 的 `create_session` 缺 `tool_manager=None` 形参
- **原因 3**：测试触达真实 `data/espai.db` 或真实已安装插件（data/plugins/installed/）
- **处置**：pytest 分块二分定位；`test_tts_gateways.py::TestCreateSession::test_create_session_retry_then_fail` 是历史案例（禁用池 + 移除 sleep patch 后修复）

## 测试顺序依赖 / 状态污染

- **症状**：单独跑过、组合跑挂（典型：test_web.py 之后 test_ws_session_handler 挂 3 个）
- **已知源**：test_web.py lifespan 加载已安装插件 → `plugin_loader._service_registry` 全局污染 → 会话初始化意外走插件网关回退路径
- **处置**：参照 test_ws_session_handler.py 的 `_isolate_service_registry` autouse fixture

## 'Event loop is closed'（进程退出时 SSL transport GC 报错）

- **原因**：AsyncOpenAI / TTS WS 等 SSL 连接未被关闭，GC 在已关循环上调 `__del__`
- **处置**：确认关闭链路完整——`OpenAILLMGateway.aclose()`、`VolcEngineTTSGateway.aclose()`、`Session.close()` 释放、web.py shutdown 三阶段顺序（见 architecture.md）。**每次新增"持有连接的类"都要配 aclose 并接入关闭链路**

## 工具注册冲突（"插件不允许覆盖系统工具"）

- **原因**：插件模块被二次实例化（importlib.import_module 直捣 src.plugins）或 sys.modules 注册缺失导致 builtin 误判
- **处置**：统一走 `plugin_loader.get_plugin_module(name)`；loader 必须 `sys.modules[module_name] = module` 后再 exec_module

## 微信 -14 session timeout / token 被清

- **原因**：两个 WeChatBot 实例用同一 token 各自轮询（历史上 web.py 与 sdk/infrastructure.py 各建过一个）
- **处置**：只用 `wechat_bot.get_or_create_bot()` 单例；新增持有 bot 的代码必须走它

## 中文乱码（GBK mojibake）

- **症状**：文件里出现 `瀹㈠巺鐨勮澶?` 类乱码、字符串引号被吃
- **原因**：UTF-8 文件被按 GBK 读写
- **处置**：新建/编辑文件显式 UTF-8；`text.encode('gbk').decode('utf-8', errors='replace')` 可试还原（引号丢失需手工补）；提交前 `ast.parse` 检查

## 关机报错刷屏

- **症状**：Ctrl+C 后出现 httpx.ReadError、`Exception in thread stdout_*`
- **原因**：后台任务（离线通知等）在资源关闭后才执行；沙箱 stdout 线程往已停循环投递
- **处置**：web.py shutdown 三阶段顺序 + supervisor stdout 线程吞 RuntimeError（已修）；新增后台任务必须走 task_manager

## CI/lint 既有红债

- `ruff check src/` 约 1400 条、`mypy src/` 约 600 条告警——HEAD 上就有，**不是你造成的**，不要顺手 mass-format（会淹没真实 diff）；只保证自己改的文件无新增错误
