"""
Config - 应用配置管理

使用Pydantic Settings进行配置管理，支持环境变量和.env文件
与旧架构(app/config.py)的环境变量名完全兼容
"""
from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class ServerConfig(BaseModel):
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8088)
    workers: int = Field(default=1)
    reload: bool = Field(default=False)
    ws_max_size: int = Field(default=20 * 1024 * 1024)
    ws_ping_interval: int = Field(default=20, description="WebSocket ping 间隔（秒）")
    ws_ping_timeout: int = Field(default=20, description="WebSocket ping 超时（秒）")
    cors_origins: List[str] = Field(default_factory=lambda: [], description="允许的 CORS 来源列表；空列表表示不允许任何跨域（最安全），生产环境需显式配置允许的域名")


class AuthConfig(BaseModel):
    # 安全优先：默认开启认证，即使忘记配置 .env 也处于受保护状态。
    # 若需关闭认证（如本地开发），请在 .env 中显式设置 AUTH_ENABLED=false。
    enabled: bool = Field(default=True)
    api_key: str = Field(default="")
    admin_api_key: str = Field(default="")
    jwt_secret: str = Field(default="", description="JWT 签名密钥，用于用户 Token 签发")


class LogConfig(BaseModel):
    level: LogLevel = Field(default=LogLevel.INFO)
    format: str = Field(default="console")
    file_path: Optional[str] = Field(default="logs/esp_ai.log")
    max_size: int = Field(default=10 * 1024 * 1024)
    backup_count: int = Field(default=5)
    debug_log: bool = Field(default=False)


class ASRConfig(BaseModel):
    provider: str = Field(default="tencent")

    tencent_app_id: str = Field(default="")
    tencent_secret_id: str = Field(default="")
    tencent_secret_key: str = Field(default="")
    tencent_engine: str = Field(default="16k_zh")

    volcengine_api_key: str = Field(default="")
    volcengine_resource_id: str = Field(default="volc.bigasr.sauc.duration")
    volcengine_model: str = Field(default="bigmodel")

    aliyun_access_key_id: str = Field(default="")
    aliyun_access_key_secret: str = Field(default="")
    aliyun_app_key: str = Field(default="")

    xunfei_app_id: str = Field(default="")
    xunfei_api_key: str = Field(default="")
    xunfei_api_secret: str = Field(default="")

    no_speech_timeout: int = Field(default=5)
    silence_timeout: int = Field(default=3)
    max_concurrency: int = Field(default=100)

    enable_pool: bool = Field(default=True)
    pool_max_size: int = Field(default=100)
    pool_min_size: int = Field(default=2)
    pool_heartbeat_interval: int = Field(default=30)
    pool_idle_timeout: int = Field(default=300)
    pool_connection_timeout: int = Field(default=15)


class LLMConfig(BaseModel):
    provider: str = Field(default="openai")
    model: str = Field(default="")
    api_key: str = Field(default="")
    base_url: str = Field(default="")
    system_prompt: str = Field(default="")
    temperature: float = Field(default=0.7)
    max_tokens: int = Field(default=2000)
    stream: bool = Field(default=True)

    memory_enabled: bool = Field(default=True)
    memory_max_messages: int = Field(default=20)
    memory_max_tokens: int = Field(default=2000)

    # 长期记忆配置
    memory_long_term_enabled: bool = Field(default=True)
    memory_long_term_auto_extract: bool = Field(default=True)


class TTSConfig(BaseModel):
    provider: str = Field(default="volcengine")

    api_key: str = Field(default="")
    resource_id: str = Field(default="")
    voice_type: str = Field(default="")
    sample_rate: int = Field(default=24000)
    speed_ratio: float = Field(default=1.0)
    volume_ratio: float = Field(default=1.0)
    pitch_ratio: float = Field(default=1.0)
    explicit_dialect: str = Field(default="", description="TTS 方言，可选：beijing/dongbei/henan/shaanxi/shanghai/sichuan/tianjin/yue")

    max_concurrency: int = Field(default=10)

    enable_pool: bool = Field(default=True)
    pool_max_size: int = Field(default=100)
    pool_min_size: int = Field(default=2)
    pool_heartbeat_interval: int = Field(default=30)
    pool_idle_timeout: int = Field(default=300)
    pool_connection_timeout: int = Field(default=15)


