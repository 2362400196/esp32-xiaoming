"""
WeChat iLink Bot — 微信集成模块

基于 ESP-Claw 的 cap_im_wechat.c 逻辑移植到 Python。
实现微信 iLink Bot 协议的：
  - 二维码扫码登录
  - 消息轮询（getupdates）
  - 文本/图片发送
  - 消息去重

使用方式：
    bot = WeChatBot()
    await bot.start()
    status = await bot.qr_login_start("my_account")
    # 扫码成功后 bot 自动开始轮询
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

import httpx

from src.infrastructure.logging import get_logger
logger = get_logger(__name__)

# ──────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────
DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
DEFAULT_CDN_BASE_URL = "https://novac2c.cdn.weixin.qq.com/c2c"
DEFAULT_APP_ID = "bot"
DEFAULT_CLIENT_VERSION = "131329"
QR_TTL_SECONDS = 5 * 60  # 二维码 5 分钟有效期
QR_MAX_REFRESH = 3
POLL_TIMEOUT_SECONDS = 35
RETRY_DELAY_SECONDS = 2
MAX_SESSION_TIMEOUT_COUNT = 5  # 连续会话超时达到该次数即判定 token 失效，停止轮询
MAX_MSG_LEN = 4000
DEDUP_CACHE_SIZE = 64
CONTEXT_CACHE_SIZE = 32

# 微信数据文件（统一存储 token + 绑定关系）
WECHAT_DATA_FILE = "data/wechat_bot_data.json"


def _load_wechat_data() -> dict:
    """加载微信数据文件。"""
    import os
    if not os.path.exists(WECHAT_DATA_FILE):
        return {"token": {}, "bindings": []}
    try:
        with open(WECHAT_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"token": {}, "bindings": []}


def _save_wechat_data(data: dict) -> None:
    """原子写入微信数据文件。"""
    import os
    os.makedirs(os.path.dirname(WECHAT_DATA_FILE), exist_ok=True)
    tmp = WECHAT_DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, WECHAT_DATA_FILE)


class QRStatus(str, Enum):
    IDLE = "idle"
    WAITING_SCAN = "waiting_scan"
    SCANNED = "scanned"
    REDIRECTED = "redirected"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    ERROR = "error"


@dataclass
class QRLoginState:
    """二维码登录状态"""
    active: bool = False
    completed: bool = False
    persisted: bool = False
    session_key: str = ""
    account_id: str = ""
    status: str = "idle"
    message: str = ""
    qrcode: str = ""
    qr_data_url: str = ""
    bot_token: str = ""
    ilink_bot_id: str = ""
    ilink_user_id: str = ""
    base_url: str = ""
    current_api_base_url: str = ""
    started_at: float = 0.0
    refresh_count: int = 0
    stop_requested: bool = False


@dataclass
class WeChatClientConfig:
    """微信客户端配置"""
    token: str = ""
    base_url: str = DEFAULT_BASE_URL
    cdn_base_url: str = DEFAULT_CDN_BASE_URL
    account_id: str = "default"
    app_id: str = DEFAULT_APP_ID
    client_version: str = DEFAULT_CLIENT_VERSION
    route_tag: str = ""


@dataclass
class WeChatState:
    """微信 Bot 运行时状态"""
    token: str = ""
    base_url: str = DEFAULT_BASE_URL
    cdn_base_url: str = DEFAULT_CDN_BASE_URL
    account_id: str = "default"
    app_id: str = DEFAULT_APP_ID
    client_version: str = DEFAULT_CLIENT_VERSION
    route_tag: str = ""
    configured: bool = False
    stop_requested: bool = False
    token_invalid: bool = False  # token 已失效，需重新扫码登录
    sync_buf: str = ""
    seen_msg_keys: list[int] = field(default_factory=list)
    context_cache: dict[str, str] = field(default_factory=dict)
    conversation_history: dict[str, list[dict]] = field(default_factory=dict)  # chat_id → [{"role":"user/assistant","content":"..."}]
    voice_mode: dict[str, bool] = field(default_factory=dict)  # chat_id → True=语音模式
    qr: QRLoginState = field(default_factory=QRLoginState)
    http_client: Optional[httpx.AsyncClient] = None
    poll_task: Optional[asyncio.Task] = None
    qr_task: Optional[asyncio.Task] = None


# 消息回调类型
OnMessageCallback = Callable[["WeChatBot", str, str, str, str, str], None]
"""(bot, chat_id, sender_id, message_id, text, context_token) -> None"""

OnAttachmentCallback = Callable[["WeChatBot", str, str, str, dict], None]
"""(bot, chat_id, sender_id, message_id, payload) -> None"""


class WeChatBot:
    """微信 iLink Bot — 消息收发引擎"""

    def __init__(self, config: Optional[WeChatClientConfig] = None):
        self.state = WeChatState()
        self.on_message: Optional[OnMessageCallback] = None
        self.on_attachment: Optional[OnAttachmentCallback] = None
        if config:
            self.set_client_config(config)
        # 尝试从文件恢复 token
        if not self.state.configured:
            self._load_persisted_token()

    # ── 配置 ──────────────────────────────────

    def set_client_config(self, config: WeChatClientConfig) -> None:
        """设置客户端配置"""
        self.state.token = config.token or ""
        self.state.base_url = config.base_url or DEFAULT_BASE_URL
        self.state.cdn_base_url = config.cdn_base_url or DEFAULT_CDN_BASE_URL
        self.state.account_id = config.account_id or "default"
        self.state.app_id = config.app_id or DEFAULT_APP_ID
        self.state.client_version = config.client_version or DEFAULT_CLIENT_VERSION
        self.state.route_tag = config.route_tag or ""
        self.state.configured = bool(self.state.token and self.state.base_url)
        if self.state.configured:
            self.state.token_invalid = False

    def set_attachment_config(self) -> None:
        """占位：附件配置（当前仅日志记录）"""
        pass

    # ── 生命周期 ──────────────────────────────

    async def start(self) -> None:
        """启动轮询任务"""
        if self.state.poll_task and not self.state.poll_task.done():
            return
        self.state.stop_requested = False
        self.state.poll_task = asyncio.create_task(self._poll_loop())
        logger.info("[WeChat] 轮询任务已启动")

    async def stop(self) -> None:
        """停止轮询"""
        self.state.stop_requested = True
        self.state.qr.stop_requested = True
        self.state.qr.active = False
        if self.state.poll_task:
            self.state.poll_task.cancel()
            try:
                await self.state.poll_task
            except asyncio.CancelledError:
                pass
            self.state.poll_task = None
        if self.state.qr_task:
            self.state.qr_task.cancel()
            try:
                await self.state.qr_task
            except asyncio.CancelledError:
                pass
            self.state.qr_task = None
        if self.state.http_client:
            await self.state.http_client.aclose()
            self.state.http_client = None
        logger.info("[WeChat] 已停止")

    async def apply_qr_token_and_start(self) -> bool:
        """将 QR 登录获取的 bot_token 应用到 state 并启动轮询

        返回 True 表示成功启动，False 表示没有可用的 QR token。
        """
        if not self.state.qr.bot_token:
            logger.warning("[WeChat] 无 QR bot_token 可用")
            return False

        self.state.token = self.state.qr.bot_token
        if self.state.qr.base_url:
            self.state.base_url = self.state.qr.base_url.rstrip(",")
        self.state.configured = True
        self.state.token_invalid = False
        logger.info(f"[WeChat] 应用 QR token 并启动轮询: token_len={len(self.state.token)}, "
                     f"base_url={self.state.base_url}")

        # 持久化 token 到文件，重启后自动恢复
        self._persist_token()

        await self.start()
        return True

    def _persist_token(self) -> None:
        """持久化 token 和 base_url 到统一数据文件（原子写入）"""
        data = _load_wechat_data()
        data["token"] = {
            "token": self.state.token,
            "base_url": self.state.base_url,
            "account_id": self.state.account_id,
        }
        _save_wechat_data(data)
        logger.info(f"[WeChat] token 已持久化到 {WECHAT_DATA_FILE}")

    def _load_persisted_token(self) -> bool:
        """从统一数据文件加载持久化的 token"""
        data = _load_wechat_data()
        tok = data.get("token", {})
        if not tok.get("token"):
            return False
        self.state.token = tok.get("token", "")
        self.state.base_url = tok.get("base_url", DEFAULT_BASE_URL)
        self.state.account_id = tok.get("account_id", "default")
        if self.state.token:
            self.state.configured = True
            return True
        return False

    def _clear_persisted_token(self) -> None:
        """清空统一数据文件中的 token（token 失效后避免重启自动重试）"""
        data = _load_wechat_data()
        if data.get("token"):
            data["token"] = {}
            _save_wechat_data(data)
            logger.info("[WeChat] token 已失效，已清除持久化 token，需重新扫码登录")

    # ── HTTP 客户端 ───────────────────────────

    def _get_client(self) -> httpx.AsyncClient:
        if not self.state.http_client:
            timeout = httpx.Timeout(POLL_TIMEOUT_SECONDS + 10, connect=10.0)
            self.state.http_client = httpx.AsyncClient(
                timeout=timeout,
                verify=True,
            )
        return self.state.http_client

    def _build_common_headers(self) -> dict:
        """构建微信 iLink API 公共请求头（与 ESP-Claw cap_im_wechat_http_request 对应）"""
        import secrets
        import base64
        # 生成随机 X-WECHAT-UIN（类似 ESP-Claw 的 cap_im_wechat_build_x_wechat_uin）
        rand_val = str(secrets.randbits(32))
        x_wechat_uin = base64.b64encode(rand_val.encode()).decode().rstrip("=\n")
        headers = {
            "Content-Type": "application/json",
            "iLink-App-Id": self.state.app_id,
            "iLink-App-ClientVersion": self.state.client_version,
            "X-WECHAT-UIN": x_wechat_uin,
        }
        if self.state.route_tag:
            headers["SKRouteTag"] = self.state.route_tag
        return headers

    def _build_auth_headers(self) -> dict:
        """构建微信 iLink API 认证请求头"""
        headers = {
            "AuthorizationType": "ilink_bot_token",
        }
        if self.state.token:
            headers["Authorization"] = f"Bearer {self.state.token}"
        return headers

    async def _api_post(self, endpoint: str, body: dict, timeout: float = 15.0) -> dict:
        """向微信 iLink API 发送 POST 请求"""
        url = f"{self.state.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        client = self._get_client()
        req_headers = {
            **self._build_common_headers(),
            **self._build_auth_headers(),
        }
        try:
            resp = await client.post(url, json=body, headers=req_headers, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            # 检查错误码
            for key in ("ret", "errcode", "code"):
                code = data.get(key)
                if isinstance(code, (int, float)) and code != 0:
                    errmsg = data.get("errmsg", str(data))
                    logger.warning(f"[WeChat] API {endpoint} 错误: {key}={code}, errmsg={errmsg}, "
                                   f"raw_body={str(data)[:300]}")
                    raise WeChatAPIError(code, errmsg)
            return data
        except httpx.TimeoutException:
            logger.warning(f"[WeChat] API 超时: {endpoint}")
            raise
        except httpx.HTTPStatusError as e:
            logger.warning(f"[WeChat] HTTP 错误: {e}")
            raise

    async def _api_get(self, base_url: str, endpoint: str, timeout: float = 15.0) -> dict:
        """向微信 iLink API 发送 GET 请求"""
        url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        client = self._get_client()
        req_headers = self._build_common_headers()
        try:
            resp = await client.get(url, headers=req_headers, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            for key in ("ret", "errcode", "code"):
                code_val = data.get(key)
                if isinstance(code_val, (int, float)) and code_val != 0:
                    logger.warning(f"[WeChat] API GET 错误: {key}={code_val}")
                    raise WeChatAPIError(code_val, data.get("errmsg", str(data)))
            return data
        except httpx.TimeoutException:
            logger.warning(f"[WeChat] API GET 超时: {endpoint}")
            raise

    # ── 基础请求辅助 ──────────────────────────

    def _build_base_info(self) -> dict:
        """构建基础请求信息（与 ESP-Claw cap_im_wechat_add_base_info 对应）"""
        info = {
            "token": self.state.token,
            "account_id": self.state.account_id,
            "appid": self.state.app_id,
            "clientversion": self.state.client_version,
        }
        return info

    # ── 二维码登录 ──────────────────────────

    async def qr_login_start(self, account_id: str = "", force: bool = False) -> QRLoginState:
        """启动二维码登录流程"""
        if self.state.qr.active and not force:
            return self.state.qr

        # 重置状态
        self.state.qr = QRLoginState()
        self.state.qr.active = True
        self.state.qr.persisted = False
        if account_id:
            self.state.qr.account_id = account_id
        self.state.qr.session_key = f"wxqr-{secrets.token_hex(8)}"

        # 获取二维码
        try:
            await self._qr_fetch_code()
        except Exception as e:
            self.state.qr.active = False
            self.state.qr.status = QRStatus.ERROR.value
            self.state.qr.message = f"拉取二维码失败: {e}"
            logger.error(f"[WeChat] 二维码获取失败: {e}")
            return self.state.qr

        # 启动状态轮询
        self.state.qr_task = asyncio.create_task(self._qr_poll_loop())
        return self.state.qr

    async def qr_login_get_status(self) -> QRLoginState:
        """获取二维码登录状态"""
        return self.state.qr

    async def qr_login_cancel(self) -> None:
        """取消二维码登录"""
        self.state.qr.stop_requested = True
        self.state.qr.active = False
        self.state.qr.status = QRStatus.CANCELLED.value
        self.state.qr.message = "已取消微信登录。"

    def qr_login_mark_persisted(self) -> None:
        """标记登录状态已持久化"""
        self.state.qr.persisted = True

    async def _qr_fetch_code(self) -> None:
        """获取登录二维码"""
        data = await self._api_get(
            DEFAULT_BASE_URL,
            "ilink/bot/get_bot_qrcode?bot_type=3",
            timeout=5.0,
        )
        qrcode = data.get("qrcode", "")
        qrcode_img_content = data.get("qrcode_img_content", "")
        if not qrcode or not qrcode_img_content:
            raise WeChatAPIError(-1, "二维码数据不完整")

        self.state.qr.qrcode = qrcode
        self.state.qr.qr_data_url = qrcode_img_content
        self.state.qr.status = QRStatus.WAITING_SCAN.value
        self.state.qr.message = "使用微信扫描二维码完成登录。"
        self.state.qr.started_at = time.time()
        self.state.qr.current_api_base_url = DEFAULT_BASE_URL
        logger.info("[WeChat] 二维码已获取，等待扫描")

    async def _qr_poll_loop(self) -> None:
        """二维码状态轮询任务"""
        while True:
            if self.state.qr.stop_requested or not self.state.qr.active:
                break

            # 检查 TTL
            elapsed = time.time() - self.state.qr.started_at
            if elapsed > QR_TTL_SECONDS:
                if self.state.qr.refresh_count >= QR_MAX_REFRESH:
                    self.state.qr.status = QRStatus.EXPIRED.value
                    self.state.qr.message = "二维码已多次过期，请重新生成。"
                    self.state.qr.active = False
                    break
                self.state.qr.refresh_count += 1
                try:
                    await self._qr_fetch_code()
                except Exception as e:
                    self.state.qr.status = QRStatus.ERROR.value
                    self.state.qr.message = f"刷新二维码失败: {e}"
                    self.state.qr.active = False
                    break
                await asyncio.sleep(0.5)
                continue

            # 轮询状态
            try:
                await self._qr_poll_once()
                if self.state.qr.completed:
                    logger.info("[WeChat] 二维码登录成功，自动激活 token...")
                    self.state.qr.active = False
                    ok = await self.apply_qr_token_and_start()
                    if ok:
                        logger.info("[WeChat] 自动激活 token 成功，消息轮询已启动")
                    else:
                        logger.warning("[WeChat] 自动激活 token 失败，无 bot_token")
                    break
            except WeChatAPIError as e:
                if "expired" in str(e) or "timeout" in str(e):
                    if self.state.qr.refresh_count >= QR_MAX_REFRESH:
                        self.state.qr.active = False
                        break
                    self.state.qr.refresh_count += 1
                    try:
                        await self._qr_fetch_code()
                    except Exception:
                        self.state.qr.active = False
                        break
                else:
                    self.state.qr.status = QRStatus.ERROR.value
                    self.state.qr.message = f"轮询扫码状态失败: {e}"
                    self.state.qr.active = False
                    break
            except Exception as e:
                self.state.qr.status = QRStatus.ERROR.value
                self.state.qr.message = f"轮询扫码状态失败: {e}"
                self.state.qr.active = False
                break

            await asyncio.sleep(0.5)

    async def _qr_poll_once(self) -> None:
        """单次二维码状态轮询"""
        if not self.state.qr.qrcode:
            raise WeChatAPIError(-1, "无二维码")

        api_base = self.state.qr.current_api_base_url or DEFAULT_BASE_URL
        data = await self._api_get(
            api_base,
            f"ilink/bot/get_qrcode_status?qrcode={self.state.qr.qrcode}",
            timeout=POLL_TIMEOUT_SECONDS,
        )

        status = data.get("status", "")
        redirect_host = data.get("redirect_host", "")
        bot_token = data.get("bot_token", "")
        ilink_bot_id = data.get("ilink_bot_id", "")
        ilink_user_id = data.get("ilink_user_id", "")
        baseurl = data.get("baseurl", "")

        if status == "wait":
            self.state.qr.status = QRStatus.WAITING_SCAN.value
            self.state.qr.message = "等待扫码。"
        elif status == "scanned":
            self.state.qr.status = QRStatus.SCANNED.value
            self.state.qr.message = "已扫码，请在微信中确认。"
        elif status == "scaned_but_redirect":
            if redirect_host:
                self.state.qr.current_api_base_url = f"https://{redirect_host}"
            self.state.qr.status = QRStatus.REDIRECTED.value
            self.state.qr.message = "登录节点已切换，继续等待确认。"
        elif status == "expired":
            self.state.qr.status = QRStatus.EXPIRED.value
            self.state.qr.message = "二维码已过期。"
            raise WeChatAPIError(-1, "expired")
        elif status == "confirmed":
            self.state.qr.status = QRStatus.CONFIRMED.value
            self.state.qr.message = "微信登录成功。"
            logger.info(f"[WeChat] QR confirmed response: bot_token={'***'+bot_token[-8:] if bot_token else 'NONE'}, "
                        f"ilink_bot_id={ilink_bot_id}, ilink_user_id={ilink_user_id}, "
                        f"baseurl={baseurl}, redirect_host={redirect_host}")
            if bot_token:
                self.state.qr.bot_token = bot_token
            if ilink_bot_id:
                self.state.qr.ilink_bot_id = ilink_bot_id
            if ilink_user_id:
                self.state.qr.ilink_user_id = ilink_user_id
            if baseurl:
                self.state.qr.base_url = baseurl.rstrip(",")
            else:
                self.state.qr.base_url = self.state.qr.current_api_base_url or DEFAULT_BASE_URL
            # QR 登录成功，bot_token 已保存到 qr.bot_token
            # 注意：不自动将 QR token 注入到 polling（与 ESP-Claw 行为一致）
            # 用户需要保存该 token 到配置后重启，或通过 API 手动设置
            self.state.qr.completed = True
            self.state.qr.active = False
            logger.info(f"[WeChat] 登录成功: bot_id={ilink_bot_id}, user_id={ilink_user_id}, "
                        f"最终 base_url={self.state.qr.base_url}")
        else:
            self.state.qr.status = QRStatus.ERROR.value
            self.state.qr.message = f"二维码状态未知: {status}"

    # ── 消息轮询 ──────────────────────────────

    async def _poll_loop(self) -> None:
        """消息轮询循环"""
        session_reset_count = 0
        while not self.state.stop_requested:
            if not self.state.configured:
                await asyncio.sleep(5)
                continue

            try:
                await self._poll_once()
                session_reset_count = 0  # 成功后重置计数
            except WeChatAPIError as e:
                if e.code == -14 or "session timeout" in str(e).lower():
                    session_reset_count += 1
                    if session_reset_count == 3:
                        logger.warning(f"[WeChat] 连续 {session_reset_count} 次会话超时，token 可能无效，"
                                      f"检查 base_url={self.state.base_url}, token_len={len(self.state.token)}")
                    if session_reset_count >= MAX_SESSION_TIMEOUT_COUNT:
                        logger.error(f"[WeChat] 连续 {session_reset_count} 次会话超时，判定 token 已失效，"
                                     f"停止轮询，请重新扫码登录。base_url={self.state.base_url}, "
                                     f"token_len={len(self.state.token)}")
                        self.state.token_invalid = True
                        self.state.configured = False
                        self.state.sync_buf = ""
                        self._clear_persisted_token()
                        break
                    self.state.sync_buf = ""
                    # 会话超时时不能无间隔重试，否则会雪崩
                    await asyncio.sleep(RETRY_DELAY_SECONDS)
                else:
                    logger.warning(f"[WeChat] 轮询失败: {e}, 将在 {RETRY_DELAY_SECONDS}s 后重试")
                    await asyncio.sleep(RETRY_DELAY_SECONDS)
            except Exception as e:
                logger.warning(f"[WeChat] 轮询失败: {e}, 将在 {RETRY_DELAY_SECONDS}s 后重试")
                await asyncio.sleep(RETRY_DELAY_SECONDS)

    async def _poll_once(self) -> None:
        """单次消息轮询"""
        body = {
            "get_updates_buf": self.state.sync_buf,
            **self._build_base_info(),
        }
        logger.info(f"[WeChat] getupdates request: token_len={len(self.state.token)}, "
                     f"base_url={self.state.base_url}, sync_buf_len={len(self.state.sync_buf)}, "
                     f"account_id={self.state.account_id}, appid={self.state.app_id}")
        data = await self._api_post(
            "ilink/bot/getupdates",
            body,
            timeout=POLL_TIMEOUT_SECONDS + 5,
        )

        # 更新 longpolling_timeout
        lp_timeout = data.get("longpolling_timeout_ms")
        if lp_timeout and isinstance(lp_timeout, (int, float)) and lp_timeout > 0:
            logger.debug(f"[WeChat] 更新 longpolling_timeout: {lp_timeout}ms")

        # 更新 sync_buf
        next_sync = data.get("get_updates_buf", "")
        if next_sync:
            self.state.sync_buf = next_sync

        msgs = data.get("msgs", [])
        if msgs:
            logger.info(f"[WeChat] getupdates 返回 {len(msgs)} 条消息")
        for msg in msgs:
            await self._process_message(msg)

    async def _process_message(self, msg: dict) -> None:
        """处理单条微信消息"""
        from_user_id = msg.get("from_user_id", "")
        group_id = msg.get("group_id", "")
        context_token = msg.get("context_token", "")
        message_id_val = msg.get("message_id", int(time.time() * 1000))
        message_id = str(message_id_val)

        chat_id = group_id if group_id else from_user_id
        if not chat_id:
            return

        # 记录群聊信息（供 App 端展示可选群聊）
        if group_id:
            from src.infrastructure.routes.wechat import add_recent_group
            add_recent_group(group_id, msg)

        # 去重
        key = self._fnv1a64(message_id)
        if key in self.state.seen_msg_keys:
            return
        self.state.seen_msg_keys.append(key)
        if len(self.state.seen_msg_keys) > DEDUP_CACHE_SIZE:
            self.state.seen_msg_keys = self.state.seen_msg_keys[-DEDUP_CACHE_SIZE:]

        # 记住 context_token
        if context_token:
            self.state.context_cache[chat_id] = context_token
            if len(self.state.context_cache) > CONTEXT_CACHE_SIZE:
                # 移除最早插入的
                oldest = next(iter(self.state.context_cache))
                del self.state.context_cache[oldest]

        # 解析消息内容
        item_list = msg.get("item_list", [])
        text_parts = []
        for item in item_list:
            item_type = item.get("type", 0)
            if item_type == 1:
                text_item = item.get("text_item", {})
                text = text_item.get("text", "")
                if text:
                    text_parts.append(text)
            elif item_type in (2, 3, 4, 5):
                # 媒体消息
                await self._process_media_item(item, chat_id, from_user_id, message_id)

        full_text = "".join(text_parts)
        if full_text:
            logger.info(f"[WeChat] 收到消息: chat_id={chat_id[:20]}, text={full_text[:80]}, "
                         f"有回调={self.on_message is not None}")
        if full_text and self.on_message:
            try:
                await self.on_message(self, chat_id, from_user_id, message_id, full_text, context_token)
            except Exception as e:
                logger.error(f"[WeChat] on_message 回调异常: {e}", exc_info=True)

    async def _process_media_item(
        self, item: dict, chat_id: str, from_user_id: str, message_id: str
    ) -> None:
        """处理媒体消息（图片/文件等），下载并解密"""
        item_type = item.get("type", 0)
        logger.info(f"[WeChat] 收到媒体消息: type={item_type}, chat_id={chat_id}")

        # 仅处理图片（type=2）
        if item_type != 2:
            return

        # 提取媒体信息
        holder = item.get("image_item") or item.get("file_item") or {}
        media = holder.get("media", {})
        if not media:
            return

        full_url = media.get("full_url", "")
        encrypt_param = media.get("encrypt_query_param", "")
        aes_key_b64 = media.get("aes_key", "")
        mid_size = holder.get("mid_size", 0)

        if not full_url and not encrypt_param:
            logger.warning(f"[WeChat] 图片缺少下载地址")
            return

        # 下载加密数据
        encrypted_data = await self._download_media(full_url, encrypt_param, mid_size)
        if not encrypted_data:
            return

        # AES-ECB 解密
        plaintext = self._aes_ecb_decrypt(encrypted_data, aes_key_b64)
        if not plaintext:
            logger.warning(f"[WeChat] 图片解密失败")
            return

        # 转为 base64 data URL
        import base64
        img_b64 = base64.b64encode(plaintext).decode()
        img_data_url = f"data:image/jpeg;base64,{img_b64}"
        logger.info(f"[WeChat] 图片已下载解密 ({len(plaintext)} bytes)")

        # 触发 on_attachment 回调
        if self.on_attachment:
            await self.on_attachment(self, chat_id, from_user_id, message_id, {
                "type": "image",
                "data_url": img_data_url,
                "chat_id": chat_id,
                "sender_id": from_user_id,
            })

    async def _download_media(self, full_url: str, encrypt_param: str, max_size: int) -> bytes | None:
        """从微信 CDN 下载加密的媒体数据"""
        import urllib.parse
        url = ""
        if full_url:
            url = full_url
        elif encrypt_param:
            encoded = urllib.parse.quote(encrypt_param)
            url = f"{self.state.cdn_base_url}/download?encrypted_query_param={encoded}"
        if not url:
            return None
        try:
            client = self._get_client()
            resp = await client.get(url, timeout=30.0)
            resp.raise_for_status()
            return resp.content
        except Exception as e:
            logger.warning(f"[WeChat] 图片下载失败: {e}")
            return None

    @staticmethod
    def _aes_ecb_decrypt(data: bytes, aes_key_base64: str) -> bytes | None:
        """AES-ECB 解密图片数据"""
        import base64
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.backends import default_backend
        try:
            key = base64.b64decode(aes_key_base64)
            cipher = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend())
            decryptor = cipher.decryptor()
            plaintext = decryptor.update(data) + decryptor.finalize()
            # 去除 PKCS7 填充
            pad_len = plaintext[-1]
            return plaintext[:-pad_len]
        except Exception as e:
            logger.warning(f"[WeChat] AES 解密失败: {e}")
            return None

    @staticmethod
    def _fnv1a64(text: str) -> int:
        """FNV-1a 64位哈希"""
        h = 1469598103934665603
        for ch in text.encode("utf-8"):
            h ^= ch
            h *= 1099511628211
            h &= 0xFFFFFFFFFFFFFFFF
        return h

    # ── 消息发送 ──────────────────────────────

    async def send_text(self, chat_id: str, text: str) -> bool:
        """发送文本消息（支持长文本自动分片），返回是否全部发送成功"""
        if not self.state.configured:
            raise WeChatAPIError(-1, "微信未配置")

        offset = 0
        success = True
        while offset < len(text):
            chunk = text[offset: offset + MAX_MSG_LEN]
            # UTF-8 安全截断
            while len(chunk.encode("utf-8")) > MAX_MSG_LEN:
                chunk = chunk[:-1]
            if not chunk:
                break

            sent = False
            for attempt in range(3):
                try:
                    await self._send_text_chunk(chat_id, chunk)
                    sent = True
                    break
                except WeChatAPIError as e:
                    if e.code == -2 and attempt < 2:
                        logger.warning(f"[WeChat] 发送文本分片失败 (retry {attempt+1}/3): {e}")
                        await asyncio.sleep(1.0)
                    else:
                        logger.warning(f"[WeChat] 发送文本分片失败: {e}")
                        break
            if not sent:
                success = False
                # ret=-2 持续失败说明 token 可能已失效，标记为无效
                logger.error(f"[WeChat] 发送消息彻底失败，token 可能已失效，请重新扫码登录。"
                            f"base_url={self.state.base_url}, token_len={len(self.state.token)}")
                self.state.token_invalid = True
                self.state.configured = False
                self.state.sync_buf = ""
                self._clear_persisted_token()
                break
            offset += len(chunk)
        return success

    async def _send_text_chunk(self, chat_id: str, chunk: str) -> None:
        """发送单条文本消息块"""
        msg = {
            "from_user_id": "",
            "to_user_id": chat_id,
            "client_id": f"espwx-{secrets.token_hex(8)}",
            "message_type": 2,
            "message_state": 2,
            "item_list": [
                {
                    "type": 1,
                    "text_item": {"text": chunk},
                }
            ],
        }
        # 携带 context_token 维持上下文
        context_token = self.state.context_cache.get(chat_id)
        if context_token:
            msg["context_token"] = context_token

        body = {
            "msg": msg,
            **self._build_base_info(),
        }
        await self._api_post("ilink/bot/sendmessage", body, timeout=15.0)
        logger.info(f"[WeChat] 已发送文本到 {chat_id}: {chunk[:80]}...")

    async def send_image(self, chat_id: str, image_path: str, caption: str = "") -> None:
        """发送图片消息"""
        if not self.state.configured:
            raise WeChatAPIError(-1, "微信未配置")

        if caption:
            await self.send_text(chat_id, caption)

        # 读取图片文件
        import aiofiles
        async with aiofiles.open(image_path, "rb") as f:
            plaintext = await f.read()

        plaintext_len = len(plaintext)
        md5_hex = hashlib.md5(plaintext).hexdigest()
        aes_key_raw = secrets.token_hex(16)
        filekey_hex = secrets.token_hex(16)

        # 获取上传 URL
        upload_body = {
            "filekey": filekey_hex,
            "media_type": 1,
            "to_user_id": chat_id,
            "rawsize": plaintext_len,
            "rawfilemd5": md5_hex,
            "filesize": ((plaintext_len // 16) + 1) * 16,
            "no_need_thumb": 1,
            "aeskey": aes_key_raw,
            **self._build_base_info(),
        }
        upload_resp = await self._api_post("ilink/bot/getuploadurl", upload_body, timeout=15.0)
        upload_full_url = upload_resp.get("upload_full_url", "")
        upload_param = upload_resp.get("upload_param", "")

        if not upload_full_url and not upload_param:
            raise WeChatAPIError(-1, f"获取上传 URL 失败: {upload_resp}")

        # AES-ECB 加密
        encrypted = self._aes_ecb_encrypt(plaintext, bytes.fromhex(aes_key_raw))
        ciphertext_size = len(encrypted)

        # 上传到 CDN
        if upload_full_url:
            upload_target = upload_full_url
        else:
            import urllib.parse
            upload_target = (
                f"{self.state.cdn_base_url}/upload"
                f"?encrypted_query_param={urllib.parse.quote(upload_param)}"
                f"&filekey={urllib.parse.quote(filekey_hex)}"
            )

        client = self._get_client()
        cdn_resp = await client.post(
            upload_target,
            content=encrypted,
            headers={"Content-Type": "application/octet-stream"},
            timeout=30.0,
        )
        cdn_resp.raise_for_status()
        cdn_data = cdn_resp.json()
        encrypted_param = cdn_data.get("encrypted_param", "")
        if not encrypted_param:
            raise WeChatAPIError(-1, "CDN 上传失败: 无 encrypted_param")

        # 发送图片消息
        aes_key_base64 = self._base64_encode(bytes.fromhex(aes_key_raw))
        msg = {
            "from_user_id": "",
            "to_user_id": chat_id,
            "client_id": f"espwx-{secrets.token_hex(8)}",
            "message_type": 2,
            "message_state": 2,
            "item_list": [
                {
                    "type": 2,
                    "image_item": {
                        "media": {
                            "encrypt_query_param": encrypted_param,
                            "aes_key": aes_key_base64,
                            "encrypt_type": 1,
                        },
                        "mid_size": ciphertext_size,
                    },
                }
            ],
        }
        context_token = self.state.context_cache.get(chat_id)
        if context_token:
            msg["context_token"] = context_token

        body = {"msg": msg, **self._build_base_info()}
        await self._api_post("ilink/bot/sendmessage", body, timeout=15.0)
        logger.info(f"[WeChat] 已发送图片到 {chat_id}")

    @staticmethod
    def _aes_ecb_encrypt(plaintext: bytes, key: bytes) -> bytes:
        """AES-ECB 加密（补齐到 16 字节倍数）"""
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.backends import default_backend

        pad_len = 16 - (len(plaintext) % 16)
        padded = plaintext + bytes([pad_len] * pad_len)

        cipher = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend())
        encryptor = cipher.encryptor()
        return encryptor.update(padded) + encryptor.finalize()

    @staticmethod
    def _base64_encode(data: bytes) -> str:
        """Base64 编码"""
        import base64
        return base64.b64encode(data).decode("ascii")


class WeChatAPIError(Exception):
    """微信 API 错误"""

    def __init__(self, code: int, message: str = ""):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")
