# 编码规范与常用配方

## 通用规范

- 注释/日志全部中文；日志用 `from src.infrastructure.logging import get_logger`，logger 名即 `__name__`
- 所有文件 UTF-8（曾发生 GBK 乱码损坏提交进库的事故）
- 配置走 `infrastructure/config.py` 的 Settings（env 变量映射）；敏感字段落盘加密用 `infrastructure/crypto.py`（`FIELD_ENCRYPTION_KEY`，enc: 前缀）
- 后台任务：`from src.infrastructure.task_manager import background_task`（持引用 + 异常记日志）；协程内新任务用 `asyncio.create_task` 时必须自持引用

## 配方：新增/修改 HTTP 路由

1. 放在 `src/infrastructure/routes/<域>.py`，模块导出 `router = APIRouter(...)`；web.py `_register_routes` 已 include 的不用再加
2. 认证：`user: UserModel = Depends(get_current_user)`；管理员 `require_admin`（不要与 get_current_user 叠加）
3. 设备归属：`from src.infrastructure.routes._deps import check_device_owner`（统一实现，勿再复制）
4. 错误一律 `raise HTTPException(status, detail)`；成功返回 `{"code": 0, "message": "ok", "data": ...}`
5. 同步 DB 调用在 async 路由里用 `asyncio.to_thread` 包裹
6. 改了用户可见行为 → 同步更新 `vuepress-starter/docs/` 对应页

## 配方：加设备表字段

1. `src/infrastructure/db/models/device.py` 加 `Mapped[...]` 列
2. `src/infrastructure/db/migrations/schema.py` 的 `init_db()` 加一行 `_ensure_column(conn, "devices", "<列名>", "ALTER TABLE ...", devices_cols)`——**绝不 DROP**；列已存在是正常路径不打日志
3. `db/repositories/device_repository.py` 的 `_dict_to_model_fields` / `_model_to_dict` 同步映射
4. 读-改-写类更新（部分更新/技能列表/MCP 配置）必须套 `_device_rw_lock(device_id)`

## 配方：新增微信/设备能力

- 先查 `use_cases/sdk/` 是否已有：device（指令+回执）、io（GPIO）、music、http、storage（kv/plugin_data）、events（事件订阅）、tools（@tool）
- 指令回执返回 `(result, status, detail)`，status ∈ ok/offline/timeout/error/busy；新代码禁止再造错误约定

## 测试

- 基线 0 failed（约 2700 用例）；跑法见 SKILL.md
- 测试文件也 UTF-8；mock `asyncio.create_task` 时返回值需带 `add_done_callback`（部分源码会调用）
- 常用子集：
  ```bash
  .venv/Scripts/python.exe -m pytest tests/ -q -k "wechat" -p no:cacheprovider
  .venv/Scripts/python.exe -m pytest tests/test_pipeline.py tests/test_session.py -q
  ```
- 有一个测试间污染源：test_web.py 的 lifespan 会加载 data/plugins/installed 下的真实插件，污染 `plugin_loader._service_registry`——test_ws_session_handler.py 已有 `_isolate_service_registry` fixture，新增受影响测试可复用
- 挂死的测试优先怀疑：patch 了 asyncio.sleep、mock 的 create_session 缺 `tool_manager=None` 形参、真实 DB（data/espai.db）未 mock

## 认证与安全要点

- JWT 带 `token_version` claim；`get_current_user` 查库比对——改密码/重置/停用用户时 `token_version += 1` 吊销全部旧 token
- refresh 端点必须查库（存在性 + is_active + token_version）
- MAC 入库前过 `websocket_handler._is_valid_mac`（防 HTML 注入入库）
- zip 读取用 `marketplace.read_zip_member_checked`（单文件 5MB/累计 20MB/200 个）；图标保存必须走白名单+magic 校验
- Pillow 全局 `MAX_IMAGE_PIXELS=30_000_000`；重处理用 `asyncio.to_thread`
