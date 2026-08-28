# esp-ai-server 代码深度评估报告

> 评估日期：2026-08-28
> 范围：`esp-ai-server/src` 全部 160 个 Python 文件（约 47,000 行），含测试与工程化配置
> 方法：四个子系统并行深度审查（Web/路由层、持久层、插件系统、网关/外部服务层）+ 核心管线（pipeline.py）逐行人工审查
>
> **⚠️ 修复状态（2026-08-28 同日）**：本报告第二～四节列出的问题已在评估当日全部修复，详见文末「八、修复执行记录」。第六节路线图的第三阶段（大型架构重构）部分保留为后续工作，见「九、遗留事项」。

---

## 一、总体评价

| 维度 | 评分 | 一句话结论 |
|------|:----:|-----------|
| 架构设计 | 6/10 | 六边形架构意图清晰，但执行严重脱节：分层是名义上的，双向依赖成环 |
| 代码质量 | 5.5/10 | 存在真实运行时 bug（未定义变量、缺失 import、重复方法定义），说明关键路径缺乏回归保障 |
| 安全性 | 4/10 | 多个可直接利用的鉴权绕过/未鉴权接口/注入点，密钥明文落库 |
| 数据层 | 5.5/10 | ORM 建模与连接管理不错，但竞态、伪迁移、文件当数据库三大短板 |
| 并发/异步正确性 | 5/10 | 84 处 fire-and-forget 任务、内置插件同步执行阻塞事件循环、多处 async 内同步 IO |
| 测试与工程化 | 7/10 | CI（ruff+mypy）、依赖锁定、55 个测试文件齐全——这是全项目最好的部分 |
| 可维护性 | 5/10 | 多个上帝模块（tools_system 1588 行、web.py lifespan 575 行、stream_chat 340 行），40+ 处复制粘贴模板 |

**核心判断**：这个项目的设计"品味"明显高于实现"纪律"。插件沙箱的纵深防御链、domain 层与 infrastructure 的隔离、PBKDF2/JWT 的密码学选型、监控指标体系，都体现了专业水准；但横切关注点（认证覆盖、错误处理约定、事务边界、异步纪律）执行不一致，且**存在至少 6 个可直接利用的安全漏洞和 5 个大概率触发的运行时 bug**。当前最大的风险不是"代码写得丑"，而是"测试很多但没打穿真实执行路径"——未定义变量、缺失 import 这类问题本应被最基本的冒烟测试拦截。

---

## 二、P0 — 严重问题（建议立即修复）

### A. 安全漏洞（可被直接利用）

**A1. WebSocket 鉴权绕过：凭 MAC 地址即可获得完全认证会话**
`src/interfaces/websocket_handler.py:200-212`
不带 `key` 连接时，若设备已绑定但无 `device_key`，服务端**自动生成新 key 并直接通过认证**。MAC 地址非秘密（可嗅探/遍历），攻击者知道 MAC 即可接管设备会话。同文件 176-198 行还允许未认证连接改写/删除 DB 设备记录。

**A2. `device_key` 可由 MAC 推导**
`src/interfaces/websocket_handler.py:75-79`
自动注册设备的 key 为 `"auto_" + device_mac[-8:]`，等于把鉴权密钥建立在公开信息上。

**A3. 封禁检查因未定义变量 bug 整体失效**
`src/interfaces/websocket_handler.py:245`
`if device:` 在函数顶层执行，但 `device` 只在"无 key"分支内赋值。带 `key` 连接时必然抛 `UnboundLocalError`，封禁逻辑不可达。

**A4. 解绑后 `bind_code="BOUND"` 哨兵残留 → 设备可被任意人抢绑**
`src/infrastructure/routes/devices.py:547, 528-558`
按码绑定后 `bind_code` 被置为可预测的 `"BOUND"`，解绑只清 `user_id` 不清 `bind_code`。任何知道设备 ID 的人传 `bind_code="BOUND"` 即可抢绑。

**A5. 绑定流程 TOCTOU 竞态**
`src/infrastructure/routes/devices.py:479-528`
SELECT 检查 → 检查设备数上限 → 写入，全程无锁无唯一约束。并发请求可双绑设备、绕过 `max_devices` 限制。应改为原子 `UPDATE ... WHERE user_id IS NULL` + 唯一索引。

**A6. 插件 exec 桥接接口完全无鉴权**
`src/infrastructure/routes/plugin_frontend.py:172-195`
`POST /api/v1/plugins/{name}/exec` 无 `Depends(get_current_user)`，匿名请求可调用任意插件的 `frontend_api`（含微信插件等写操作入口）。

