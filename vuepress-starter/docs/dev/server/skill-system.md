# 技能系统

## 概述

技能系统通过 `SKILL.md` 文件定义 LLM 的行为规则，将特定场景下的回复逻辑以可插拔的方式注入到对话流程中。每个技能包含触发条件描述、执行步骤和工具依赖，由 LLM 在运行时根据用户输入自主判断是否激活。系统按设备维度过滤可见技能，将精简后的目录渲染进 system prompt，使不同设备能够获得差异化的能力集合。

技能的来源分为两类：全局技能位于 `src/skills/` 下，所有设备默认可见；设备自学习技能位于 `data_dir/devices/*/skills/` 下，仅对所属设备可见。两类技能共用同一套发现、加载、渲染流程，由 `SkillService` 统一管理，持久化层则通过 `SkillRepository` 在 SQLite 中维护镜像，处于文件系统与数据库双写的过渡阶段。

## 技能发现与加载

技能发现由 `src/use_cases/skill_system.py` 中的 `SkillService` 实现，依赖模块级全局注册表保存已加载的技能条目。

### 全局注册表

注册表在模块加载时初始化为空，`init()` 调用时先清空再重新填充：

| 变量 | 类型 | 用途 |
|---|---|---|
| `_skills_by_id` | `dict[str, SkillEntry]` | 按技能 ID 索引，O(1) 查找 |
| `_skills_by_device` | `dict[str, list[SkillEntry]]` | 按设备 ID 分组的设备自学习技能（已预留，当前未填充）|
| `_global_skills` | `list[SkillEntry]` | 全局技能列表 |
| `_skills_dir` | `str` | 已扫描的技能根目录，用于 `reload()` |

### init 扫描机制

`init(skills_root_dir, data_dir="")` 的执行顺序如下：

1. 清空上述四个注册表
2. 调用 `_scan_directory(skills_root_dir, device_id="")` 扁平扫描 `src/skills/` 下所有子目录，每个子目录视为一个全局技能
3. 若提供 `data_dir`，调用 `_scan_device_skills(data_dir)` 扫描 `data_dir/devices/*/skills/*` 加载设备自学习技能
4. 输出加载总数日志

设备自学习技能的 device_id 解析依赖数据库映射：`_scan_device_skills` 通过 `DeviceRepository.load_all_devices_sync()` 建立 key → MAC 映射表，能匹配到则用 MAC 作为 `device_id`，匹配不到时回退使用目录名作为 `device_id`。使用 MAC 而非目录名是为了与 API 查询时的设备标识保持一致。

### _load_skill

`_load_skill(skill_dir, device_id="")` 负责单个技能的加载：

- `skill_id` 取 `basename(skill_dir)`，目录下须存在 `SKILL.md`，否则跳过
- 调用 `_parse_skill_md` 解析 frontmatter 和 body
- 校验 `meta.name` 与目录名是否一致，不一致仅输出 warning，不阻断加载
- 注册到 `_skills_by_id` 和 `_global_skills`，遇到同名旧条目直接替换

### reload 热更新

`reload()` 重调 `init(_skills_dir)`，复用上次记录的技能根目录重新扫描加载。该函数用于运行时刷新技能内容，无需重启进程。

## SKILL.md 格式规范

技能通过 `SKILL.md` 文件描述，由 `_parse_skill_md(path)` 解析。解析逻辑使用正则 `r"^---\s*\n(.*?)\n---\s*\n"`（DOTALL 模式）提取 frontmatter 块，frontmatter 之后的全部内容作为 body。

### frontmatter 格式

frontmatter 使用 **JSON 格式**（非 YAML），用 `---` 行包裹。顶层字段包含 `name`、`description`、可选的 `author`，其余配置归入 `metadata` 对象：

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | string | 技能 ID，需与目录名一致 |
| `description` | string | 触发条件描述，注入 catalog 供 LLM 判断激活 |
| `author` | string | 作者，可选 |
| `metadata.cap_groups` | list[string] | 工具能力组，如 `["tools:get_current_time"]` |
| `metadata.manage_mode` | string | 管理模式，默认 `"readonly"` |
| `metadata.category` | list[string] | 分类，如 `["entertainment"]` |
| `metadata.peripherals` | list | 外设依赖 |
| `metadata.tags` | list[string] | 标签 |

### body 编写规范

body 为自由 Markdown，常用结构为 `#` 标题 → 触发说明 → `## 重要规则` → `## 执行步骤`。body 中可使用 `{CUR_SKILL_DIR}` 占位符，运行时由 `get_skill_document` 替换为技能目录的绝对路径，便于在规则中引用技能目录下的静态资源。

### 示例一 猜数字游戏

含工具依赖与多步骤规则的典型技能，位于 `src/skills/guess_number/SKILL.md`：

