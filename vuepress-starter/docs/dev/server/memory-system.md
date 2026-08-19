# 记忆系统

## 概述

小明同学 采用双层记忆架构，将对话上下文与跨会话知识分别存储。短期记忆维护当前会话内的消息流，按设备隔离，用于构建 LLM 上下文；长期记忆跨会话沉淀用户的事实、偏好与历史，通过摘要标签与关键词倒排索引支持召回。

两层记忆均通过仓储层落盘到 SQLite，由 `ConversationMemory` 负责短期、`LongTermMemoryServiceImpl` 负责长期。短期记忆以滑动窗口控制上下文规模，长期记忆通过语义去重、软删除、访问计数实现可控的知识积累与遗忘。Pipeline 在每次推理流程中编排两者：先注入长期记忆目录到 system prompt，再用短期记忆构建消息列表，流结束后写入新消息并触发自动提取。

## 短期记忆

`ConversationMemory` 按 `device_id` 隔离会话历史，数据通过 `MemoryRepository` 落盘到 `short_term_memories` 表。为避免在 `__init__` 中同步执行 5-30ms 的 DB I/O 阻塞事件循环，构造函数仅初始化 `_messages` 列表与 `_loaded` 延迟加载标记，不调用 `repository.load()`。

构造函数签名：

```python
def __init__(self, max_messages: int = 20, device_id: str = "", repository=None)
```

### 延迟加载机制

`ensure_loaded()` 在首次使用历史时按需加载：

```python
async def ensure_loaded(self) -> None
```

首次调用通过 `asyncio.to_thread(self._repository.load, self._device_id)` 在线程池中执行 DB 读取，避免阻塞事件循环；后续调用由 `_loaded` 守卫直接返回。加载失败时记录 warning 并将 `messages` 置空，使会话可继续以空上下文运行。

### 消息存储格式

`add_message` 写入的消息字典结构：

```python
{"role": str, "content": str, "timestamp": float, "datetime": "%Y-%m-%d %H:%M:%S"}
```

空消息直接跳过；超过 `MAX_CHARS_PER_MESSAGE` 的内容截断至 2000 字符。落盘策略分两种路径：异步上下文使用 `_loop.create_task(asyncio.to_thread(repo.save, ...))` 后台写入，同步上下文（如单元测试）直接调用同步写。写入流程为**先 `_trim()` 收缩窗口，再落盘**。便捷方法 `add_user_message` 与 `add_assistant_message` 封装了常见 role 的写入。

### 构建 LLM 上下文

`build_messages(system_prompt, current_user_message)` 拼接 LLM 输入：

- 结构为 `[system(1)] + history(self._messages) + [current_user(1)]`
- 当前用户消息超长时同样截断至 2000 字符
- 日志输出形如 `system(1) + history(N) + user(1) = total`，便于排查上下文规模

### 滑动窗口

`_trim()` 同时执行条数与 Token 双重限制：

- 条数超限：`while len > max_messages: pop(0)`，FIFO 移除最早消息
- Token 超限：`while total_tokens > MAX_TOKENS_ESTIMATE: pop(0)`，Token 估算公式为 `len(text) // 2`

两种检查顺序执行，保证上下文既不超过消息条数也不超过 Token 上限。

### 常量表

| 常量 | 值 | 说明 |
|---|---|---|
| `MAX_CHARS_PER_MESSAGE` | 2000 | 单条消息截断阈值 |
| `MAX_TOKENS_ESTIMATE` | 2000 | Token 上限，估算公式 `len(text)//2` |

其他成员：`clear()` 清空内存并删除 DB 记录；`message_count` 与 `is_empty` 属性供外部查询。

## 长期记忆

`LongTermMemoryServiceImpl` 依赖注入 `LongTermMemoryRepository`，提供跨会话事实的存储、召回、更新与遗忘能力。所有记忆以 `MemoryItem` 实体表示，召回条件由 `MemoryQuery` 值对象描述。

### MemoryItem 实体

| 字段 | 类型 | 说明 |
|---|---|---|
| `memory_id` | `str` | 形如 `mem-{timestamp}-{uuid 前 4 位}` |
| `device_id` | `str` | 设备隔离键 |
| `content` | `str` | 归一化记忆事实，核心字段 |
| `tags` | `list[str]` | 摘要标签，驱动 summary catalog |
| `keywords` | `list[str]` | 关键词，驱动倒排索引 |
| `source` | `str` | `manual` 或 `auto_llm` |
| `created_at` | `float` | 创建时间戳 |
| `updated_at` | `float` | 更新时间戳 |
| `access_count` | `int` | 访问计数，影响召回排序 |
| `deleted` | `bool` | 软删除标记 |

`to_dict()` / `from_dict()` 负责序列化；`summary_labels` property 返回 `tags[:3]`，作为摘要标签的实际来源。

### MemoryQuery 值对象

```python
@dataclass(frozen=True)
class MemoryQuery:
    device_id: str = ""
    summary_labels: tuple[str, ...] = ()   # 摘要标签过滤，精确匹配
    keyword: str = ""                       # 关键词搜索
    limit: int = 8                          # 返回上限
```