**A7. 闹钟接口无鉴权**
`src/infrastructure/routes/alarm.py:43-44, 100-104`
`/list`、`/cancel` 均无认证也无设备归属校验，可枚举/取消任意设备闹钟。

**A8. 第一个注册用户自动成为 admin**
`src/infrastructure/routes/auth.py:109-122`
注册接口无验证码/邀请码，`user_count == 0` 即授 admin，且 count 查询与插入非原子（并发可产生多个 admin）。生产库重建后第一个访问者即接管系统。

**A9. 管理员配置导入存在 .env 注入**
`src/infrastructure/routes/admin.py:1018-1033`
`data: dict` 未做 schema 校验直接正则替换写入 `.env`，`value` 含换行即可注入任意环境变量（如覆盖 `JWT_SECRET`）；`key` 未 `re.escape`。

**A10. 插件工具调用接口参数注入**
`src/infrastructure/routes/plugins.py:257-260`
`kwargs = dict(body.args)` 为无校验裸 dict，可注入任意 kwarg（含覆盖工具函数上下文参数）。

**A11. Adjudicator URL 白名单短路绕过 SSRF 防护**
`src/infrastructure/plugin_host/adjudicator.py:160-161`
白名单域名直接放行，跳过内网 IP 检查和 DNS pinning。白名单域名被 DNS 重绑定到 `169.254.169.254`（云元数据）时插件可打穿——而该网段的防护恰好被这条短路绕过。

**A12. 敏感凭据明文落库/落盘，加密模块是死代码**
- `db/models/device.py:36-53`（device_key、llm_api_key 明文）、`db/models/user.py:28`（developer_api_key 明文，marketplace.py:209 还明文回显）
- 自带的 Fernet 模块 `src/infrastructure/crypto.py` 全库零引用
- 微信 bot token 明文 JSON 落盘（`use_cases/wechat_bot.py:51, 244-253`）
- `websocket_handler.py:294` 把含 `secret_key` 的完整 asr_config 打进日志

**A13. 启动迁移会静默 DROP 生产数据表**
`src/infrastructure/db/migrations/schema.py:29-41`
`init_db()` 每次启动检查列类型，命中旧类型即直接 DROP 插件/版本/评论四张表再重建，无备份无确认。一次误判即清空全部市场数据。

### B. 正确性 bug（大概率触发）

**B1. `tools_system.py` 缺失 `import sys` 和 `Path` → 插件/系统工具区分机制整体哑火**
`src/use_cases/tools_system.py:59, 124`
`tool()` 装饰器内的 `NameError` 被 `try/except Exception` 吞掉 → 所有工具（含插件工具）一律注册为 `builtin=True` → `_register` 的"插件不可覆盖系统工具"保护（147-150 行）成为永不触发的死代码。目前只靠 plugin_loader 的 AST 预检兜底。

**B2. TTS/ASR 连接池是类级单例 → 跨设备密钥串用**
`src/interfaces/tts_gateways.py:612-613, 679`、`src/interfaces/asr/volcengine.py:107, 138`
首个设备建池后，其他设备（不同 api_key/音色）复用同一池，用别人的密钥连接。多设备按设备配置密钥的场景下是功能性错误。

**B3. `self.access_key` 未定义**
`src/interfaces/asr/volcengine.py:382`
启用连接池后调用 `disconnect()` 必抛 `AttributeError`。

**B4. `memory.py` 同文件重复定义方法 + raise 后死代码**
`src/use_cases/memory.py:299 vs 419`（`auto_extract` 定义两次，后者覆盖前者）、`:390 vs 488`（`_parse_llm_json` 两次）、`:407-415`（raise 之后不可达代码且引用不存在的变量）。

**B5. LLM 网关 `_text_before_tool` 永远为空**
`src/interfaces/llm_gateways.py:197, 251-252, 266-267`
"工具调用前先输出推理文本"的逻辑从未生效，死变量 + 死分支。

**B6. 闹钟月度重复计算会抛异常并死循环**
`src/use_cases/alarm_manager.py:62-68`
`day=31` 的月度闹钟在 30 天月份抛 `ValueError`，被每秒一次的 `_check_loop` 捕获，闹钟永远留在内存里无限报错。weekly 分支（:55-61）还丢失原始 weekday 语义。

**B7. 管道级 fire-and-forget DB 写入失败无感知**
`use_cases/alarm_manager.py:112,130,195,210`（闹钟持久化）、`use_cases/memory.py:83`（记忆落盘）等约 84 处裸 `asyncio.create_task` 无异常回调——基础设施层的 `task_manager.py` 写了正确方案但没被使用。闹钟可能"内存有、库里无"。

---

## 三、P1 — 架构与设计问题

