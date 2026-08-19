# 数据库设计

## 概述

系统采用 **SQLite** 作为唯一持久化存储，通过 WAL 模式提升并发读写能力。数据访问层未引入 Alembic 迁移工具，而是依赖 `Base.metadata.create_all` 的幂等特性完成建表。整个持久化体系由基础设施层（`infrastructure/db`）、领域抽象层（`domain/repositories.py`）与仓储实现层（`infrastructure/db/repositories/`）三部分组成，共 14 张表、11 个仓储类，完全替代了早期基于 JSON 文件的存储方式。

## 引擎配置

### AsyncEngine 单例与 sessionmaker

`engine.py` 提供 `get_engine()` 全局 `AsyncEngine` 单例，并基于它构造 `get_session_factory()` 返回的 `async_sessionmaker`。会话工厂的关键配置如下：

| 配置项 | 值 | 作用 |
|---|---|---|
| `expire_on_commit` | `False` | 提交后对象属性不过期，避免异步上下文再次触发懒加载 |
| `autoflush` | `False` | 查询前不自动 flush，避免隐式 SQL 执行打乱事务边界 |

数据库 URL 来自 `settings.database.url`，引擎创建时会自动创建父目录，避免 SQLite 文件路径不存在导致的异常。

### SQLite PRAGMA 配置

SQLite 在默认配置下并发能力较弱，因此通过 `_apply_sqlite_pragmas` 在连接建立时执行以下 PRAGMA：

| PRAGMA | 值 | 作用 |
|---|---|---|
| `journal_mode` | `WAL` | Write-Ahead Logging，读不阻塞写 |
| `synchronous` | `NORMAL` | WAL 模式下安全且高效 |
| `foreign_keys` | `ON` | 启用外键约束 |
| `busy_timeout` | `5000` | 写冲突时等待 5 秒 |

PRAGMA 的挂载通过 `event.listens_for(sync_engine, "connect")` 实现，即在同步引擎的 `connect` 事件回调中执行。这种方式让每一个由连接池创建的 DBAPI 连接都会带上正确的 PRAGMA 设置，而不是只作用于首次连接。

## 表结构设计

14 张表按职责划分为 7 个 model 文件，对应 7 个分类。所有继承 `TimestampMixin` 的表都自动获得 `created_at`/`updated_at` 两个 `Float` 类型字段，存储 UNIX 时间戳秒，其中 `updated_at` 通过 `onupdate` 自动刷新。

### users 表

`UserModel` 继承 `Base + TimestampMixin`，`__tablename__ = "users"`，是用户账户体系的核心表，设备通过 `user_id` 外键绑定到用户。

| 列名 | 类型 | 约束/索引 | 说明 |
|---|---|---|---|
| `id` | `String(36)` | PK | 用户唯一标识（UUID）|
| `email` | `String(128)` | UNIQUE INDEX NOT NULL | 邮箱/手机号（登录账号）|
| `password_hash` | `String(256)` | NOT NULL | PBKDF2-HMAC-SHA256 密码哈希 |
| `nickname` | `String(64)` | NOT NULL | 昵称 |
| `role` | `String(16)` | default `"user"` | 角色（`admin` / `user`）|
| `max_devices` | `Integer` | default 10 | 可绑定设备数上限 |
| `is_active` | `Boolean` | default True | 账户是否启用 |
| `last_login` | `Float` | - | 最后登录时间戳 |

### devices 表

`DeviceModel` 继承 `Base + TimestampMixin`，`__tablename__ = "devices"`，是设备配置的核心表，替代了早期的 `users.json`。