```markdown
---
{
  "name": "guess_number",
  "description": "猜数字大小游戏。用户说 猜数字、猜大小、继续猜、玩个游戏 时激活此技能",
  "metadata": {
    "cap_groups": ["tools:get_current_time"],
    "manage_mode": "readonly",
    "category": ["entertainment"],
    "tags": ["game", "guess", "entertainment"]
  }
}
---

# 猜数字游戏

用户说"猜数字"、"猜大小"、"玩个游戏"、"继续猜"时使用此 Skill。

## 重要规则（必须遵守）
- 在任何情况下都**不能说出或暗示秘密数字**...
- **不要重复读取技能说明**...

## 开局（用户第一次说猜数字）
1. 调用 `get_current_time` 获取当前时间，生成一个 1-100 的随机数
2. 回复格式：`好的，来玩猜数字游戏！...[secret:XX]`
```

### 示例二 故事

无工具依赖的纯内容型技能，位于 `src/skills/gushi/SKILL.md`，`metadata` 中各数组字段为空：

```markdown
---
{
  "name": "gushi",
  "description": "当用户想听故事的时候触发此技能，然后你在下面的故事中随便选一个。",
  "metadata": {
    "cap_groups": [],
    "manage_mode": "readonly",
    "category": [],
    "tags": []
  }
}
---

## 山间小驿
深山里藏着一间不起眼的小驿...
```

### 示例三 设备专属测试

仅特定设备可见的测试技能，位于 `src/skills/test_device_only/SKILL.md`：

```markdown
---
{
  "name": "test_device_only",
  "description": "验证设备技能是否生效",
  "metadata": {
    "cap_groups": ["tools:get_current_time"],
    "manage_mode": "readonly",
    "category": ["utility"],
    "tags": ["test", "device"]
  }
}
---

# 设备专属测试
此技能仅厨房设备(esp32_kitchen)可见，用于验证设备过滤功能。
## 执行步骤
1. 调用 `get_current_time` 获取当前时间
2. 返回："🔧 设备专属技能生效！当前厨房设备时间: [时间]"
```

## 技能目录预渲染

技能目录预渲染负责把已加载的技能按设备维度过滤后，以精简形式注入 LLM 的 system prompt。`SkillCatalogEntry` 是 LLM 看到的精简结构，仅包含 `id`、`description`、`category`、`tags`、`device_id` 字段。

### get_catalog 设备过滤逻辑

`get_catalog(device_id="", skills=None)` 按下表规则组装可见技能列表：

| `skills` 取值 | 行为 |
|---|---|
| `None` | 返回所有全局技能（向后兼容） |
| `[]` | 仅返回该设备的自学习技能 |
| `["skill_a", "skill_b"]` | 返回列表中的全局技能加上该设备的自学习技能 |

设备自学习技能（`skill.metadata.device_id == device_id`）始终自动包含，无需在 `skills` 列表中显式声明。

### render_skills_catalog 注入 system prompt

`render_skills_catalog(device_id="", skills=None, disabled_skills=None)` 在 `get_catalog` 基础上过滤 `disabled_skills`，再按文档长度决定渲染方式，输出固定头部：

```
## 技能规则 (Skill Rules)
你拥有以下技能。当用户的输入匹配某个技能的触发条件时，
**必须严格按照该技能的执行步骤回复**...
```

长短技能的渲染策略如下：

| 技能文档长度 | 渲染方式 |
|---|---|
| ≤ 500 字 | 直接内联完整文档，包含 `### 技能: {id}`、触发条件、执行规则 |
| > 500 字 | 仅列出目录条目，提示 LLM 使用 `read_skill_document("skill_id")` 工具查看详情 |

`get_skill_document` 在返回 body 前会将 `{CUR_SKILL_DIR}` 占位符替换为实际技能目录路径。

## 技能激活机制

技能系统没有显式的"激活"函数。激活由 LLM 根据注入 catalog 中的触发条件 `description` 自主判断：当用户输入匹配某个技能的描述时，LLM 选择该技能并按内联的执行步骤回复，或先调用 `read_skill_document` 读取完整说明再执行。

设备可见性由 `is_skill_available_for_device(skill_id, device_id, skills)` 控制，规则与 `get_catalog` 一致：

| `skills` 取值 | 可见性 |
|---|---|
| `None` | 全部可见 |
| `[]` | 全部不可见（仅设备自学习除外） |
| 列表 | 需在列表中或属于该设备自学习技能 |

被禁用的技能（出现在 `disabled_skills` 中）即使可见也不会出现在渲染目录中，`read_skill_document` 工具被调用时也会返回禁用提示。

## 技能工具

技能工具定义在 `skill_tools.py` 中，通过 `@tool()` 装饰器注册到工具系统，供 LLM 在对话中调用。