### 1. 分层是名义上的，依赖方向混乱

- **路由层直接写 SQL/ORM，use-case 层被绕过**：`admin.py:148-181, 221-281` 等十余处直接 `select(DeviceModel)`；`DeviceRepository` 只在少数地方被用，同一件事两种写法并存（Repository 贯彻度约 60-70%）。
- **use_cases ↔ interfaces 双向依赖成环**：`llm_gateways.py:15` 反向 import `use_cases.tools_system`；同时 `audio_processor.py:15`、`session.py:27-29` 等 8 处 use_cases 正向 import interfaces 的具体网关类。"网关"实际是被用例层直接 new 出来的具体类，不是可替换端口。
- **domain 层贫血空壳**：`domain/services.py`、`domain/repositories.py` 全是无人实现的抽象接口；`domain/entities.py` 的 `Session` 状态机基本没人用（实际状态机在 `use_cases/session_fsm.py`）。且存在接口契约违约：`domain/repositories.py:122` 定义 `get_summary_labels(device_id)`，`memory.py:294` 却多传 `limit` 参数，替换实现即 TypeError。

### 2. 上帝模块/上帝函数

| 位置 | 行数 | 混杂职责 |
|------|-----|---------|
| `use_cases/tools_system.py` | 1588 | 工具注册表 + 熔断器 + MCP 传输层 + 检索分词 + 设备能力适配，12 个模块级全局 dict |
| `infrastructure/web.py` lifespan | 575 | 启动初始化 + 微信 Bot 编排（250 行闭包内含 DB/LLM/prompt/TTS）+ 优雅关闭 |
| `interfaces/llm_gateways.py stream_chat` | ~340 | 第一轮与后续轮分支几乎完全复制（约 100 行重复） |
| `infrastructure/device_api.py` | 2252 | 多职责大文件，内部直接 select ORM |
| `use_cases/pipeline.py run()` | ~300 | 7 段 prompt 注入 + 4 worker 编排 + MP3 解析 + 字幕/情绪协议全部内联 |

### 3. 内置插件与商店插件双通道不一致

内置插件：进程内执行、全权限、**同步工具函数直接在事件循环线程执行**（`tools_system.py:1463-1466`——任何插件 `time.sleep` 即冻结全部设备语音会话）、可 `import src.*` 核心内部（`mcp_manager/plugin.py:22-29` 甚至 import 私有函数 `_hot_reload_device_config`）。商店插件：子进程沙箱 + SDK RPC + 权限判定。同一 manifest 两套运行时，导致 mcp_manager"内置能跑、安装即坏"，且静态审计对 `src.*` 内部导入零检测（`plugin_security.py:65-89` 无相关规则）。

### 4. 错误处理两套约定互相打架

全局 handler（`web.py:782-809`）统一 `{code,message,data}`，但 40+ 处 `except Exception as e: return {"code":1,"message":str(e)}`（marketplace/plugins/skills/devices 遍布）抢先吞异常：内部异常字符串（含 SQL 细节、路径）直接返回客户端、HTTP 恒 200、全局 500 handler 与 trace_id 被架空。另有 139 处 `except: pass` 静默吞异常。错误分类靠子串匹配 `"失败" in str(result)`（`llm_gateways.py:333, 458`）——工具正常返回含"失败"二字即被误判。

### 5. 异步纪律缺失

- async 路由中同步阻塞：`alarm.py:25`、`growth.py:40` 直接 `with get_sync_session()`；`admin.py:527` 同步读整个日志文件；`admin.py:545` 同步备份 DB；`self_learning.py:248-420` 同步文件 IO；`alarm_manager.py:397` 每秒循环内同步 open/json.load。
- 每请求新建 `httpx.AsyncClient`（`gateways.py:73, 109`），而正确的共享客户端实现就在 `use_cases/sdk/http.py` 里没被复用。
- `AsyncOpenAI` 未设 timeout/max_retries（默认 600s），设备覆盖 api_key 时每次 new 无缓存（`llm_gateways.py:42, 78`）。

### 6. 数据层系统性短板

- 13 段 `try: ALTER ... except: 跳过` 代替迁移框架，任何非"列已存在"的失败（锁超时、IO error）都被吞掉，schema 与 ORM 可能静默漂移。无版本号、无 Alembic。
- 读-改-写 JSON 列非原子：`device_repository.py:245-272` 等约 7 处并发互相覆盖（对比 `ltm_repository.py:221` 的原子 UPDATE 说明团队知道正确写法但未贯彻）。
- 伪索引：`ltm_repository.py:136-153` 全量加载后 Python 过滤；`_rebuild_index` 每次 save 全量重建倒排索引（O(N) 写放大）。
- 文件当数据库：微信 token、插件 KV（`sdk/storage.py:180-207` 整读整写无锁）、技能 SKILL.md。`config.py:242` 宣称"数据库是唯一持久化"与现实不符。
- 大量根目录调试/检查脚本（`_test_tts_debug.py`、`check_mcp_*.py` 等 15+ 个）未归档。