class AudioConfig(BaseModel):
    sample_rate: int = Field(default=16000)
    channels: int = Field(default=1)
    sample_width: int = Field(default=2)
    format: str = Field(default="pcm")
    max_buffer_seconds: float = Field(default=2.0)


class OTAConfig(BaseModel):
    enabled: bool = Field(default=True)
    bin_id: str = Field(default="")
    is_official: str = Field(default="0")
    bin_url: str = Field(default="")
    version: str = Field(default="")
    query_url: str = Field(default="")


class WakeupConfig(BaseModel):
    text: str = Field(default="我在呢")
    enable_audio: bool = Field(default=True)
    audio_cache_enabled: bool = Field(default=True)
    audio_play_enabled: bool = Field(default=True)
    audio_source: str = Field(default="tts")
    play_on_next_round: bool = Field(default=False)


class EmotionConfig(BaseModel):
    enabled: bool = Field(default=False)
    gif_dir: str = Field(default="emos")
    static_dir: str = Field(default="static_emos")


class MCPConfig(BaseModel):
    servers_json: str = Field(default="")

    def get_servers(self) -> Dict[str, Any]:
        if self.servers_json:
            try:
                return json.loads(self.servers_json)
            except json.JSONDecodeError:
                return {}
        return {}


class MusicConfig(BaseModel):
    api_url: str = Field(default="")
    lyrics_offset: int = Field(default=0)


class RateLimitConfig(BaseModel):
    max_rpm: int = Field(default=0)


class RemoteConfigSettings(BaseModel):
    enabled: bool = Field(default=False)
    url: str = Field(default="")
    api_key: str = Field(default="")
    cache_ttl: int = Field(default=300)
    refresh_interval: int = Field(default=60)
    timeout: float = Field(default=10.0)


class ShutdownConfig(BaseModel):
    grace_period: int = Field(default=10)


class WeChatBotConfig(BaseModel):
    """微信 iLink Bot 配置"""
    enabled: bool = Field(default=False)
    token: str = Field(default="", description="微信 Bot Token")
    base_url: str = Field(default="https://ilinkai.weixin.qq.com", description="微信 iLink API 基址")
    cdn_base_url: str = Field(default="https://novac2c.cdn.weixin.qq.com/c2c", description="微信 CDN 基址")
    app_id: str = Field(default="bot")
    client_version: str = Field(default="131329")
    account_id: str = Field(default="default", description="微信账号标识")
    poll_interval_ms: int = Field(default=35000, description="消息轮询间隔（毫秒）")


class SessionConfig(BaseModel):
    max_sessions: int = Field(default=1000)
    timeout: float = Field(default=3600.0)
    idle_timeout: float = Field(default=300.0)
    enable_auto_conversation: bool = Field(default=True)
    # TTS 播放完成超时配置
    tts_playback_base_timeout: float = Field(default=30.0, description="基础超时时间（秒）")
    tts_playback_max_timeout: float = Field(default=300.0, description="最大超时时间（秒）")
    tts_playback_duration_multiplier: float = Field(default=1.5, description="音频时长乘数（考虑网络延迟）")


class PerformanceConfig(BaseModel):
    # 全局并发控制
    global_max_concurrent_sessions: int = Field(default=500)
    enable_global_concurrency_limit: bool = Field(default=True)

    # 队列大小限制
    audio_queue_max_size: int = Field(default=200)
    send_queue_max_size: int = Field(default=500)

    # 内存保护
    max_messages_per_session: int = Field(default=100)

    # 限流
    rate_limit_global_rpm: int = Field(default=3000)

    # CPU 密集型任务池
    process_pool_max_workers: int = Field(default=8)


class DatabaseConfig(BaseModel):
    """数据库配置（SQLite + SQLAlchemy）

    数据库是唯一持久化存储，不再回退到 JSON 文件。
    """
    url: str = Field(default="sqlite+aiosqlite:///data/espai.db", description="SQLAlchemy 异步连接串")
    sync_url: str = Field(default="sqlite:///data/espai.db", description="SQLAlchemy 同步连接串")
    echo: bool = Field(default=False, description="是否输出 SQL 日志（调试用）")
    pool_size: int = Field(default=10, description="连接池大小")
    max_overflow: int = Field(default=20, description="连接池溢出上限")
    connect_args: dict = Field(default_factory=lambda: {"timeout": 30}, description="连接参数")


