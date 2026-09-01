# 插件沙箱机制

第三方插件是"不可信代码"——它可能来自任何一个上传者，里面可能藏着恶意逻辑。本系统对已安装的插件运行在**独立子进程沙箱**中，用多层防御隔离插件与主服务：插件拿不到服务器密钥、连不上内网、写不了任意文件、调不动操作系统接口，只能通过一套受控的 SDK 接口做"系统允许它做的事"。

::: tip 适用范围
- **已安装插件**（`data/plugins/installed/`，来自市场或 zip 上传）：**完整沙箱**隔离，本篇的主角。
- **内置插件**（`src/plugins/`，随源码分发）：第一方可信代码，走进程内加载，只过权限声明门，不隔离。
:::

## 威胁模型：防的是什么

| 恶意行为 | 示例 | 沙箱对策 |
|----------|------|----------|
| 窃取密钥 | 读 `os.environ` 里的 API Key、读 `.env` 文件 | 环境变量擦除 + 文件系统命名空间 |
| 攻击内网 | 连接 `192.168.x.x` 或云元数据地址扫描内网 | 网络权限裁决 + SSRF 防护 |
| 破坏数据 | 删改服务器任意文件、改数据库 | 文件系统命名空间 + DB 权限裁决 |
| 执行系统命令 | `os.system` / `subprocess` 反弹 shell | audit 钩子直接拦截 |
| 拖垮服务 | 死循环、无限阻塞、内存泄漏 | 独立进程 + 工具调用超时杀进程 |
| 窃听数据 | 读取服务器源码、其他用户数据 | import 白名单 + 文件系统命名空间 + 设备数据权限 |

**设计原则**：不信任插件、不信任它 import 的模块、不信任它的任何输入；所有"能力"必须显式声明（权限）且经过主进程裁决。

---

## 架构总览

```
┌──────────────────────── 主进程（信任边界） ────────────────────────┐
│   plugin_loader / supervisor                                      │
│   ├── 启动子进程、喂 stdin / 收 stdout（JSON 行协议）              │
│   ├── Adjudicator 裁决器：按 manifest 权限裁决每个 SDK 调用        │
│   └── 真实凭据/设备连接/数据库 都在主进程手里，插件永远接触不到     │
└───────────────┬──────────────────────────────────┬────────────────┘
                │  spawn: python -m ...runner      │  JSON-Lines RPC
                ▼                                  ▼
┌──────────────────────── 子进程（沙箱内） ──────────────────────────┐
│   runner + sandbox                                                │
│   1. 擦除环境变量（只留系统必需）                                  │
│   2. 清理 sys.modules 里的危险预导入模块                            │
│   3. 安装 sys.meta_path import 白名单钩子                          │
│   4. 安装 sys.addaudithook 审计钩子                                │
│   5. 注入 SDK 桩模块（src.use_cases.* 的替身）                     │
│   6. 加载 plugin.py，@tool 注册到本地工具表                        │
│   7. 上报 ready → 进入事件循环，服务 RPC                          │
└───────────────────────────────────────────────────────────────────┘
```

---

## 七层防护详解

### 第一层：进程隔离

插件跑在独立子进程里，与主服务物理隔离：

- 插件崩溃/被 OOM 杀死，不影响主服务
- 插件死循环/卡死，主进程在工具调用超时后直接杀掉子进程
- 插件拿不到主进程的内存、文件句柄、网络连接

启动命令（主进程侧生成）：

```
python -m src.infrastructure.plugin_host.runner <plugin_dir> <plugin_id> <allow_file>
```

- 工作目录 = 插件目录（插件只能看到自己的地盘）
- 环境变量：仅注入 `PYTHONPATH`（指向服务器源码，供 SDK 桩使用）与系统必需项
- 工具调用超时：默认 120 秒，超时即终止子进程

### 第二层：环境变量擦除

子进程启动后立即执行 `scrub_environment()`，只保留白名单中的系统必需变量：

```
PATH、SYSTEMROOT、WINDIR、TEMP、TMP、USERPROFILE、HOMEDRIVE、HOMEPATH、
	PATHEXT、PROCESSOR_ARCHITECTURE、NUMBER_OF_PROCESSORS、PYTHONPATH、
	PYTHONIOENCODING、COMSPEC、LC_ALL、LANG、TZ、HOME、APPDATA、LOCALAPPDATA、
	COMPUTERNAME、USERNAME、SESSIONNAME（共 23 个）
```