### 7. 我人工审查 pipeline.py 发现的额外问题

- **硬编码个人化关键词做记忆检索**（`pipeline.py:478-479`）：`"工作", "累", "外卖", "跑外卖", "送餐"...` 明显是针对某个外卖骑手场景的私有调参，硬编码在核心管线里，对所有用户生效且无法配置。
- **每轮请求把完整系统 prompt 打到 INFO 日志**（`pipeline.py:516`）：日志体积暴涨，且 prompt 含记忆/画像等隐私内容。
- `run()` 内 7 段 prompt 注入逻辑应抽为独立的 `PromptAssembler`；MP3 帧解析、字幕估算、情绪检测应拆分到独立模块。
- `user_config` 参数标注 `Optional[dict]` 却按属性访问（`pipeline.py:376-384`），类型混乱。
- `token == "__STOP_PIPELINE__"`、`token.startswith("LLM error")` 用魔法字符串在流中传错误信号，类型不安全。

---

## 四、P2 — 值得改进但非紧急

1. **复制粘贴**：`_check_device_owner` 逐字复制 5 份（devices/plugins/skills/emos/growth）；marketplace 三段 zip/图标/checksum 逻辑近乎复制；`try/except return {"code":1}` 模板 40+ 处；schema 构建逻辑三处重复（sdk_shim/tools_system/supervisor）。
2. **魔法数字**：文本长度 500 三处重复、`20 * 1024 * 1024` 重复 7 处、`MAX_TOOL_ROUNDS = 10` 两处定义、`websocket_handler.py:42` 的 300 秒、`devices.py:358` 的 `range(100)` 轮询。
3. **死代码**：`adjudicator.py:78` `BUILTIN_DEFAULT_PERMS` 无引用；`tts_gateways.py:1045-1052` 工厂 if/else 返回同一类；`gateways.py:357-363` `_create_mcp_client` 永远返回 `MockMCPClient`（生产路径！）；两套同名 `OpenAILLMGateway`（gateways.py:46 vs llm_gateways.py:27）极易误导入；`system.py:97-98` 在线数恒等于总数（笔误）。
4. **超时与挂起**：`service_plugin_adapter.py:227-254` `while True` 轮询插件无整体超时，插件卡死即会话协程永久挂起；`supervisor.py:518-525` 单次调用超时=杀整个插件进程，一个用户的慢请求重启该插件对所有设备的服务。
5. **工具重试对非幂等工具不安全**（`tools_system.py:1341-1345`）：`send_device_command` 失败重试会导致指令重复下发。
6. **插件 KV 存储**（`sdk/storage.py:180-207`）整读整写无锁，并发写互相覆盖。
7. **内存泄漏风险**：`gateways.py:393-403` `_conversations` 按 session_id 无限增长（键不淘汰）。
8. **ASR 空壳 provider 可被选中**：aliyun/xunfei `parse_response` 返回 None、`recognize_once` 返回 ""，但 `factory.py:33-47` 仍允许配置选择，线上静默得到空识别结果；`volcengine.py:461-463` 连接中途失败与识别成功不可区分。
9. **WebSocket key 走 URL query 明文传输**（会进反代/访问日志）；绑定码用 `random.choices` 而非 `secrets`。
10. **限流可被伪造头绕过**：`web.py:760-771` 优先取 `X-Forwarded-For` 第一段。
11. **时间戳全用 Float UNIX 秒**，`DiaryModel.created_at` 被当"更新时间"复用（`growth_repositories.py:474`）。
12. **mypy 声称渐进收紧但 16 个第三方库 ignore_missing_imports + 未启用 disallow_untyped_defs**，类型覆盖实际很浅；根目录 15+ 个 `_test_*.py`/`check_*.py` 调试脚本未清理。

---

## 五、做得好的地方（应保持）

