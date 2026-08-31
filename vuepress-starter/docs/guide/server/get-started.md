# 快速开始

跟随本教程在 5 分钟内启动 小明同学 Server。

## 环境要求

- **Python** ≥ 3.10
- **UV** 包管理器（推荐）或 pip

## 1. 安装 UV 包管理器

### Windows

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
Invoke-RestMethod -Uri https://astral.sh/uv/install.ps1 -OutFile install.ps1
./install.ps1
```

### macOS / Linux

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## 2. 克隆项目

```bash
git clone https://gitee.com/zhuxiaohuaqn/esp-ai-server.git
cd esp-ai-server
```

## 3. 同步依赖

```bash
uv sync
```

## 4. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，填入你的 API 密钥（参见[配置教程](/guide/server/config)）。

## 5. 启动服务

```bash
uv run python src/main.py
```

服务将在 `http://0.0.0.0:8088` 启动。

## 6. 注册与登录（App）

打开手机 App，注册账号并登录。App 会自动连接服务端（服务器 IP + 端口 8088）。

## 7. 设备配网与绑定

1. 设备开机 → 在 App 的「配网」页，通过蓝牙把 WiFi 和服务器地址发给设备
2. 设备连接 WiFi 后自动连接服务器，屏幕显示 6 位绑定码
3. 在 App「我的 → 设备」中输入绑定码完成绑定

## 8. 配置 AI 服务

在 App 中为设备配置 **ASR / LLM / TTS**（API Key、音色、模型等），配置存入数据库（多用户模式），每台设备可独立配置。

## 9. 验证运行

对设备说出唤醒词（如"小明同学"），设备回应"我在呢"并进入聆听状态，即表示搭建成功。

## Docker 部署

项目自带多阶段 `Dockerfile` 和 `docker-compose.yml`，开箱即用。

### 1. 准备配置

```bash
cp .env.example .env
# 编辑 .env，填入 ASR / LLM / TTS 密钥、JWT_SECRET 等
```

### 2. 构建并启动

```bash
docker compose up -d --build
```

首次会自动构建镜像（多阶段构建，内含 Python 虚拟环境）。容器入口为 `uvicorn src.main:app --host 0.0.0.0 --port 8088`，暴露 `8088` 端口，并内置健康检查（`/health/live`）。

### 3. 数据持久化

`docker-compose.yml` 已挂载命名卷，容器重建 / 升级不丢数据：

| 卷 | 容器路径 | 用途 |
|---|---|---|
| `esp-ai-data` | `/app/data` | **主数据**：SQLite 数据库（`data/espai.db`）、插件、备份、微信数据 |
| `esp-ai-device-data` | `/app/src/data` | 设备级数据：技能、记忆 |
| `esp-ai-firmware` | `/app/src/firmware` | OTA 固件文件 |
| `esp-ai-emos` | `/app/src/emos` | 表情包静态资源 |
| `esp-ai-logs` | `/app/logs` | 运行日志 |

如需直接访问数据目录，可把命名卷改成 bind mount，例如 `./data:/app/data`。

### 4. 查看状态与日志

```bash
docker compose ps
docker compose logs -f esp-ai-server
```

### 5. 停止 / 卸载

```bash
docker compose down        # 停止并删除容器（数据卷保留）
docker compose down -v     # 连数据卷一起删除（数据将丢失！）
```

> 资源限制默认 2G 内存 / 2 CPU，可在 `docker-compose.yml` 的 `deploy.resources` 中调整。