服务器业务密钥（LLM API Key、JWT 密钥、数据库密码等）全部从 `os.environ` 中删除。插件读到的 `os.environ` 是"洗过"的空壳。

### 第三层：import 白名单 + sys.modules 清理

插件能 import 什么，由 `sys.meta_path` 钩子逐条裁决，只放行三类模块：

1. **白名单标准库**：`json`、`re`、`datetime`、`asyncio`、`math` 等纯工具模块
2. **SDK 桩模块**：`src.use_cases.tools_system`、`src.use_cases._plugin_helpers` 等，由桩代码替身代替真实实现（见第六层）
3. **插件自带模块**：插件目录下的 `.py` 文件

以下模块一律拒绝：

```
importlib / ctypes / marshal / pickle / shelve / subprocess / multiprocessing
socket / ssl / http.client / http.server / urllib.request / urllib.response
httpx / requests / aiohttp / urllib3 / websockets / websocket
sqlite3 / sqlalchemy / pymysql / psycopg / aiomysql
shutil / tempfile / zipfile / tarfile / gzip / bz2 / lzma / zlib
pty / pwd / grp / spwd / resource / pdb / distutils / setuptools / pip
smtplib / ftplib / telnetlib / imaplib / poplib
msvcrt / curses / tkinter / winreg / configparser / email / platform / gc / signal
以及服务器内部模块 src.* 的全部真实实现
```

::: warning 预导入缓存绕过
`asyncio` 等运行时在子进程启动阶段就会把 `subprocess`、`socket`、`ssl` 加载进 `sys.modules`。如果不清除，插件 `import subprocess` 会直接命中缓存、绕过白名单钩子。因此沙箱在装钩子前会先把这些攻击面模块从 `sys.modules` 置空，强制插件 import 必须重新经过白名单裁决。
:::

### 第四层：审计钩子（兜底防线）

即使插件通过动态构造、反射等手法绕过 import 检查，`sys.addaudithook` 也会拦截危险系统调用本身：

| 被拦截的事件 | 拦截的调用 |
|--------------|-----------|
| 命令执行 | `os.system`、`os.spawn*`、`os.exec*`、`os.posix_spawn` |
| 子进程 | `subprocess.*` 全部 |
| 网络连接 | `socket.__new__`（所有 socket 创建） |
| 低级加载 | `ctypes.dlopen`、`marshal.loads`、`marshal.load` |
| 文件写操作 | `open` 写模式、`os.remove/rename/mkdir/chmod/...` 越界路径 |
| 文件读操作 | 读取插件目录与状态目录以外的文件 |

**兜底的意义**：import 钩子管"能不能拿到模块"，审计钩子管"能不能调用动作"。即使某个模块漏网，危险动作也会被审计钩子拦下。

### 第五层：文件系统命名空间

插件能读写的路径被严格限制在两个根目录内：

| 根目录 | 说明 | 读写规则 |
|--------|------|----------|
| `data/plugins/installed/<plugin_id>/` | 插件自身目录 | 读始终放行，写需声明 `file_write` |
| `data/plugins/state/<plugin_id>/` | 专属状态目录 | 读写均需声明 `file_read` / `file_write` |

- 未声明 `file_read`/`file_write` 权限的插件：只能读自己的代码和自带数据，**不能写任何文件**，连状态目录都进不去
- 标准库源码读取放行（否则连 `import json` 都会因读源码失败而崩溃），但 `site-packages` 第三方库目录仍被排除
- 路径穿越（`../` 逃逸）在审计钩子层被拦截

### 第六层：SDK 权限裁决（核心）

插件里的 SDK 函数（`http_get_json`、`get_ltm_service`、发设备指令……）在子进程里是**桩**——它们不做事，只把请求编码成 JSON 发给主进程。主进程的 **Adjudicator 裁决器**按 manifest 声明的 `permissions` 决定"这个操作允不允许"。

#### SDK 操作 → 权限映射