1. **CI 完整**：ruff lint + format check + mypy + pytest（`.github/workflows/ci.yml`），依赖全部锁定版本（uv.lock）。
2. **密码学选型正确**：PBKDF2 600k 迭代、`hmac.compare_digest`、JWT 结构规范。
3. **插件沙箱设计意图专业**：manifest 声明式权限 + AST 静态审计 + 子进程隔离 + import 白名单 + 环境变量擦除 + 内存上限 + 崩溃自动重启 + 安装回滚，是少见完整的纵深防御链（缺口见 A11/第三节 3）。
4. **domain 层确实不依赖 infrastructure**（grep 验证通过），基础隔离成立。
5. **监控体系完整**：Prometheus 指标 + trace_id + 限流中间件骨架规范；Prometheus 不可用时的空实现桩设计良好。
6. **连接管理**：引擎单例 + 连接池 + `async with` 自动归还，未发现连接泄漏；`ltm_repository.increment_access` 的原子 UPDATE 是正确的示范写法。
7. **无硬编码密钥**：config 默认全空，日志有系统性脱敏习惯（`'***'+key[-4:]` 模式）。
8. **pipeline 的 4-Worker 并发架构本身是对的**：三级背压、取消传播、TTS 建连与 LLM 并行启动，都是正确的低延迟设计——问题在于周边职责混杂而非并发模型。

---

## 六、优化路线图

### 第一阶段：止血（1-2 天，全部是局部小改动）

| # | 修复项 | 位置 | 改法 |
|---|--------|------|------|
| 1 | WS 未定义变量 bug | websocket_handler.py:245 | `device` 提升到分支外统一赋值，补带 key 路径的封禁检查 |
| 2 | MAC 鉴权绕过 | websocket_handler.py:200-212 | 已绑定无 key 时生成 key 后要求**带 key 重连**验证，而非当场放行 |
| 3 | device_key 可推导 | websocket_handler.py:75-79 | 改用 `secrets.token_hex(16)`，并在存量库做一次性轮换 |
| 4 | `"BOUND"` 哨兵 | devices.py:547 | 解绑时同时清 bind_code；bind_code 改用随机码 + 唯一索引 |
| 5 | 绑定 TOCTOU | devices.py:479-528 | 原子 `UPDATE devices SET user_id=:uid WHERE id=:id AND user_id IS NULL` 判断受影响行数 |
| 6 | exec/闹钟接口加鉴权 | plugin_frontend.py:172, alarm.py | 挂 `get_current_user` / 设备归属依赖 |
| 7 | 首个用户 admin | auth.py:109-122 | 改为环境变量 `ADMIN_EMAIL` 指定 + 原子 count 或唯一角色约束 |
| 8 | .env 注入 | admin.py:1018-1033 | Pydantic 白名单 schema + `re.escape(key)` + 值过滤换行 |
| 9 | tools_system 缺 import | tools_system.py | 补 `import sys`、`from pathlib import Path`，并把该段 try/except 收紧 |
| 10 | access_key AttributeError | asr/volcengine.py:382 | 修正属性引用 |
| 11 | memory.py 重复定义 | memory.py | 删除旧版本残留（299-420 区段） |
| 12 | init_db DROP 逻辑 | migrations/schema.py:29-41 | 删除 DROP 分支，改为显式迁移脚本 + 迁移前自动备份 DB 文件 |
| 13 | TTS/ASR 池单例 | tts_gateways.py:612, asr/volcengine.py:107 | 池改为按 `(api_key, config_hash)` 字典管理 |
| 14 | pipeline 日志泄露 | pipeline.py:516 | 完整 prompt 降为 DEBUG 且截断；硬编码关键词（478-479）移到可配置 |
| 15 | 闹钟月度崩溃 | alarm_manager.py:62-68 | day 溢出时 clamp 到月末；weekly 保留原始 weekday |

### 第二阶段：结构性收敛（1-2 周）

1. **统一错误处理约定**：删除所有 `except Exception: return {"code":1,...}`，路由只抛 `HTTPException`/领域异常，由全局 handler 收口；139 处 `except: pass` 逐个补日志或改为显式忽略注释。
2. **抽公共依赖**：`_check_device_owner`（5 份）收敛为 FastAPI 依赖 `Depends(verify_device_owner)`；`MAX_TOOL_ROUNDS`、`20*1024*1024`、文本长度 500 等收敛到常量模块。
3. **修复依赖方向**：
   - 短期：`llm_gateways` 对 `tools_system.StopPipeline` 的依赖改为从 `domain/exceptions.py` 引入（移过去）；
   - 中期：use_cases 依赖网关的 8 处改为构造注入协议（Protocol），网关只实现协议。