`frozen=True` 使其可哈希、不可变，适合作为参数在服务层传递。

### 核心方法

| 方法 | 签名 | 逻辑 |
|---|---|---|
| `store` | `async (item: MemoryItem) -> tuple[str, bool]` | 校验 content → 归一化 tags/keywords（各截前 3）→ 生成 `memory_id = "mem-{int(now)}-{uuid.hex[:4]}"` → 全量拉取做语义去重 → 命中则 `increment_access` 返回 `(ex_id, False)`；否则 `repo.save` 返回 `(id, True)` |
| `recall` | `async (query: MemoryQuery) -> list[MemoryItem]` | `repo.find_by_labels(device_id, summary_labels, limit or 8)` → 对每条结果 `increment_access` |
| `list_all` | `async (device_id) -> list[MemoryItem]` | `repo.find_all(device_id)` |
| `update` | `async (memory_id, patch: dict, device_id) -> bool` | 找 old → `mark_deleted(old)` → 用 patch 构造新 `MemoryItem` → `store(new)`，返回 `changed` |
| `forget` | `async (memory_id, device_id) -> Optional[MemoryItem]` | 找到后 `mark_deleted` 软删除，返回被删 item；未找到返回 `None` |

`store` 返回值的布尔位表示是否新增：`True` 为新写入，`False` 为命中已有记忆并提升访问计数。

### 语义去重机制

`store` 在写入前全量拉取该设备的活跃记忆，调用 `_items_semantically_match` 逐条比较。匹配规则包含两层：归一化后的 key 比较，以及子串包含判断。命中已有记忆时不创建新记录，而是对该记忆执行 `increment_access`，提升其在后续召回中的排序优先级。这种设计避免同一事实被重复存储，同时通过访问计数反映记忆的重要度。

### 标签目录缓存机制

`get_summary_catalog(device_id)` 渲染固定前缀文本供 LLM 使用：

```
Long-term memory summary label catalog (use exact labels with memory_recall):
- {label1}
- {label2}
```

标签来源是仓储层 `_rebuild_index` 聚合所有活跃记忆的 `tags[:3]`，统计 `ref_count` 写入 `LongTermMemorySummaryLabelModel`。该 catalog 注入 `auto_extract` 的 user prompt，辅助 LLM 判断新记忆是否与现有标签重合，从而决定是新增还是遗忘。

### 自动提取流程

`auto_extract(device_id, user_message, llm_chat_func)` 流程：

1. 系统提示 `_AUTO_EXTRACT_SYSTEM_PROMPT` 要求 LLM 返回 JSON：`{"intent":"none|forget|replace","memories":[{"content","tags","keywords"}]}`
2. 注入现有 catalog 帮助去重判断
3. `intent=forget` 时直接返回空列表，表示用户意图为遗忘
4. `_parse_llm_json` 兼容 markdown 代码块和裸 JSON 两种返回格式
5. 对 `memories[:3]` 逐条构造 `MemoryItem(source="auto_llm")` 调用 `store`，将 `changed=True` 的条目拼成摘要列表返回

`MAX_AUTO_EXTRACT_ITEMS = 3` 限制单次提取数量，避免 LLM 一次性灌入过多记忆冲击索引。辅助方法 `_normalize_tags` 去重保序；`_normalize_keywords` 要求关键词必须出现在 content 或 tags 中，否则回退到 `item.tags[:3]`。

## 数据表设计

记忆系统共四张 SQLite 表，分别承载短期消息、长期记忆主记录、摘要标签索引与关键词倒排索引。表定义位于 `infrastructure/db/models/memory.py`。

### 短期记忆表

`short_term_memories`（`ShortTermMemoryModel`）：

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | Integer PK | 自增 |
| `device_id` | String(128) | 索引 |
| `role` | String(32) | 消息角色 |
| `content` | Text | 消息内容 |
| `timestamp` | Float | 索引 |
| `datetime_str` | String(32) | 可读时间 |
| `seq` | Integer | 列表序号 |

索引：`idx_stm_device_seq (device_id, seq)`，支撑按设备拉取并按序号排序。

### 长期记忆主表

`long_term_memory_records`（`LongTermMemoryRecordModel`，含 `TimestampMixin`）：

| 列 | 类型 | 说明 |
|---|---|---|
| `memory_id` | String(64) PK | 主键 |
| `device_id` | String(128) | 索引 |
| `content` | Text | 记忆事实 |
| `tags` | JSON | list |
| `keywords` | JSON | list |
| `source` | String(32) | default `manual` |
| `access_count` | Integer | default 0 |
| `deleted` | Boolean | default False |
| `created_at` / `updated_at` | Float | TimestampMixin |

索引：`idx_ltm_device_deleted`、`idx_ltm_device_access (device_id, deleted, access_count)`、`idx_ltm_updated_at`。`access_count` 纳入复合索引，使按设备过滤并按访问频次排序的查询走索引。

### 摘要标签索引表

`long_term_memory_summary_labels`（`LongTermMemorySummaryLabelModel`）：