| SDK 操作 | 需要的权限 | 说明 |
|----------|-----------|------|
| `device_send_instruct` / `device_send_command` / `device_send_command_ack` / `device_request_result` | `device` | 给设备下发指令 |
| `device_is_online` / `device_get_info` | `device` | 设备在线状态查询 |
| `http_request` / `http_get_json` | `network` | 外部 HTTP 请求（含 SSRF 防护） |
| `ltm_store` / `ltm_recall` / `ltm_list_all` / `ltm_update` / `ltm_forget` | `ltm` | 长期记忆读写 |
| `diary_get_recent` / `diary_upsert_entry` / `diary_search` | `db` | 日记数据 |
| `device_config_get` / `device_config_update_partial` | `db` | 设备配置 |
| `get_user_profile_summary` | `db` | 用户画像查询 |
| `env_read` | `env_read` | 读环境变量（仅白名单变量） |
| `llm_chat` / `llm_generate` | `llm` | LLM 对话/文本生成 |
| `tts_synthesize` | `tts` | 文本转语音合成 |
| `plugin_data_read` / `plugin_data_list` | `file_read` | 读取插件数据目录 |
| `plugin_data_write` / `plugin_data_delete` | `file_write` | 写入插件数据目录 |
| `kv_get` / `kv_set` / `kv_delete` / `kv_list` | `kv` | 键值存储读写 |
| `billing_add_asr` / `billing_add_llm` / `billing_add_tts` | `billing` | 上报本轮用量到计费系统 |
| `device_key` / `resolve_device_key` / `plugin_config` / `skill_catalog` / `plugin_log` | 无需权限 | 只读基础信息 |

#### 权限白名单语义

`manifest.json` 中的 `permissions` 声明决定插件能调用哪些 SDK：

| permissions | 插件能做什么 |
|-------------|-------------|
| `[]`（默认） | 只能读设备 key、插件配置、技能目录、写日志，其余全部被拒 |
| `["network"]` | 可发外部 HTTP 请求 |
| `["device"]` | 可给设备下发指令、查询设备在线状态与信息 |
| `["ltm"]` | 可读写长期记忆 |
| `["db"]` | 可读写数据库（日记、设备配置、用户画像） |
| `["env_read"]` | 可读白名单内的环境变量 |
| `["file_read"]` | 可读插件数据目录与状态目录 |
| `["file_write"]` | 可写插件数据目录与状态目录 |
| `["llm"]` | 可调用 LLM 对话（`llm_chat` / `llm_generate`） |
| `["tts"]` | 可调用 TTS 语音合成 |
| `["kv"]` | 可使用插件键值存储（`kv_get` / `kv_set` / `kv_delete` / `kv_list`） |
| `["billing"]` | 可上报本轮用量到计费系统（`add_asr` / `add_llm` / `add_tts`） |

**内置插件的权限声明**：`alarm=[]`、`device_config=[device,db]`、`device_control=[device]`、`diary=[db]`、`http_tool=[network]`、`media_player=[network,device]`、`memory=[ltm]`、`screen=[device]`、`system_basic=[device]`、`weather=[network,device]`。

#### 拒绝的语义

未声明权限的 SDK 调用会被主进程拒绝，插件侧抛出 `PermissionError`，工具返回可播报的失败文案。**插件开发时请务必声明所需权限，否则功能会"静默失败"**。

### 第七层：builtins 封锁

`input`、`breakpoint` 等交互入口被替换为直接抛错的桩，防止插件阻塞子进程或进入调试器。

---

## 通信协议与生命周期

插件与主进程通过 **JSON 行协议**（stdin/stdout）通信，单条消息不超过 1MB。

### 启动时序

```
主进程                      子进程
  │-- spawn ------------------> 解析参数、安装沙箱（擦环境→清 modules→装钩子）
  │                            ├─ 注入 SDK 桩
  │                            ├─ 加载 plugin.py（@tool 注册到本地）
  │                            └─ 上报 ready（含工具清单）
  │<------- ready --------------│
  │   校验工具 schema，注册到全局工具表
```

- 子进程在 ready 之前就退出（EOF 早于 ready）→ 主进程判定**启动失败**，快速失败
- ready 超时 → 主进程终止子进程

