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
uv run python main.py
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

项目提供了 `Dockerfile` 和 `docker-compose.yml`：

```bash
# 使用 docker-compose
docker compose up -d

# 或手动构建
docker build -t esp-ai-server .
docker run -d \
  --name esp-ai-server \
  -p 8088:8088 \
  --env-file .env \
  esp-ai-server
```