| 工具 | 签名 | 职责 |
|---|---|---|
| `list_skills` | `(tool_manager=None) -> str` | 列出设备可用技能。尝试从 `tool_manager.device_id` 取设备 ID（运行时通常为空，实际列出全局技能），调用 `skill_system.get_catalog`，过滤 `tool_manager.user_config.disabled_skills`，渲染 `## 可用技能列表`，每条格式为 `**{id}**: {description} [tags] [设备专属]`，末尾提示使用 `read_skill_document` 查看详情 |
| `read_skill_document` | `(skill_id: str, tool_manager=None) -> str` | 读取技能详细文档。先检查 `disabled_skills`，禁用则返回提示；否则调用 `skill_system.get_skill_document(skill_id)`。技能不存在时列出当前可用技能 ID 供 LLM 参考 |

## 技能管理 API

`SkillService` 提供三个管理方法用于运行时增删改技能。其中 `create_skill` 会校验 `skill_id`（名称）匹配正则 `^[a-z][a-z0-9_]*$`（小写字母开头、仅含小写字母数字下划线）；`update_skill` / `delete_skill` 仅检查技能存在性，不重复校验正则。

| 方法 | 行为 |
|---|---|
| `create_skill(name, description, instructions, category, tags, cap_groups)` | 校验名称合法性，生成标准 `SKILL.md`（frontmatter + `# name` + `## 执行步骤`），写盘后调用加载逻辑注册到内存 |
| `update_skill(skill_id, description, instructions, category, tags, cap_groups)` | 重写 frontmatter 与 body，重新加载到内存替换旧条目 |
| `delete_skill(skill_id)` | 调用 `shutil.rmtree` 删除技能目录，并从内存注册表注销 |

## 数据存储

技能的持久化由 `SkillRepository`（`infrastructure/db/repositories/skill_repository.py`）承担，底层模型为 `SkillModel`（`infrastructure/db/models/skill.py`）。当前处于文件系统与数据库双写的过渡期，`file_path` 和 `directory` 字段保留文件系统链接，便于回退。

### SkillModel 表结构

`SkillModel` 映射到 `skills` 表，包含 `TimestampMixin` 提供的时间戳字段：

| 列 | 类型 | 说明 |
|---|---|---|
| `skill_id` | String(64) | 主键 |
| `name` | String(128) | NOT NULL |
| `description` | Text | 默认 `""` |
| `author` | String(128) | 默认 `""` |
| `cap_groups` | JSON | list |
| `category` | JSON | list |
| `peripherals` | JSON | list |
| `tags` | JSON | list |
| `manage_mode` | String(32) | 默认 `"readonly"` |
| `device_id` | String(128) | 默认 `""`，建索引；空表示全局技能 |
| `body` | Text | Markdown 正文 |
| `file_path` | String(512) | 文件系统链接（过渡期） |
| `directory` | String(512) | 同上 |
| `source` | String(32) | 默认 `"builtin"` |
| `created_at` / `updated_at` | Float | `TimestampMixin` |

表上建有 `idx_skills_name` 索引，加速按名称查询。

### SkillRepository 仓储

`SkillRepository` 将 frontmatter 字段拍平为表列，`body` 单独存储 Markdown 正文，替代直接的 `SKILL.md` 文件读写。异步方法供路由层通过 `get_session_ctx` 调用：

| 方法 | 说明 |
|---|---|
| `get_skill(skill_id)` | 返回 frontmatter + body 组成的 dict，不存在返回 `None` |
| `get_catalog(device_id=None, skills_filter=None)` | 返回设备可见目录，过滤逻辑同 `skill_system.get_catalog`；返回 `[{id, description, category, tags, device_id}]` |
| `upsert_skill(skill_id, frontmatter, body)` | SQLite UPSERT；冲突时仅更新 frontmatter 字段、`body`、`updated_at`，不覆盖 `file_path`/`directory`/`source`/`device_id` |
| `delete_skill(skill_id)` | 仅删除 DB 记录，不删磁盘文件 |
| `list_skills_by_device(device_id)` | 列出指定设备的自学习技能 |

同步方法 `init_sync(skills_root_dir, data_dir="")` 在启动时执行：

1. 扁平扫描 `skills_root_dir` 加载全局技能，`device_id=""`，`source="builtin"`
2. 扫描 `data_dir/devices/*/skills/*` 加载设备自学习技能，通过 `_load_key_to_mac_mapping` 解析 `device_id`，`source="self_learning"`
3. 对每个技能调用 `_sync_one_from_disk(skill_dir, device_id="")` UPSERT 到 DB

`_sync_one_from_disk` 的 `source` 字段**优先取 frontmatter `metadata.source`**，未指定时才按是否传入 `device_id` 回退：有 `device_id` 时默认 `"self_learning"`，否则为 `"builtin"`。
