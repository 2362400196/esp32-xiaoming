"""
ESP AI Server - Main Entry Point

Clean Architecture实现的智能语音助手服务器

功能：
- ASR语音识别（腾讯云、火山引擎、阿里云、讯飞）
- LLM大模型对话（OpenAI兼容接口）
- TTS语音合成（火山引擎流式TTS）
- WebSocket实时通信
- Pipeline流水线处理
- 会话管理
- 连接池管理
- 记忆系统
- 工具系统（MCP）
- 情感检测
- 设备认证
- 监控指标

架构：
    src/
    ├── domain/           # 领域层（实体、值对象、仓储接口、领域服务）
    ├── use_cases/        # 用例层（DTOs、端口）
    ├── interfaces/       # 接口适配器层（控制器、展示器、网关）
    └── infrastructure/   # 基础设施层（配置、Web、认证、日志、监控、DI）

依赖方向：
    use_cases → domain
    interfaces → domain, use_cases
    infrastructure → domain, use_cases, interfaces
"""

import asyncio
import os
import socket
import sys
import warnings
from pathlib import Path

# 抑制警告
warnings.filterwarnings("ignore")
warnings.simplefilter("ignore", DeprecationWarning)

# 确保项目根目录在sys.path中
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ═══════════════════════════════════════════════
# 常量和配置
# ═══════════════════════════════════════════════

SERVER_VERSION = "v3.0.0-clean-arch"

ASCII_ART = r"""
 _____   ____    ____               _      ___
| ____| / ___|  |  _ \             / \    |_ _|
|  _|   \___ \  | |_) |  _____    / _ \    | |
| |___   ___) | |  __/  |_____|  / ___ \   | |
|_____| |____/  |_|             /_/   \_\ |___|
"""


def print_banner() -> None:
    """打印启动横幅"""
    # 清屏
    os.system("cls" if os.name == "nt" else "clear")

    # 彩色输出
    GREEN = "\033[32m"
    RESET = "\033[0m"

    print(GREEN + ASCII_ART + RESET)
    print(GREEN + f"  Server Version: {SERVER_VERSION}" + RESET)
    print(GREEN + f"  Architecture: Clean Architecture (Domain/Use Cases/Interfaces/Infrastructure)" + RESET)


def get_server_ips() -> list[str]:
    """获取服务器IP地址"""
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        ips.append(local_ip)
        ips.append("127.0.0.1")
    except Exception as e:
        print(f"[WARN] Failed to get IP addresses: {e}")
    return ips