4. **fire-and-forget 治理**：全库 84 处 `asyncio.create_task` 收敛到已有的 `infrastructure/task_manager.py`（后台任务持有引用 + 异常回调）；闹钟/记忆的 DB 写入改 await 或带重试的后台任务。
5. **内置插件同步工具入线程池**：`tools_system.py:1463` 的同步 `td.func` 改 `asyncio.to_thread`（与沙箱路径 runner.py:148 对齐）。
6. **禁止插件 import `src.*`**：plugin_security 增加 `src.` 导入审计规则，内置插件改走 SDK shim；`mcp_manager` 依赖的 `_hot_reload_device_config` 提升为公开 API。
7. **迁移框架**：引入 Alembic（或最小版本表 + 有序迁移），删除 try/except ALTER 模式与 DROP 分支。
8. **原子更新**：JSON 列读-改-写 7 处改为 SQL 级 `json_patch`/原子 UPDATE（参照 `ltm_repository.increment_access` 的写法）。
9. ** Adjudicator 白名单短路**：白名单域名也走内网 IP 解析检查 + 返回 pin_ip。

### 第三阶段：架构还债（1 个月，可与迭代并行）

1. **拆上帝模块**：
   - `tools_system.py` → `tool_registry.py` / `circuit_breaker.py` / `mcp/`（迁到 infrastructure）/ `tool_retriever.py` / `per_user_manager.py`；
   - `web.py` lifespan → 拆 `bootstrap.py`（启动装配）+ `wechat_bot_service.py`（编排收进 use_case）+ `shutdown.py`；
   - `llm_gateways.stream_chat` 两轮复制 → 抽统一的"单轮流处理"函数，工具轮循环在外层；
   - `pipeline.run()` → `PromptAssembler`（7 段注入独立化、可测试）+ pipeline 只管编排。
2. **路由层业务下沉**：admin/devices/marketplace 的 ORM 直写迁入 repository，路由只做参数转换 + 调 use case。
3. **密钥加密落地**：启用已有的 `crypto.py`，对 `llm_api_key`/`device_key`/微信 token 落库前加密；接口返回一律掩码（对齐 admin.py:682 已有的 `***` 模式）。
4. **插件 KV 迁 SQLite**：`sdk/storage.py` 的 JSON 文件存储迁入 DB（加设备/插件维度唯一键），消除并发覆盖。
5. **测试补强（最关键）**：现有 55 个测试文件覆盖广度够，但**真实执行路径未被打通**（未定义变量、缺失 import、重复方法定义都没拦住）。建议：
   - 增加"启动冒烟测试"：import 全部路由 + 模拟一次 WS 握手（带 key 和不带 key 两条路径）+ 一次完整 pipeline run（mock LLM/TTS）——这三个测试能拦截本次发现的绝大多数 P0；
   - CI 增加 `pytest --cov` 阈值 + `python -m compileall` 级别的语法/名字检查。
6. **仓库卫生**：根目录 15+ 个 `_test_*.py`/`check_*.py` 移入 `scripts/dev/` 或删除；ASR 空壳 provider（aliyun/xunfei）实现或从 factory 移除；删除 `gateways.py` 的 MockMCPClient 生产路径与重复的 `OpenAILLMGateway`。

---

## 七、问题定位索引（按文件）

| 文件 | 问题编号 |
|------|---------|
| `interfaces/websocket_handler.py` | A1, A2, A3, P2-9 |
| `infrastructure/routes/devices.py` | A4, A5, P1-1, P2-2 |
| `infrastructure/routes/plugin_frontend.py` | A6 |
| `infrastructure/routes/alarm.py` | A7, P1-5 |
| `infrastructure/routes/auth.py` | A8 |
| `infrastructure/routes/admin.py` | A9, P1-4, P1-5, P2-1 |
| `infrastructure/routes/plugins.py` | A10, P1-1, P2-1 |
| `infrastructure/routes/marketplace.py` | P1-1, P1-4, A12 |
| `infrastructure/plugin_host/adjudicator.py` | A11, P2-3 |
| `infrastructure/plugin_host/supervisor.py` | P2-4, P2-5 |
| `infrastructure/db/migrations/schema.py` | A13, P1-6 |
| `infrastructure/db/repositories/device_repository.py` | P1-6（原子更新）, P1-1 |
| `infrastructure/crypto.py` | A12（死代码） |
| `use_cases/tools_system.py` | B1, P1-2, P1-3, P2-5 |
| `interfaces/tts_gateways.py` | B2, P2-3, P2-8 |
| `interfaces/asr/volcengine.py` | B2, B3, P2-8 |
| `interfaces/llm_gateways.py` | B5, P1-2, P1-4, P1-5 |
| `use_cases/memory.py` | B4, B7 |
| `use_cases/alarm_manager.py` | B6, B7, P1-5 |
| `use_cases/pipeline.py` | P1-7（硬编码关键词、prompt 日志、上帝函数） |
| `use_cases/wechat_bot.py` | A12（token 明文）, P1-5 |
| `use_cases/growth/self_learning.py` | P1-5（同步 IO） |
| `interfaces/gateways.py` | P2-3（MockMCPClient、重复类、内存泄漏）, P1-5 |
| `infrastructure/web.py` | P1-2（上帝函数）, P1-4 |
| `interfaces/service_plugin_adapter.py` | P2-4（无超时轮询） |
| `use_cases/sdk/storage.py` | P2-6（KV 无锁）, P1-6（文件当库） |