| 列 | 类型 |
|---|---|
| `id` | Integer PK |
| `device_id` | String(128) 索引 |
| `label` | String(128) |
| `ref_count` | Integer |

唯一索引：`idx_ltm_sl_device_label (device_id, label)`，支撑 catalog 的聚合与去重。

### 关键词倒排索引表

`long_term_memory_keyword_index`（`LongTermMemoryKeywordIndexModel`）：

| 列 | 类型 |
|---|---|
| `id` | Integer PK |
| `device_id` | String(128) 索引 |
| `keyword` | String(128) 索引 |
| `memory_id` | String(64) |

唯一索引：`idx_ltm_kw_device_kw_mem (device_id, keyword, memory_id)`，按关键词反查记忆 id。

## 仓储实现

仓储层封装所有 SQL 细节，服务层只面对 `MemoryItem` 与 `MemoryQuery`。长期仓储为异步友好设计，短期仓储保持同步以简化事务控制。

### SqlLongTermMemoryRepository

| 方法 | 实现要点 |
|---|---|
| `save` | SQLite UPSERT（`INSERT ... ON CONFLICT DO UPDATE`），冲突时保留 `created_at`、刷新 `updated_at`，随后 `_rebuild_index` |
| `find_by_labels` | 拉全部活跃记忆后内存过滤 tags（任一匹配），按 `access_count` 降序，`limit or 8` |
| `find_all` / `find_by_id` | 均按 `deleted=False` 过滤 |
| `mark_deleted` | 软删除 + flush + 重建索引 |
| `increment_access` | 原子 `UPDATE ... SET access_count = access_count + 1`，避免读改写竞态 |
| `_rebuild_index` | 删旧 → 从活跃记忆 `tags[:3]` 聚合 `ref_count` 重建 summary_labels（UPSERT）→ 从 keywords 重建倒排索引（同条记忆内去重，`ON CONFLICT DO NOTHING`） |

`increment_access` 的原子 UPDATE 是关键设计：召回流程会对每条结果调用一次，若采用先读后写会出现并发覆盖；直接在 SQL 层自增避开竞态。`_rebuild_index` 在每次写入、软删除后执行，使摘要标签和关键词索引与主表保持一致。

### SqlShortTermMemoryRepository

该仓储为同步实现，方法：

- `load(device_id)`：按 `seq` 升序返回 `[{role, content, timestamp, datetime}]`
- `save(device_id, messages)`：事务内 `DELETE` + batch `INSERT`，`seq` 取列表索引
- `delete(device_id)`：清空该设备全部记录

事务内 DELETE + INSERT 的写法保证短期记忆的整表替换原子性：要么新消息全部生效，要么保留旧消息，不会出现部分写入导致 `seq` 断裂。

## Pipeline 集成

Pipeline 在 `pipeline.run` 中编排两层记忆，使每次推理都能利用历史上下文并沉淀新知识。

### System Prompt 注入

构建 system prompt 时注入 LTM summary catalog，`_ltm_catalog_ttl=60s` 缓存避免每次推理都查库。catalog 文本作为 system prompt 的一部分，让 LLM 感知可用的记忆标签，从而在需要时通过 `memory_recall` 工具精确召回。

### build_messages 流程

调用 `conversation_memory.build_messages(sp, iat_text)` 构建消息列表前，先 `await conversation_memory.ensure_loaded()` 触发延迟加载。这样首次推理才产生 DB 读，未使用的设备不会无谓查库。

### 流结束后写入

`_llm_task` 流结束后执行两步：先 `add_user_message(iat_text)` 与 `add_assistant_message(full_text)` 记录本轮对话，再异步触发 `ltm_service.auto_extract` 从用户消息中提取可能的长期记忆。两步分离使主响应路径不被记忆提取阻塞，提取失败也不影响对话历史写入。

## 记忆工具

`builtin_tools.py` 暴露 5 个**记忆相关**内置工具，供 LLM 在对话中按需操作长期记忆。所有工具通过 `tool_manager` 访问对应设备的 `LongTermMemoryService` 实例。

| 工具名 | 参数 | 职责 |
|---|---|---|
| `memory_store` | `content`, `device_id`, `tags`, `keywords`, `tool_manager` | 存储长期记忆，触发语义去重与索引重建 |
| `memory_recall` | `summary_labels`, `device_id`, `limit`, `tool_manager` | 按摘要标签召回，命中条目自增访问计数 |
| `memory_list` | `device_id`, `tool_manager` | 列出该设备全部活跃记忆 |
| `memory_update` | `memory_id`, `device_id`, `content`, `tags`, `keywords`, `tool_manager` | 软删旧记忆后写入新记忆，返回是否变更 |
| `memory_forget` | `memory_id`, `device_id`, `tool_manager` | 软删除指定记忆，返回被删 item 或 None |

工具层不直接操作 DB，全部委托给 `LongTermMemoryService`，因此 UPSERT、`_rebuild_index`、`increment_access` 等逻辑在工具调用与 `auto_extract` 路径中行为一致。
