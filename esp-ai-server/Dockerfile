# ============================================================
# ESP-AI Server - Multi-stage Dockerfile
# ============================================================
# Stage 1: builder  - 安装构建工具，用 uv sync 安装依赖到 .venv
# Stage 2: runtime  - 精简运行时镜像，只保留 .venv 和 src
# ============================================================

# -------------------- Stage 1: builder --------------------
FROM python:3.10-slim AS builder

LABEL org.opencontainers.image.title="ESP-AI Server"
LABEL org.opencontainers.image.description="ESP-AI voice assistant backend service"

# uv 运行参数：copy 模式（跨阶段拷贝兼容）、预编译字节码、不下载 Python
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# 安装构建依赖：build-essential（编译 C 扩展）+ libgomp1（OpenMP，torch 依赖）
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 从官方镜像拷贝 uv 二进制（无需 pip 安装）
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /bin/

WORKDIR /app

# 先拷贝依赖描述文件，利用 Docker 层缓存
COPY pyproject.toml uv.lock README.md ./

# 仅安装运行时依赖到 .venv（不装 dev extras，不安装项目自身）
# --frozen: 严格使用 uv.lock，保证可复现
# --no-install-project: 只装依赖，不把当前项目作为包安装
RUN uv sync --frozen --no-install-project

# 拷贝源码
COPY src/ ./src/


# -------------------- Stage 2: runtime --------------------
FROM python:3.10-slim AS runtime

# 运行时只需 libgomp1（torch OpenMP 依赖）
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system espai \
    && useradd --system --gid espai --home-dir /app --shell /usr/sbin/nologin espai

WORKDIR /app

# 从 builder 拷贝虚拟环境和源码（注意：.venv 中字节码已预编译，路径一致）
COPY --from=builder --chown=espai:espai /app/.venv /app/.venv
COPY --from=builder --chown=espai:espai /app/src /app/src

# 运行时环境变量
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy

# 创建运行时需要的目录并赋权（数据、设备数据、固件、表情包、日志）
# /app/data 存 SQLite 数据库 (data/espai.db)、插件、备份、微信数据
RUN mkdir -p /app/src/data /app/src/firmware /app/src/emos \
        /app/data /app/logs \
    && chown -R espai:espai /app

USER espai

EXPOSE 8088

# 健康检查：访问 /health/live 端点
HEALTHCHECK --interval=15s --timeout=3s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8088/health/live').read()" || exit 1

# 入口：uvicorn 直接加载 src.main:app
CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8088", "--ws-max-size", "20971520"]