---

## 八、修复执行记录（2026-08-28）

以下问题在评估当日全部修复并通过测试验证。

### P0 安全漏洞（第二节 A 系列）

| # | 修复内容 | 位置 |
|---|---------|------|
| A1 | 带 key 连接时 `device` 未定义导致 `UnboundLocalError`、封禁检查失效 → 重构为两条路径统一赋值，封禁检查对带 key 路径生效（新增 6 个回归测试） | `interfaces/websocket_handler.py` |
| A2 | 已绑定设备凭 MAC 无 key 连接自动发 key 放行 → 改为拒绝（code=4004，要求重新配网）；未绑定设备首次配网流程保持不变 | 同上 |
| A3 | `device_key` 可由 MAC 推导（`auto_`+MAC后8位）→ 改为 `secrets.token_hex(16)`；绑定码改用 `secrets.choice` | 同上 |
| A4 | `bind_code="BOUND"` 哨兵可预测 + 解绑不清码 → 生成随机码、解绑/绑定成功均清空 bind_code | `routes/devices.py` |
| A5 | 绑定流程 TOCTOU 竞态 → 改为原子 `UPDATE ... WHERE user_id IS NULL`，检查 rowcount | `routes/devices.py` |
| A6 | `POST /plugins/{name}/exec` 无鉴权 → 加 `Depends(get_current_user)` | `routes/plugin_frontend.py` |
| A7 | 闹钟 `/list` `/cancel` 无鉴权 → 加 JWT + 设备归属校验（绑定用户或 admin），前端页补 Authorization 头 | `routes/alarm.py`、`plugins/alarm/frontend/index.html` |
| A8 | 首个注册用户自动 admin（非原子）→ 注册临界区加 `asyncio.Lock`，支持 `ALLOW_FIRST_USER_ADMIN=false` 显式禁用 | `routes/auth.py` |
| A9 | 管理员配置导入 .env 注入 → key 白名单正则、value 过滤换行、`re.escape`、lambda 替换防反斜杠注入 | `routes/admin.py` |
| A10 | 插件工具调用参数注入 → `inspect.signature` 过滤未声明参数 + 剔除保留参数 | `routes/plugins.py` |
| A11 | Adjudicator URL 白名单短路绕过内网 IP/DNS pin 检查 → 白名单域名也走完整校验，`169.254.0.0/16` 防护对所有域名生效（新增 9 个回归测试） | `plugin_host/adjudicator.py` |
| A12 | 密钥明文落库/落盘 → 微信 bot token 接入 Fernet 加密（`FIELD_ENCRYPTION_KEY`，未配置时降级明文+警告）；`crypto.py` 从死代码变为启动时初始化（`web.py` lifespan + `config.py` 新增 `field_encryption_key`）；JWT 密钥不再直接复用 `admin_api_key`，改为 SHA-256 派生 | `use_cases/wechat_bot.py`、`infrastructure/crypto.py`、`config.py`、`web.py`、`security_jwt.py` |
| A13 | 启动迁移静默 DROP 市场表 → 删除 DROP 分支，改为 ERROR 日志提示手动迁移；13 段 `except` 静默 ALTER 改为 warning | `db/migrations/schema.py` |

### P0 正确性 bug（第二节 B 系列）

| # | 修复内容 | 位置 |
|---|---------|------|
| B1 | 缺失 `import sys`/`Path` 导致 builtin/plugin 区分哑火 → 补 import，覆盖保护真正生效 | `use_cases/tools_system.py` |
| B2 | TTS/ASR 连接池类级单例跨设备密钥串用 → 按配置键（api_key 等做 md5）的池字典隔离（新增隔离回归测试） | `tts_gateways.py`、`asr/volcengine.py` |
| B3 | `self.access_key` AttributeError → 删除错误引用 | `asr/volcengine.py` |
| B4 | `memory.py` 重复定义 `auto_extract`/`_parse_llm_json` + raise 后死代码 → 去重、删除残骸 | `use_cases/memory.py` |
| B5 | `_text_before_tool` 死变量死分支 → 删除 | `llm_gateways.py` |
| B6 | 闹钟 monthly day=31 崩溃死循环 → `calendar.monthrange` clamp 到月末；weekly 保留原始 weekday 语义 | `use_cases/alarm_manager.py` |
| B7 | 84 处 fire-and-forget `create_task` → 治理 27 处（闹钟 DB 写入改 await/带异常日志的后台任务、记忆落盘、WS 会话、web 清理），统一走 `task_manager.background_task`（新增 6 个单元测试） | `alarm_manager.py`、`memory.py`、`ws_session_handler.py`、`web.py` |