_DEFAULT_SYSTEM_PROMPT = (
    "你的回复会通过语音合成（TTS）播放，禁止输出任何在语音中无法朗读的符号。\n\n"
    "【回复长度】\n"
    "回复必须控制在 1 句、25 字以内，一句话说完，简短口语化，像真人聊天一样自然。\n"
    "除非用户明确要求详细解释，否则禁止长篇大论、列举多条或展开说明。\n\n"
    "【输出格式】\n"
    "只输出纯中文+标点+数字+末尾情绪标签[e:情绪]，不要有任何 Markdown、特殊符号、表情符号。\n"
    "正确例子：你太棒了[e:快乐]\n"
    "正确例子：别难过啦[e:伤心]\n"
    "错误例子：**你太棒了**[e:快乐]（有**号，禁止）\n"
    "错误例子：你太棒了！😊[e:快乐]（有 emoji，禁止）\n"
    "错误例子：- 列表项[e:无情绪]（有-号，禁止）\n\n"
    "【情绪标签】\n"
    "在回复末尾附上 [e:情绪]，可选：快乐、伤心、愤怒、意外、否定、无情绪"
)


class Settings(BaseSettings):
    """
    应用全局配置

    从环境变量和.env文件加载配置，与旧架构环境变量名完全兼容。
    环境变量命名规则：大写+下划线，嵌套用下划线连接
    例如：ASR_TENCENT_APP_ID -> asr.tencent_app_id
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    server: ServerConfig = Field(default_factory=ServerConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    log: LogConfig = Field(default_factory=LogConfig)
    asr: ASRConfig = Field(default_factory=ASRConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    wakeup: WakeupConfig = Field(default_factory=WakeupConfig)
    emotion: EmotionConfig = Field(default_factory=EmotionConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    music: MusicConfig = Field(default_factory=MusicConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    remote_config: RemoteConfigSettings = Field(default_factory=RemoteConfigSettings)
    shutdown: ShutdownConfig = Field(default_factory=ShutdownConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    performance: PerformanceConfig = Field(default_factory=PerformanceConfig)
    ota: OTAConfig = Field(default_factory=OTAConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    wechat_bot: WeChatBotConfig = Field(default_factory=WeChatBotConfig)

    # 数据库配置（顶层环境变量，映射到 database 子模型）
    database_url: str = Field(default="", description="数据库异步连接串")
    database_sync_url: str = Field(default="", description="数据库同步连接串")
    database_echo: bool = Field(default=False, description="是否输出 SQL 日志")

    asr_provider: str = Field(default="")
    asr_tencent_app_id: str = Field(default="")
    asr_tencent_secret_id: str = Field(default="")
    asr_tencent_secret_key: str = Field(default="")
    asr_tencent_engine: str = Field(default="")
    asr_volcengine_api_key: str = Field(default="")
    asr_volcengine_resource_id: str = Field(default="")
    asr_volcengine_model: str = Field(default="")
    asr_no_speech_timeout: int = Field(default=0)
    asr_silence_timeout: int = Field(default=0)
    asr_max_concurrency: int = Field(default=0)
    asr_pool_enabled: bool = Field(default=True)
    asr_pool_max_size: int = Field(default=0)
    asr_pool_min_size: int = Field(default=0)
    asr_pool_heartbeat_interval: int = Field(default=0)
    asr_pool_idle_timeout: int = Field(default=0)
    asr_pool_connection_timeout: int = Field(default=0)

    llm_api_key: str = Field(default="")
    llm_base_url: str = Field(default="")
    llm_model: str = Field(default="")
    llm_system_prompt: str = Field(default="")
    llm_temperature: float = Field(default=0.0)
    llm_max_tokens: int = Field(default=0)
    llm_memory_enabled: bool = Field(default=True)
    llm_memory_max_messages: int = Field(default=0)
    llm_memory_max_tokens: int = Field(default=0)
    llm_memory_long_term_enabled: bool = Field(default=True)
    llm_memory_long_term_auto_extract: bool = Field(default=True)

    tts_volcengine_api_key: str = Field(default="")
    tts_volcengine_resource_id: str = Field(default="")
    tts_volcengine_voice_type: str = Field(default="")
    tts_volcengine_speed: str = Field(default="")
    tts_volcengine_volume: str = Field(default="")
    tts_volcengine_pitch: str = Field(default="")
    tts_volcengine_dialect: str = Field(default="")
    tts_volcengine_sample_rate: int = Field(default=0)
    tts_pool_enabled: bool = Field(default=True)
    tts_pool_max_size: int = Field(default=0)
    tts_pool_min_size: int = Field(default=0)
    tts_pool_heartbeat_interval: int = Field(default=0)
    tts_pool_idle_timeout: int = Field(default=0)
    tts_pool_connection_timeout: int = Field(default=0)

    # 火山引擎 OpenAPI 凭据(用于查询账号下已有的复刻音色列表,与 TTS 合成的 X-Api-Key 是两套)
    volc_access_key_id: str = Field(default="")
    volc_secret_access_key: str = Field(default="")
    volc_project_name: str = Field(default="default")

    auth_enabled: bool = Field(default=True)
    auth_api_key: str = Field(default="")
    admin_api_key: str = Field(default="")
    jwt_secret: str = Field(default="")
    debug_log: bool = Field(default=False)
    log_format: str = Field(default="")
    debug_log_level: str = Field(default="")
    log_file_path: str = Field(default="", description="日志文件路径")
    log_max_size: int = Field(default=0, description="日志文件最大字节数")
    log_backup_count: int = Field(default=0, description="日志文件保留份数")
    rate_limit_max_rpm: int = Field(default=0)
    shutdown_grace_period: int = Field(default=0)

    wakeup_text: str = Field(default="")
    enable_wakeup_audio: bool = Field(default=True)
    wake_audio_cache_enabled: bool = Field(default=True)
    wake_audio_play_enabled: bool = Field(default=True)
    wake_audio_source: str = Field(default="")
    wake_audio_on_next_round: bool = Field(default=False)

    server_emotion_enabled: bool = Field(default=True)
    server_emotion_gif_dir: str = Field(default="")
    server_emotion_static_dir: str = Field(default="")

    mcp_servers_json: str = Field(default="")

    music_api_url: str = Field(default="")

    # ============================================================
    # AI成长系统配置
    # ============================================================
    # 成长任务冷却时间（秒）
    # 用户对话结束后，等待指定时间无新对话，才触发成长任务
    # 避免用户连续说话时频繁触发，同时收集更完整的对话内容
    # 默认300秒（5分钟），设置为0则立即触发
    growth_cooldown_seconds: int = Field(default=300)

    # Performance configuration (environment variables)
    perf_global_max_concurrent_sessions: int = Field(default=0)
    perf_enable_global_concurrency_limit: bool = Field(default=True)
    perf_audio_queue_max_size: int = Field(default=0)
    perf_send_queue_max_size: int = Field(default=0)
    perf_max_messages_per_session: int = Field(default=0)
    perf_rate_limit_global_rpm: int = Field(default=0)
    perf_process_pool_max_workers: int = Field(default=0)
    lyrics_offset: int = Field(default=0)

    host: str = Field(default="")
    port: int = Field(default=0)
    deploy_mode: str = Field(default="single")
    cors_origins: str = Field(default="", description="CORS 来源（逗号分隔），例如 https://a.com,https://b.com")

    remote_config_enabled: bool = Field(default=False)
    remote_config_url: str = Field(default="")
    remote_config_api_key: str = Field(default="")
    remote_config_cache_ttl: int = Field(default=300)
    remote_config_refresh_interval: int = Field(default=60)

    ota_enabled: bool = Field(default=True)
    ota_version: str = Field(default="")
    ota_bin_url: str = Field(default="")
    ota_bin_id: str = Field(default="")
    ota_is_official: str = Field(default="0")

    def model_post_init(self, __context: Any) -> None:
        # 数据库配置映射
        if self.database_url:
            self.database.url = self.database_url
        if self.database_sync_url:
            self.database.sync_url = self.database_sync_url
        if self.database_echo:
            self.database.echo = True

        if self.asr_provider:
            self.asr.provider = self.asr_provider
        if self.asr_tencent_app_id:
            self.asr.tencent_app_id = self.asr_tencent_app_id
        if self.asr_tencent_secret_id:
            self.asr.tencent_secret_id = self.asr_tencent_secret_id
        if self.asr_tencent_secret_key:
            self.asr.tencent_secret_key = self.asr_tencent_secret_key
        if self.asr_tencent_engine:
            self.asr.tencent_engine = self.asr_tencent_engine
        if self.asr_volcengine_api_key:
            self.asr.volcengine_api_key = self.asr_volcengine_api_key
        if self.asr_volcengine_resource_id:
            self.asr.volcengine_resource_id = self.asr_volcengine_resource_id
        if self.asr_volcengine_model:
            self.asr.volcengine_model = self.asr_volcengine_model
        if self.asr_no_speech_timeout > 0:
            self.asr.no_speech_timeout = self.asr_no_speech_timeout
        if self.asr_silence_timeout > 0:
            self.asr.silence_timeout = self.asr_silence_timeout
        if self.asr_max_concurrency > 0:
            self.asr.max_concurrency = self.asr_max_concurrency
        if not self.asr_pool_enabled:
            self.asr.enable_pool = False
        if self.asr_pool_max_size > 0:
            self.asr.pool_max_size = self.asr_pool_max_size
        if self.asr_pool_min_size > 0:
            self.asr.pool_min_size = self.asr_pool_min_size
        if self.asr_pool_heartbeat_interval > 0:
            self.asr.pool_heartbeat_interval = self.asr_pool_heartbeat_interval
        if self.asr_pool_idle_timeout > 0:
            self.asr.pool_idle_timeout = self.asr_pool_idle_timeout
        if self.asr_pool_connection_timeout > 0:
            self.asr.pool_connection_timeout = self.asr_pool_connection_timeout

        if self.llm_api_key:
            self.llm.api_key = self.llm_api_key
        if self.llm_base_url:
            self.llm.base_url = self.llm_base_url
        if self.llm_model:
            self.llm.model = self.llm_model
        if self.llm_system_prompt:
            self.llm.system_prompt = self.llm_system_prompt
        if not self.llm.system_prompt:
            self.llm.system_prompt = _DEFAULT_SYSTEM_PROMPT
        if self.llm_temperature > 0:
            self.llm.temperature = self.llm_temperature
        if self.llm_max_tokens > 0:
            self.llm.max_tokens = self.llm_max_tokens
        if not self.llm_memory_enabled:
            self.llm.memory_enabled = False
        if self.llm_memory_max_messages > 0:
            self.llm.memory_max_messages = self.llm_memory_max_messages
        if self.llm_memory_max_tokens > 0:
            self.llm.memory_max_tokens = self.llm_memory_max_tokens
        if not self.llm_memory_long_term_enabled:
            self.llm.memory_long_term_enabled = False
        if not self.llm_memory_long_term_auto_extract:
            self.llm.memory_long_term_auto_extract = False

        if self.tts_volcengine_api_key:
            self.tts.api_key = self.tts_volcengine_api_key
        if self.tts_volcengine_resource_id:
            self.tts.resource_id = self.tts_volcengine_resource_id
        if self.tts_volcengine_voice_type:
            self.tts.voice_type = self.tts_volcengine_voice_type
        if self.tts_volcengine_speed:
            try:
                self.tts.speed_ratio = float(self.tts_volcengine_speed)
            except (ValueError, TypeError):
                pass
        if self.tts_volcengine_volume:
            try:
                self.tts.volume_ratio = float(self.tts_volcengine_volume)
            except (ValueError, TypeError):
                pass
        if self.tts_volcengine_pitch:
            try:
                self.tts.pitch_ratio = float(self.tts_volcengine_pitch)
            except (ValueError, TypeError):
                pass
        if self.tts_volcengine_dialect:
            self.tts.explicit_dialect = self.tts_volcengine_dialect
        if self.tts_volcengine_sample_rate:
            try:
                self.tts.sample_rate = int(self.tts_volcengine_sample_rate)
            except (ValueError, TypeError):
                pass
        if not self.tts_pool_enabled:
            self.tts.enable_pool = False
        if self.tts_pool_max_size > 0:
            self.tts.pool_max_size = self.tts_pool_max_size
        if self.tts_pool_min_size > 0:
            self.tts.pool_min_size = self.tts_pool_min_size
        if self.tts_pool_heartbeat_interval > 0:
            self.tts.pool_heartbeat_interval = self.tts_pool_heartbeat_interval
        if self.tts_pool_idle_timeout > 0:
            self.tts.pool_idle_timeout = self.tts_pool_idle_timeout
        if self.tts_pool_connection_timeout > 0:
            self.tts.pool_connection_timeout = self.tts_pool_connection_timeout

        # auth_enabled 直接映射到 auth.enabled（默认 True，安全优先）
        # 支持 AUTH_ENABLED=false 显式关闭认证
        self.auth.enabled = self.auth_enabled
        if self.auth_api_key:
            self.auth.api_key = self.auth_api_key
        if self.admin_api_key:
            self.auth.admin_api_key = self.admin_api_key
        if self.jwt_secret:
            self.auth.jwt_secret = self.jwt_secret
        if self.debug_log:
            self.log.debug_log = True
        if self.log_format and self.log.format == "console":
            self.log.format = self.log_format
        if self.debug_log_level:
            try:
                self.log.level = LogLevel(self.debug_log_level.upper())
            except ValueError:
                pass
        if self.log_file_path:
            self.log.file_path = self.log_file_path
        if self.log_max_size > 0:
            self.log.max_size = self.log_max_size
        if self.log_backup_count > 0:
            self.log.backup_count = self.log_backup_count
        if self.rate_limit_max_rpm > 0:
            self.rate_limit.max_rpm = self.rate_limit_max_rpm
        if self.shutdown_grace_period > 0:
            self.shutdown.grace_period = self.shutdown_grace_period

        if self.wakeup_text:
            self.wakeup.text = self.wakeup_text
        if not self.enable_wakeup_audio:
            self.wakeup.enable_audio = False
        if not self.wake_audio_cache_enabled:
            self.wakeup.audio_cache_enabled = False
        if not self.wake_audio_play_enabled:
            self.wakeup.audio_play_enabled = False
        if self.wake_audio_source:
            self.wakeup.audio_source = self.wake_audio_source
        if self.wake_audio_on_next_round:
            self.wakeup.play_on_next_round = True

        # 情感检测开关：显式设置 True 或 False
        self.emotion.enabled = self.server_emotion_enabled
        if self.server_emotion_gif_dir:
            self.emotion.gif_dir = self.server_emotion_gif_dir
        if self.server_emotion_static_dir:
            self.emotion.static_dir = self.server_emotion_static_dir

        if self.mcp_servers_json:
            self.mcp.servers_json = self.mcp_servers_json

        if self.music_api_url:
            self.music.api_url = self.music_api_url
        if self.lyrics_offset != 0:
            self.music.lyrics_offset = self.lyrics_offset

        if self.host:
            self.server.host = self.host
        if self.port > 0:
            self.server.port = self.port

        # CORS 来源迁移：CORS_ORIGINS（逗号分隔）-> server.cors_origins
        if self.cors_origins:
            origins = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
            if origins:
                self.server.cors_origins = origins

        # Apply performance settings from env vars
        if self.perf_global_max_concurrent_sessions > 0:
            self.performance.global_max_concurrent_sessions = self.perf_global_max_concurrent_sessions
        if not self.perf_enable_global_concurrency_limit:
            self.performance.enable_global_concurrency_limit = False
        if self.perf_audio_queue_max_size > 0:
            self.performance.audio_queue_max_size = self.perf_audio_queue_max_size
        if self.perf_send_queue_max_size > 0:
            self.performance.send_queue_max_size = self.perf_send_queue_max_size
        if self.perf_max_messages_per_session > 0:
            self.performance.max_messages_per_session = self.perf_max_messages_per_session
        if self.perf_rate_limit_global_rpm > 0:
            self.performance.rate_limit_global_rpm = self.perf_rate_limit_global_rpm
        if self.perf_process_pool_max_workers > 0:
            self.performance.process_pool_max_workers = self.perf_process_pool_max_workers

        if not self.ota_enabled:
            self.ota.enabled = False
        if self.ota_version:
            self.ota.version = self.ota_version
        if self.ota_bin_url:
            self.ota.bin_url = self.ota_bin_url
        if self.ota_bin_id:
            self.ota.bin_id = self.ota_bin_id
        if self.ota_is_official:
            self.ota.is_official = self.ota_is_official
        
        # 性能配置日志
        from src.infrastructure.logging import get_logger
        logger = get_logger(__name__)
        logger.info(f"[Config] Performance settings loaded:")
        logger.info(f"  - Global concurrency limit: {self.performance.global_max_concurrent_sessions}")
        logger.info(f"  - ASR pool size: {self.asr.pool_max_size} (min: {self.asr.pool_min_size})")
        logger.info(f"  - TTS pool size: {self.tts.pool_max_size} (min: {self.tts.pool_min_size})")
        logger.info(f"  - Audio queue size: {self.performance.audio_queue_max_size}")
        logger.info(f"  - Send queue size: {self.performance.send_queue_max_size}")
        logger.info(f"  - Process pool workers: {self.performance.process_pool_max_workers}")
        logger.info(f"  - Max messages per session: {self.performance.max_messages_per_session}")
        logger.info(f"  - Global RPM limit: {self.performance.rate_limit_global_rpm}")

    @field_validator("llm", mode="before")
    @classmethod
    def set_default_system_prompt(cls, v):
        if isinstance(v, dict):
            if not v.get("system_prompt"):
                v["system_prompt"] = _DEFAULT_SYSTEM_PROMPT
        elif isinstance(v, LLMConfig) and not v.system_prompt:
            v.system_prompt = _DEFAULT_SYSTEM_PROMPT
        return v

    def validate_config(self) -> List[str]:
        # multi 模式下 ASR/LLM/TTS 配置从数据库读取，不检查 .env 密钥
        if self.deploy_mode == "multi":
            return []

        missing = []

        if not self.llm.api_key:
            missing.append("LLM_API_KEY")
        if not self.tts.api_key:
            missing.append("TTS_API_KEY")
        # 校验所有 ASR provider 的必要配置
        if self.asr.provider == "tencent" and not self.asr.tencent_secret_key:
            missing.append("ASR_TENCENT_SECRET_KEY")
        elif self.asr.provider == "volcengine" and not self.asr.volcengine_api_key:
            missing.append("ASR_VOLCENGINE_API_KEY")
        elif self.asr.provider == "aliyun" and not self.asr.aliyun_access_key_id:
            missing.append("ASR_ALIYUN_ACCESS_KEY_ID")
        elif self.asr.provider == "xunfei" and not self.asr.xunfei_app_id:
            missing.append("ASR_XUNFEI_APP_ID")

        return missing


_settings_instance: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
    return _settings_instance


def reset_settings() -> None:
    global _settings_instance
    _settings_instance = None


def _get_compat_settings() -> Settings:
    return get_settings()


SID_CONNECTED = "0001"
SID_TTS = "0010"
SID_WAKE = "1001"
SID_REST = "1002"

SCREEN_WIDTH = 80
SCREEN_HEIGHT = 80


__all__ = [
    "Settings",
    "get_settings",
    "reset_settings",
    "SID_CONNECTED",
    "SID_TTS",
    "SID_WAKE",
    "SID_REST",
    "SCREEN_WIDTH",
    "SCREEN_HEIGHT",
    "ServerConfig",
    "AuthConfig",
    "LogConfig",
    "ASRConfig",
    "LLMConfig",
    "TTSConfig",
    "AudioConfig",
    "WakeupConfig",
    "EmotionConfig",
    "MCPConfig",
    "MusicConfig",
    "RateLimitConfig",
    "ShutdownConfig",
    "SessionConfig",
    "LogLevel",
    "OTAConfig",
]