### 工具调用时序（含 SDK 请求）

```
主进程                      子进程
  │-- {call, tool, args} ----> 执行工具函数
  │                            │ 插件调用 SDK 桩
  │<-- {sdk_request, op} ------│
  │   Adjudicator 裁决权限
  │   调用真实实现（真实凭据/设备/DB 在主进程）
  │-- {sdk_reply, result} ----> 继续执行
  │<-- {result} --------------│ 工具返回
  │   PermissionDenied → 错误回复前缀 PermissionError
  │   超时 → 直接终止子进程
```

### 卸载时序

```
主进程                      子进程
  │-- {stop} -----------------> 收到停止信号
  │                            退出事件循环，清理退出
  │   process.terminate() 兜底  （优雅退出超时则强杀）
  │<-- 进程退出
  │  注销工具、清理状态
```

---

## 对插件开发者的影响

### 能做的

- 声明 `permissions` 后正常使用 SDK：网络请求、设备指令、**设备 IO（GPIO/PWM/ADC/舵机）**、**音乐播放**、**语音播报**、记忆读写、数据库访问、LLM 对话、TTS 合成、键值存储
- 用白名单标准库（`json`、`datetime`、`asyncio` 等）写业务逻辑
- 读取和（声明后）写入自己的插件目录与状态目录
- 读白名单内的环境变量（`<插件id>_` 或 `PLUGIN_` 前缀，或通过 `PLUGIN_ENV_ALLOWLIST` 显式放行）

### 不能做的

| 动作 | 结果 |
|------|------|
| `import subprocess` / `import socket` / `import os` 读密钥 | 启动即被拒绝（模块不存在/被拦截） |
| 调 `os.system` / `subprocess.run` | 审计钩子拦截，抛 `SandboxAuditError` |
| 读 `/etc/passwd`、`.env`、服务器源码 | 文件系统命名空间拒绝 |
| 连内网 IP / 云元数据地址 | SSRF 防护拒绝 |
| 读环境变量里的 API Key | 环境变量已被擦除 / `env_read` 白名单拦截 |
| 写任意文件 | 未声明 `file_write` 一律拒绝 |
| 死循环卡住主服务 | 独立进程 + 120s 超时强杀 |

### 常见报错速查

| 报错 | 含义 | 解决方案 |
|------|------|----------|
| `插件禁止导入模块: subprocess` | 触及 import 黑名单 | 移除该 import，改用 SDK |
| `插件未声明 network 权限，SDK 操作 http_get_json 已被阻止` | 权限不足 | 在 manifest 声明 `permissions: ["network"]` |
| `插件未声明 file_write 权限，禁止写入文件` | 尝试写文件 | 声明 `file_write`，且只写插件目录/状态目录 |
| `PermissionError: 插件「x」尝试读取非白名单环境变量 FOO` | 读环境变量越权 | 用 `<插件id>_FOO` 命名，或加 `PLUGIN_ENV_ALLOWLIST=FOO` |
| `PermissionError: 插件「x」未声明 billing 权限，上报 ASR 计费用量被拒绝` | 计费上报越权 | 在 manifest 声明 `permissions: ["billing"]` |

### 沙箱 SDK 能力对照（RPC 支持的操作）

沙箱内插件调用 SDK 时，经 Adjudicator 裁决后由主进程代为执行。当前支持的操作：

| 操作 | SDK 函数 | 所需权限 | 返回约定 |
|------|---------|---------|---------|
| 设备指令 | `send_device_command` / `send_instruct` | `device` | `None`/错误串 |
| 指令回执 | `send_device_command_ack` / `request_device_result` / `lua_execute` / `get_device_state` / `device_command_ack` | `device` | `(result, status, detail)` |
| 设备 IO | `gpio_mode` / `gpio_write` / `pwm_write` / `servo_write` | `device` | `"ok"`/错误串 |
| 设备 IO 读 | `gpio_read` / `adc_read` | `device` | int，失败 `-1` |
| 音乐播放 | `play_music_url` | `device` | `"ok"`/错误串 |
| 语音播报 | `speak_to_device` | `device` + `tts` | `True`/`False` |
| HTTP 请求 | `http_request` / `http_get_json` | `network` | `(resp, err)` |
| LLM / TTS | `llm_chat` / `llm_generate` / `tts_synthesize` | `llm` / `tts` | 见 API 参考 |
| 记忆 / KV | LTM 服务 / `kv_*` | `db` / `kv` | 见 API 参考 |
| 文件持久化 | `plugin_data_*` | `file_read` / `file_write` | 见 API 参考 |
| 计费上报 | `add_asr` / `add_llm` / `add_tts` | `billing` | 无返回值 |