| 列名 | 类型 | 约束/索引 | 说明 |
|---|---|---|---|
| `device_id` | `String(128)` | PK | 设备唯一标识 |
| `user_id` | `String(36)` | INDEX | 所属用户 ID（绑定后写入）|
| `name` | `String(256)` | NOT NULL | 设备名称 |
| `device_key` | `String(128)` | UNIQUE INDEX | 设备密钥（绑定后自动生成 bound_xxx）|
| `mac_address` | `String(64)` | INDEX | MAC 地址 |
| `management_api_key` | `String(256)` | - | 管理 API 密钥 |
| `bound_at` | `Float` | - | 绑定时间戳 |
| `bind_code` | `String(6)` | - | 6 位绑定码 |
| `bind_code_expires` | `Float` | - | 绑定码过期时间 |
| `asr_provider` / `llm_type` / `tts_type` | `String(32)` | - | 语音/LLM/TTS 提供商 |
| `asr_config` / `tts_config` / `music_config` / `wakeup_config` / `mcp_servers` | `JSON` | - | 各模块配置 |
| `llm_api_key` / `llm_base_url` / `llm_model` | `String` | - | LLM 接入参数 |
| `llm_system_prompt` | `Text` | - | 系统提示词 |
| `llm_memory_enabled` / `llm_memory_long_term_enabled` / `llm_memory_long_term_auto_extract` | `Boolean` | - | 记忆开关 |
| `llm_memory_max_messages` | `Integer` | - | 短期记忆窗口 |
| `rate_limit_rpm` | `Integer` | - | 每分钟请求限速 |
| `ota_enabled` | `Boolean` | - | OTA 开关 |
| `ota_bin_url` / `ota_version` / `ota_bin_id` / `ota_is_official` | `String` | - | OTA 升级配置 |
| `disabled_tools` | `JSON (list)` | - | 禁用工具列表 |
| `disabled_mcp_servers` | `JSON (list)` | - | 禁用 MCP 服务器列表 |
| `disabled_mcp_tools` | `JSON (dict)` | - | 按服务器禁用工具映射 |
| `disabled_skills` | `JSON (list)` | - | 禁用技能列表 |
| `skills` | `JSON (list)` | - | 设备启用技能列表 |
| `active_emo_pack` | `String(128)` | - | 当前激活表情包 |
| `is_online` | `Boolean` | - | 在线状态 |
| `last_seen` | `Float` | - | 最后在线时间 |

索引：`idx_devices_mac`（MAC 地址）、`idx_devices_updated_at`（更新时间）。

### memory 表族（4 个 model）

短期记忆与长期记忆分表存储，长期记忆额外维护标签表与关键词倒排索引表。

**ShortTermMemoryModel** — `short_term_memories` 表：

| 列名 | 类型 | 约束/索引 | 说明 |
|---|---|---|---|
| `id` | `Integer` | PK auto | 自增主键 |
| `device_id` | `String(128)` | INDEX | 设备 ID |
| `role` | `String(32)` | - | 角色（user/assistant） |
| `content` | `Text` | - | 消息内容 |
| `timestamp` | `Float` | INDEX | 时间戳 |
| `datetime_str` | `String(32)` | - | 可读时间字符串 |
| `seq` | `Integer` | - | 序列号 |

索引：`idx_stm_device_seq`（`device_id`, `seq`）。

**LongTermMemoryRecordModel**（+`TimestampMixin`）— `long_term_memory_records` 表：

| 列名 | 类型 | 约束/索引 | 说明 |
|---|---|---|---|
| `memory_id` | `String(64)` | PK | 记忆唯一标识 |
| `device_id` | `String(128)` | INDEX | 设备 ID |
| `content` | `Text` | - | 记忆内容 |
| `tags` | `JSON (list)` | - | 标签列表 |
| `keywords` | `JSON (list)` | - | 关键词列表 |
| `source` | `String(32)` | default `"manual"` | 来源 |
| `access_count` | `Integer` | default 0 | 访问计数 |
| `deleted` | `Boolean` | default False | 软删除标记 |

索引：`idx_ltm_device_deleted`、`idx_ltm_device_access`（`device_id`, `deleted`, `access_count`）、`idx_ltm_updated_at`。

**LongTermMemorySummaryLabelModel** — `long_term_memory_summary_labels` 表：

| 列名 | 类型 | 约束/索引 | 说明 |
|---|---|---|---|
| `id` | - | PK auto | 自增主键 |
| `device_id` | `String(128)` | INDEX | 设备 ID |
| `label` | `String(128)` | - | 标签 |
| `ref_count` | `Integer` | - | 引用计数 |