async def main() -> None:
    """
    主函数 - 应用入口点

    初始化和启动整个应用
    """
    # 打印横幅
    print_banner()

    # 导入配置
    from src.infrastructure.config import get_settings, SID_CONNECTED, SCREEN_WIDTH, SCREEN_HEIGHT
    settings = get_settings()

    # 验证配置
    missing_configs = settings.validate_config()
    if missing_configs:
        print(f"[Config] WARN: Missing configurations: {', '.join(missing_configs)}")
        print("[Config] Some services may not work properly")
    else:
        print("[Config] OK: All critical configurations loaded")

    # 获取监听地址
    host = settings.server.host
    port = settings.server.port

    # 显示服务信息
    print(f"\n[Server] Starting on {host}:{port}")

    # 显示IP地址
    ips = get_server_ips()
    for ip in ips:
        print(f"  -> {ip}:{port}")

    print("\n" + "=" * 50)
    print("[Info] Client will auto-connect after power cycle!")
    print("=" * 50 + "\n")

    # 初始化日志
    from src.infrastructure.logging import setup_logging, get_logger
    # 确保日志目录存在（日志轮转文件写入需要）
    if settings.log.file_path:
        try:
            Path(settings.log.file_path).parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
    logger = setup_logging(
        level=settings.log.level,
        log_format=settings.log.format,
        file_path=settings.log.file_path,
        debug=settings.log.debug_log,
    )
    logger.info(f"Server version: {SERVER_VERSION}")
    logger.info(f"Log level: {settings.log.level.value}")

    # 初始化数据库 + 数据迁移（JSON → SQLite，一次性历史迁移）
    try:
        from src.infrastructure.db import init_db
        await init_db()
        logger.info("[DB] 数据库初始化完成")

        # 一次性历史数据迁移（首次启动时从 JSON 迁移到 DB）
        try:
            from src.infrastructure.db.migrations.data_migration import run_migration
            reports = await run_migration(project_root=PROJECT_ROOT, dry_run=False, force=False)
            total = sum(r.inserted for r in reports)
            if total > 0:
                logger.info(f"[DB] 历史数据迁移完成: 共 {total} 条记录")
                for r in reports:
                    if r.inserted > 0 or r.skipped:
                        logger.info(f"  {r.table}: 插入 {r.inserted} 条, 跳过={r.skipped}")
            else:
                # logger.info("[DB] 历史数据迁移跳过（DB 已有数据或无 JSON 文件）")
                pass
        except Exception as mig_err:
            logger.warning(f"[DB] 历史数据迁移失败（不影响启动）: {mig_err}")
    except Exception as db_err:
        logger.error(f"[DB] 数据库初始化失败（数据库是唯一存储，服务可能无法正常工作）: {db_err}")

    # 创建应用
    from src.infrastructure.web import create_app
    app = create_app()

    # 配置Prometheus监控（如果可用）
    # 统一使用 prometheus 默认 registry：业务指标（track_*）与 HTTP 指标
    # 均注册到 prometheus_client.REGISTRY，由 system 路由的 /metrics 端点统一暴露。
    # 注意：这里只调用 instrument() 采集 HTTP 指标，不再调用 expose() 注册 /metrics，
    # 避免与 system.py 中手动注册的 /metrics 路由重复。
    try:
        from src.infrastructure.monitoring import MetricsCollector
        # 确保业务指标注册到默认 REGISTRY
        MetricsCollector()
        try:
            from prometheus_fastapi_instrumentator import Instrumentator
            Instrumentator(
                should_group_status_codes=True,
                should_ignore_untemplated=True,
                should_instrument_requests_inprogress=True,
                excluded_handlers=["/metrics"],
            ).instrument(app)
            logger.info("[Metrics] Prometheus HTTP instrumentation enabled (metrics exposed at /metrics)")
        except ImportError:
            logger.info("[Metrics] prometheus_fastapi_instrumentator not installed; /metrics exposes business metrics only")
    except Exception as e:
        logger.warning(f"[Metrics] Prometheus setup failed: {e}")

    # 启动服务器
    import uvicorn

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        ws_max_size=settings.server.ws_max_size,
        # 禁用 uvicorn 的 WebSocket ping，避免与设备的应用层 keepalive 冲突
        # 设备的心跳由 idle_keepalive() 发送的 keepalive JSON 消息维持
        ws_ping_interval=None,
        ws_ping_timeout=None,
        log_level=settings.log.level.value.lower(),
        workers=settings.server.workers,
        reload=settings.server.reload,
    )

    server = uvicorn.Server(config)

    logger.info(f"[Server] Starting UVicorn server on {host}:{port}...")

    try:
        await server.serve()
    except KeyboardInterrupt:
        logger.info("[Server] Received shutdown signal")
    finally:
        logger.info("[Server] Shutting down...")
        # 清理资源
        await cleanup()


async def cleanup() -> None:
    """清理资源"""
    from src.infrastructure.logging import get_logger
    logger = get_logger()

    logger.info("[Cleanup] Complete")


def run_dev() -> None:
    """
    开发模式运行入口

    用于开发调试，支持热重载
    """
    import uvicorn

    from src.infrastructure.config import get_settings
    settings = get_settings()

    print_banner()
    print("\n[Dev Mode] Running in development mode with auto-reload...\n")

    uvicorn.run(
        "src.main:app",
        host=settings.server.host,
        port=settings.server.port,
        reload=True,
        ws_max_size=settings.server.ws_max_size,
        log_level="debug",
    )


# FastAPI应用实例（用于uvicorn直接导入）
app = None


def create_app_instance():
    """创建应用实例（用于直接导入）"""
    global app
    if app is None:
        from src.infrastructure.web import create_app
        app = create_app()
    return app


# 模块级初始化 - 延迟创建，避免启动时的导入错误
def _get_app():
    global app
    if app is None:
        from src.infrastructure.web import create_app
        app = create_app()
    return app


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--dev":
        run_dev()
    else:
        try:
            if sys.platform == "win32":
                # 必须用 Proactor：Selector 事件循环在 Windows 上不支持子进程，
                # 插件沙箱靠 create_subprocess_exec 运行，会抛 NotImplementedError。
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            asyncio.run(main())
        except KeyboardInterrupt:
            print("\n[Server] Shutdown by user")