::: tip 设备语音播报
沙箱插件声明 `device` + `tts` 权限后可直接调用 `speak_to_device(device_key="", text=...)` 让设备播报一段文本：主进程会完成 TTS 合成并按帧推流到设备实时播放（不经过 LLM 流程），`device_key` 留空时自动回退到本次调用绑定的设备。设备离线 / 语音服务不可用时返回 `False`。
:::

::: warning 尚未进入沙箱 RPC 的 SDK 能力
`get_device_registry`、`get_wechat_bot`、`get_remote_config_provider` 等基础设施封装仅内置插件可用（它们依赖进程内单例）。
:::

---

## 签名与完整性校验

插件包支持两层完整性校验，防止插件被篡改或夹带私货：

1. **文件哈希校验**（`file_hashes`）：安装时校验包内每个文件的 SHA-256 哈希，多余文件、缺失文件、被改过的文件都会被拒绝
2. **数字签名**（`signature`）：管理员配置 `PLUGIN_SIGN_PUBLIC_KEY`（PEM 公钥）后，安装强制校验签名链——只有持有对应私钥的开发者签发的包才能安装

| 配置项 | 说明 |
|--------|------|
| `PLUGIN_SIGN_PUBLIC_KEY` | 配置后强制验签，未签名或签名无效的包被拒绝 |
| `PLUGIN_ENV_ALLOWLIST` | 逗号分隔的环境变量白名单，显式放行非前缀变量 |

## 安装包安全限制

| 限制项 | 上限 |
|--------|------|
| zip 文件大小 | 5MB |
| 解压后总大小 | 20MB |
| 单个文件大小 | 8MB |
| 包内文件数量 | 200 |

超过任一项即拒绝安装。解压过程在临时目录进行，校验通过后才原子移动到 `data/plugins/installed/`，中途失败不会留下半成品。

---

## 已知局限与演进规划

当前沙箱是 **Python 进程级防护**，不是 OS 级隔离（无 seccomp / 容器 / 虚拟机），理论上有被高超技巧逃逸的可能。对第三方插件场景（信任度低、交互面有限），多层纵深已是够用的防御。后续演进方向：

- 生命周期钩子 + 版本 pin + 完整签名链（插件声明依赖的版本，加载时校验）
- 插件运行时状态隔离与审计日志（记录每个 SDK 调用的完整上下文）
- host 层与沙箱层接口解耦（沙箱协议独立成稳定 API，便于切换后端）

---

## 相关文件

| 文件 | 说明 |
|------|------|
| `src/infrastructure/plugin_host/sandbox.py` | 沙箱内核：环境擦除、import 白名单、audit 钩子、sys.modules 清理 |
| `src/infrastructure/plugin_host/runner.py` | 子进程入口：加载插件、服务 RPC、上报 ready |
| `src/infrastructure/plugin_host/supervisor.py` | 主进程侧：启动子进程、收发消息、工具调用、超时与卸载 |
| `src/infrastructure/plugin_host/adjudicator.py` | SDK 权限裁决器（SDK 操作 → 权限映射 + SSRF 防护） |
| `src/infrastructure/plugin_host/sdk_shim.py` | SDK 桩：插件侧的替身实现，只负责转发请求 |
| `src/infrastructure/plugin_host/protocol.py` | JSON 行通信协议定义 |
| `src/infrastructure/plugin_security.py` | 权限上下文、环境变量白名单、AST 静态审计 |
| `src/infrastructure/plugin_manifest.py` | manifest 校验、签名与文件哈希校验 |
| `src/infrastructure/plugin_manager.py` | 安装包限制、安全解压、市场下载限流 |
| `tests/test_plugin_sandbox.py` | 沙箱端到端测试（进程级往返、权限拦截、import 黑名单） |