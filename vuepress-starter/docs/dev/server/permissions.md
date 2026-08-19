# 权限体系（角色与 API 分级）

系统采用 **JWT 用户认证 + 角色分级 + 设备归属校验** 三层权限模型，精确控制每个 API 的访问。

## 角色模型

| 角色 | 来源 | 权限 |
|---|---|---|
| `admin`（管理员） | **系统中第一个注册的用户自动成为管理员**；已部署系统由启动迁移自动提升最早注册用户 | 全部 API（含固件管理、批量 OTA、全局插件/技能管理）|
| `user`（普通用户） | 后续注册的用户 | 管理**自己的**设备、插件、技能、配置 |

- 用户表 `users.role` 字段（`admin` / `user`，默认 `user`）
- 首次注册时数据库计数为 0 → 该用户 `role=admin`（`src/infrastructure/routes/auth.py`）
- 兼容已部署系统：启动时若没有任何管理员，最早注册的用户自动提升（`src/infrastructure/db/migrations/schema.py`）

## 三层校验机制

1. **认证层**：`Depends(get_current_user)` —— 校验 JWT access_token 有效、用户存在且未禁用
2. **角色层**：`Depends(require_admin)` —— 仅 `role=admin` 可访问（普通用户返回 403）
3. **归属层**：`require_device_owner(request, device)` / `_check_device_owner(device_id, user)` —— 设备操作必须属于当前登录用户（兼容 device_id / mac_address / device_key 三种标识），防止跨用户串台

## API 权限矩阵

### 🔓 公开（无需认证）

| 端点 | 说明 |
|---|---|
| `POST /api/v1/auth/register` `/login` `/refresh` | 注册（首个用户自动 admin）/ 登录 / 刷新令牌 |
| `GET /health/live` `/health/ready` `/api/health` | 健康检查 |
| `GET /stats` `/metrics` | 聚合统计 / Prometheus 指标（仅计数，无敏感数据）|
| `GET /api/v1/emos` `/api/v1/emos/{device_id}` | 设备端拉取表情列表（设备固件使用）|

### 👤 用户级（JWT 认证 + 设备归属）

| 端点 | 说明 |
|---|---|
| `GET/PUT /api/v1/user/me`、`PUT /api/v1/user/password` | 个人信息 / 改密码 |
| `GET/POST /api/v1/devices` 及 `/devices/{id}/bind|unbind|wakeup|speak|stop` 等 | 设备管理（仅自己的设备）|
| `GET/PUT /api/v1/devices/{id}/plugins`、`PUT .../plugins/{plugin}/config` | 插件商店安装/卸载/配置（仅自己的设备）|
| `GET /api/v1/plugins` | 查看可用插件列表 |
| `GET/POST /api/v1/skills`、`GET /api/v1/skills/{id}` | 技能列表/详情/创建（绑定设备时校验归属）|
| `/api/v1/devices/{mac}/mcp*` | MCP 服务器配置（仅自己的设备）|
| `/api/v1/growth/*` | 日记/成长数据（仅自己的设备）|
| `/api/v1/emos/packs*` | 表情包管理 |
| `/api/v1/wechat/*` | 微信绑定、发指令（send-to-device 仅限自己的设备）|
| `/api/v1/devices/{mac}/config|history|volume|ota|wifi|pins|test|stats` | 设备控制/配置（仅自己的设备）|
| `/api/v1/tts/clone-voices*` | 复刻音色（mac 归属）|

### 🛡️ 管理员级（JWT + require_admin）

| 端点 | 说明 | 风险（若放开）|
|---|---|---|
| `POST /api/v1/firmware/upload` | 上传固件 | 植入恶意固件推送 |
| `GET /api/v1/firmware`、`GET/POST /api/v1/firmware/{filename}` | 固件库查看/删除 | 删除他人固件 |
| `POST /api/v1/firmware/default` | 设置默认固件 | 劫持所有设备升级 |
| `POST /api/v1/devices/ota/all` | 批量升级所有设备 | 控制全网设备 |
| `POST /api/v1/plugins/reload` | 全局插件热重载 | 影响所有设备工具列表 |
| `PUT/DELETE /api/v1/skills/{skill_id}`、`POST /api/v1/skills/reload` | 全局技能库管理 | 篡改共享技能影响其他设备 |

## 安全设计要点

- **插件商店权限**：插件未安装 → schema 隐藏 + 执行拦截 + **缓存路径前置检查**（`call_tool` 权限校验在缓存命中之前，卸载/退订后缓存期内也无法使用）
- **设备归属统一**：所有 `/devices/{mac|id}/*` 端点都过 `require_device_owner`，杜绝跨用户操作
- **管理员端点不可绕过**：`require_admin` 是 FastAPI 依赖，无法通过 URL 变体绕过
- **设备级插件配置隔离**：`plugin_configs` 按设备存储，A 设备的密钥不影响 B 设备

## 新增 API 时的权限清单

开发新端点时按此检查：

- [ ] 是否公开？→ 默认不公开
- [ ] 操作设备？→ 加 `require_device_owner` 归属校验
- [ ] 影响全局（固件/批量操作/全局配置）？→ 加 `Depends(require_admin)`
- [ ] 普通用户操作？→ `Depends(get_current_user)`