唯一索引：`idx_ltm_sl_device_label`（`device_id`, `label`）。

**LongTermMemoryKeywordIndexModel** — `long_term_memory_keyword_index` 表：

| 列名 | 类型 | 约束/索引 | 说明 |
|---|---|---|---|
| `id` | - | PK auto | 自增主键 |
| `device_id` | `String(128)` | INDEX | 设备 ID |
| `keyword` | `String(128)` | INDEX | 关键词 |
| `memory_id` | `String(64)` | - | 关联记忆 ID |

唯一索引：`idx_ltm_kw_device_kw_mem`（`device_id`, `keyword`, `memory_id`）。

### growth 表族（5 个 model）

用户画像、情绪历史、自学习日志、日记与闹钟共同构成设备的成长数据。

**UserProfileModel**（+`TimestampMixin`）— `user_profiles` 表：

| 列名 | 类型 | 约束/索引 | 说明 |
|---|---|---|---|
| `device_id` | `String(128)` | PK | 设备 ID |
| `name` / `birthday` / `occupation` | `String` | - | 基础信息 |
| `family` | `JSON (list)` | - | 家庭成员 |
| `personality` | `JSON (dict)` | - | 性格 |
| `interests` | `JSON (dict)` | - | 兴趣 |
| `habits` | `JSON (dict)` | - | 习惯 |
| `important_dates` | `JSON (list)` | - | 重要日期 |
| `current_state` | `JSON (dict)` | - | 当前状态 |

**EmotionHistoryModel** — `emotion_history` 表：

| 列名 | 类型 | 约束/索引 | 说明 |
|---|---|---|---|
| `id` | - | PK auto | 自增主键 |
| `device_id` | `String(128)` | INDEX | 设备 ID |
| `timestamp` | `Float` | - | 时间戳 |
| `emotion` | `String(32)` | - | 情绪类型 |
| `intensity` | `Float` | - | 强度 |
| `trigger` | `String(512)` | - | 触发因素 |
| `context` | `String(256)` | - | 上下文 |
| `speaker` | `String(16)` | default `"user"` | 说话方 |

索引：`idx_eh_device_time`（`device_id`, `timestamp`）。

**LearningLogModel** — `learning_logs` 表：

| 列名 | 类型 | 约束/索引 | 说明 |
|---|---|---|---|
| `id` | - | PK auto | 自增主键 |
| `device_id` | `String(128)` | INDEX | 设备 ID |
| `timestamp` | `Float` | - | 时间戳 |
| `action` | `String(32)` | - | 动作 |
| `skill_name` | `String(128)` | - | 技能名 |
| `title` | `String(256)` | - | 标题 |
| `category` | `String(128)` | - | 分类 |

索引：`idx_ll_device_time`（`device_id`, `timestamp`）。

**DiaryModel** — `diaries` 表：

| 列名 | 类型 | 约束/索引 | 说明 |
|---|---|---|---|
| `id` | `Integer` | PK auto | 自增主键 |
| `device_key` | `String(128)` | INDEX NOT NULL | 设备密钥 |
| `date` | `String(16)` | NOT NULL | 日期（`YYYY-MM-DD`）|
| `content` | `Text` | - | 日记内容 |
| `created_at` | `Float` | NOT NULL | 创建时间戳 |

索引：`idx_diary_device_date`（`device_key`, `date`）。

**AlarmModel** — `alarms` 表：

| 列名 | 类型 | 约束/索引 | 说明 |
|---|---|---|---|
| `alarm_id` | `String(64)` | PK | 闹钟唯一标识 |
| `device_key` | `String(128)` | INDEX NOT NULL | 设备密钥 |
| `alarm_type` | `String(16)` | NOT NULL | 类型（`alarm` / `reminder`）|
| `trigger_at` | `Float` | NOT NULL | 触发时间戳 |
| `text` | `Text` | - | 提醒内容 |
| `repeat` | `String(16)` | default `"once"` | 重复模式 |
| `created_at` | `Float` | NOT NULL | 创建时间戳 |