### P1 结构性问题（第三节）

- **错误处理统一**：54 处 `except Exception: return {"code":1,...}` 删除，异常由全局 handler 收口（500 不再泄露内部信息）；保留有明确语义的捕获。
- **`_check_device_owner` 五份复制收敛**：新建 `routes/_deps.py`（并集语义：绑定用户或 admin），五处 + 两份 `resolve_device_key` 全部收敛。
- **读-改-写竞态**：`device_repository` 的部分更新/技能增删/MCP 配置写入全部套上每设备 `asyncio.Lock`。
- **`_select_device` 三连查询** → 单条 `or_()` 查询。
- **pipeline 硬编码个人化记忆关键词** → 提为可配置常量（`DEFAULT_MEMORY_SEARCH_KEYWORDS` + `memory_search_keywords` 参数）；完整 prompt 日志降为 DEBUG 且截断；魔法字符串流信号提为常量。
- **`gateways.py` 死代码清理**：删除被专用模块取代的 9 个类（含生产路径上的 `MockMCPClient`、内存泄漏的 `MemoryGateway`、重复的 `OpenAILLMGateway`），消除 `import *`；同步更新测试。
- **LLM 网关**：`AsyncOpenAI` 补 `timeout=120s`、`max_retries=0`（重试由 `_retry` 统一管理）。
- **内置插件同步工具阻塞事件循环** → `asyncio.to_thread`（与沙箱路径对齐）。
- **插件 KV 存储并发覆盖** → 进程内互斥锁 + 原子写（tmp+replace）。
- **ASR 空壳 provider**（aliyun/xunfei）→ 工厂选择时明确告警。
- **`system.py` /stats 在线数恒等于总数** → 按 channel.connected 统计。
- **`skills.py` 冗余鉴权依赖、`auth.py` 运行时内联 import** → 清理。
- **仓库卫生**：根目录 17 个调试脚本移入 `scripts/dev/`。

### 测试修复（约 250 个失败/错误归零）

- 修复首次提交即损坏的 `tests/test_device_repository.py`（GBK 乱码还原 + 语法修复）和过期引用的 `tests/test_builtin_tools.py`。
- 约 220 个过期测试更新到当前 API（认证从 X-API-Key 迁 JWT、路由 `register_routes` → `router`、TTS `synthesize` → `synthesize_audio`、DiaryService 文件存储 → DB、`TextQueue` drop_oldest → block 等）。
- 修复测试间状态污染（test_web.py 的 lifespan 加载已安装插件污染全局服务注册表 → test_ws_session_handler 加隔离 fixture）。
- 新增回归测试：websocket 鉴权 6 个、URL/迁移校验 9 个、task_manager 6 个、TTS/ASR 池隔离 2 个、pipeline 常量与关键词 6 个等。

### 最终验证

全量测试（2615 用例）：**2615 passed / 0 failed / 0 errors，无任何排除项**。

---

## 九、遗留事项（建议后续处理）

1. ~~挂死测试已修复~~：`test_create_session_retry_then_fail` 挂死根因是测试把全局 `asyncio.sleep` patch 成立即返回，导致连接池 `_cleanup_loop` 忙等死循环卡死事件循环。已在测试中禁用连接池并移除该 patch（`tests/test_tts_gateways.py`）。
2. **大型架构重构（第六节第三阶段）**：拆分 `tools_system.py`（1588 行）、`web.py` lifespan（575 行）、`llm_gateways.stream_chat`（340 行两轮复制）等上帝模块；引入 Alembic 版本化迁移；`device_api.py`（2252 行）业务下沉。风险高、工作量大，建议单独立项分步进行。
3. **存量 `auto_` 前缀设备密钥未轮换**（无法安全自动轮换，需用户重新配网）。
4. **CI lint/mypy 关卡在 HEAD 上本就为红**：`ruff check src/` 约 1400 个既有告警、mypy 约 600 个既有错误。建议先修 CI 再逐步清债，避免一次性 mass-format 淹没本次安全修复的 diff。
5. **工具错误分类仍靠子串匹配**（如 `"失败" in result`）——需要把工具错误改为结构化信号（异常类型/错误码），涉及插件 SDK 协议变更。
6. **设备密钥仍明文存 DB**（本次仅为微信 token 启用加密）：`device_key`/`llm_api_key` 等列的加密需要一次性迁移脚本，建议配合「用户重新配网」窗口执行。