索引：`idx_alarm_device`（`device_key`）。

### skills 表

`SkillModel`（+`TimestampMixin`），`__tablename__ = "skills"`。

| 列名 | 类型 | 约束/索引 | 说明 |
|---|---|---|---|
| `skill_id` | `String(64)` | PK | 技能 ID |
| `name` | `String(128)` | NOT NULL | 技能名 |
| `description` | `Text` | - | 描述 |
| `author` | `String(128)` | - | 作者 |
| `cap_groups` / `category` / `peripherals` / `tags` | `JSON (list)` | - | 能力分组/分类/外设/标签 |
| `manage_mode` | `String(32)` | default `"readonly"` | 管理模式 |
| `device_id` | `String(128)` | default `""` INDEX | 所属设备 |
| `body` | `Text` | - | 技能正文 |
| `file_path` / `directory` | `String(512)` | - | 磁盘路径 |
| `source` | `String(32)` | default `"builtin"` | 来源 |

索引：`idx_skills_name`。

### emo_packs 表

`EmoPackModel`（+`TimestampMixin`），`__tablename__ = "emo_packs"`。GIF 文件仍存磁盘，数据库只存元数据。

| 列名 | 类型 | 约束/索引 | 说明 |
|---|---|---|---|
| `pack_name` | `String(128)` | PK | 表情包名 |
| `display_name` | `String(256)` | NOT NULL | 显示名 |

### wechat_bindings 表

`WeChatBindingModel` 继承 `Base`，`__tablename__ = "wechat_bindings"`，记录微信账号与设备的绑定关系（替代 `wechat_bindings.json`）。

| 列名 | 类型 | 约束/索引 | 说明 |
|---|---|---|---|
| `wechat_chat_id` | `String(128)` | PK | 微信会话 ID |
| `wechat_user_id` | `String(128)` | - | 微信用户 ID |
| `device_key` | `String(128)` | INDEX NOT NULL | 绑定的设备密钥 |
| `device_mac` | `String(64)` | - | 设备 MAC 地址 |
| `bound_at` | `Float` | NOT NULL | 绑定时间戳 |
| `wechat_group_id` | `String(64)` | - | 微信群 ID |
| `alias` | `Text` | - | 别名 |

## 迁移机制

项目不使用 Alembic 版本化迁移，而是依赖 `Base.metadata.create_all` 的幂等行为完成建表。`schema.py` 中的 `init_db()` 实现如下：

```python
async with engine.begin() as conn:
    await conn.run_sync(Base.metadata.create_all)
```

`create_all` 只创建尚不存在的表，不会修改已存在表的结构，因此可以安全地重复调用。当 schema 变更需要修改已存在表的列定义时，需要手动处理数据迁移或重建表。

测试场景下提供 `drop_all_tables()`，通过 `Base.metadata.drop_all` 清空所有表，便于测试用例之间隔离。

## 仓储模式

### 领域抽象基类

领域层 `domain/repositories.py` 定义了与具体实现解耦的抽象基类，`MemoryRepository`（短期记忆接口）定义在 `src/use_cases/ports.py`。

| 抽象基类 | 职责 |
|---|---|
| `ToolConfigRepository` | 工具配置抽象 |
| `ASRRepository` | ASR 仓储抽象 |
| `TTSRepository` | TTS 仓储抽象 |
| `LLMRepository` | LLM 仓储抽象 |
| `ToolRepository` | 工具仓储抽象 |
| `LongTermMemoryRepository` | 长期记忆仓储抽象 |
| `MemoryRepository` | 短期记忆仓储抽象 |

### 仓储实现

`infrastructure/db/repositories/` 下共 7 个文件、11 个仓储类：

| # | 仓储类 | 文件 | 职责 | 关键方法 |
|---|---|---|---|---|
| 1 | `DeviceRepository` | `device_repository.py` | 设备配置 CRUD（替代 `users.json`），异步+同步双接口 | `get_device_config`, `get_all_devices`, `upsert_device`（SQLite UPSERT）, `update_device_partial`（深度合并 `_deep_merge`）, `find_by_key`, `find_by_mac`, `add_skill_to_device`, `toggle_skill`, `get`/`set`/`delete_mcp_server`, `load_all_devices_sync` |
| 2 | `EmoPackRepository` | `emo_repository.py` | 表情包元数据 + 设备激活表情包 | `list_packs`, `get_pack_meta`, `upsert_pack`, `delete_pack`, `get_active_pack`（读 devices 表）, `set_active_pack`（写 devices 表） |
| 3 | `UserProfileRepository` | `growth_repositories.py` | 用户画像 UPSERT | `get`, `upsert`（ON CONFLICT DO UPDATE）, `update_partial` |
| 4 | `EmotionHistoryRepository` | `growth_repositories.py` | 情绪历史 Append-only + trim 100 | `append`（含 `_trim`）, `list_all`, `list_since` |
| 5 | `LearningLogRepository` | `growth_repositories.py` | 自学习日志 Append-only + trim 100 | `append`（含 `_trim`）, `list_all` |
| 6 | `SqlLongTermMemoryRepository`（继承 `LongTermMemoryRepository`） | `ltm_repository.py` | 长期记忆 CRUD + 索引重建 | `save`（UPSERT + `_rebuild_index`）, `find_by_labels`, `find_all`, `find_by_id`, `mark_deleted`（软删除）, `get_summary_labels`, `increment_access`（原子 UPDATE +1） |
| 7 | `SqlShortTermMemoryRepository`（继承 `MemoryRepository`，同步） | `short_term_memory_repo.py` | 短期对话历史（同步） | `load`, `save`（事务内 DELETE + batch INSERT）, `delete` |
| 8 | `SkillRepository` | `skill_repository.py` | 技能 CRUD + 磁盘 SKILL.md 同步 | 异步：`get_skill`, `get_catalog`, `upsert_skill`, `delete_skill`, `list_skills_by_device`；同步：`init_sync` |
| 9 | `AlarmRepository` | `growth_repositories.py` | 闹钟 CRUD | `list`, `upsert`, `delete`, `get` |
| 10 | `DiaryRepository` | `growth_repositories.py` | 日记 CRUD | `list`, `upsert`, `delete` |
| 11 | `WeChatBindingRepository` | `wechat_binding_repository.py` | 设备-微信绑定 | `find_by_device_key`, `find_by_wechat_union_id`, `upsert`, `delete` |

### 通用设计要点

**UPSERT 统一实现**：所有写或更新操作统一使用 `sqlalchemy.dialects.sqlite.insert` 配合 `on_conflict_do_update`。冲突时 `created_at` 保留原值、`updated_at` 刷新为当前时间，避免覆盖创建时间。

**会话获取**：异步仓储通过 `get_session_ctx()`（contextmanager）获取会话，同步仓储通过 `get_sync_session()` 获取。两种获取方式分别对应不同的调用上下文，同步仓储主要服务于与同步框架交互的场景。

**dict 与 Model 转换**：每个仓储内部实现 `_model_to_dict` 与 `_dict_to_model_fields`，处理 JSON 列与 Python dict/list 之间的序列化差异，对调用方屏蔽 ORM 细节。

**索引重建（LTM）**：`_rebuild_index` 在长期记忆写入时触发，先删除该记忆的旧索引记录，再从活跃记忆的 `tags[:3]` 重建 `summary_labels`（含 `ref_count` 计数），从 `keywords` 重建倒排索引表。

**Append-only + trim**：`EmotionHistoryRepository` 与 `LearningLogRepository` 在插入新记录后，通过子查询保留该设备最新的 100 条记录，超出部分删除，避免历史数据无限增长。

## 设计约束

整个 `data` 目录与数据库文件通过 `.gitignore` 排除，运行时数据不进入版本控制。早期基于 JSON 文件的存储方式已被完全消除，所有结构化数据统一通过 SQLite 表与仓储抽象访问，配置类数据（如设备配置）与运行时数据（如记忆、情绪历史）共用同一套持久化基础设施。
