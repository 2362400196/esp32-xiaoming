"""
Session Management - 会话管理

与旧架构(app/session/session.py, app/websocket/session_runtime.py)完全对齐：
- SessionRuntime: ASR/TTS生命周期管理
- Session: 完整会话类（ASR → Pipeline → 下一轮ASR循环）
- Watchdog: 超时监控
"""
from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import suppress
from typing import TYPE_CHECKING, Callable, Optional

from src.domain.entities import SessionState
from src.infrastructure.logging import get_logger, trace_id_var
from src.infrastructure.monitoring import get_metrics
from src.use_cases.auxiliary_services import AudioProcessor, ConversationMemory
from src.use_cases.pipeline import ConversationPipeline, PipelineConfig, SentenceSplitter
from src.use_cases.queues import BackpressureQueues
from src.use_cases.session_fsm import SessionFSM, WSChannel
from src.use_cases.voice_generator import VoiceGenerator

if TYPE_CHECKING:
    from src.interfaces.asr.base import BaseASRGateway
    from src.interfaces.llm_gateways import OpenAILLMGateway
    from src.interfaces.tts_gateways import VolcEngineTTSGateway
    from src.use_cases.memory import LongTermMemoryServiceImpl
    from src.use_cases.ports import MemoryRepository
    from src.use_cases.tools_system import PerUserToolManager

logger = get_logger(__name__)


class SessionRuntime:
    """ASR/TTS 生命周期运行时"""

    def __init__(self):
        self.asr_full_text = ""
        self.asr_processed = False
        self.asr_last_audio_time = None
        self.asr_last_result_time = None
        self.asr_start_time = None
        self.asr_stop_event: asyncio.Event | None = None
        self.asr_task: asyncio.Task | None = None
        self.audio_queue: asyncio.Queue | None = None
        self.pre_asr_ws = None
        self._pre_asr_time = 0

    def reset(self):
        self.asr_full_text = ""
        self.asr_processed = False
        self.asr_last_audio_time = None
        self.asr_last_result_time = None
        self.asr_start_time = None
        self.asr_stop_event = None
        self.asr_task = None
        self.audio_queue = None


class Session:
    """
    完整会话类（与旧架构 app/session/session.py 完全对齐）

    管理完整的 ASR → Pipeline → 下一轮 ASR 对话循环
    """

    _WS_MAX_SIZE = 20 * 1024 * 1024
    _WS_PING_INTERVAL = None

    def __init__(
        self,
        device_id: str,
        channel: WSChannel,
        fsm: SessionFSM,
        voice_generator: VoiceGenerator,
        llm_processor: Optional["OpenAILLMGateway"],
        tts_processor: Optional["VolcEngineTTSGateway"],
        asr_client: Optional["BaseASRGateway"],
        tool_mgr: Optional["PerUserToolManager"],
        user_config: Optional[dict] = None,
        no_speech_timeout: float = 5.0,
        silence_timeout: float = 2.0,
        ltm_service: Optional["LongTermMemoryServiceImpl"] = None,
        client_max_buffer: int = 10240,
        memory_repository: Optional["MemoryRepository"] = None,
    ) -> None:
        self.device_id = device_id
        self.channel = channel
        self.fsm = fsm
        self.voice_generator = voice_generator
        self.llm_processor = llm_processor
        self.tts_processor = tts_processor
        self.asr_client = asr_client
        self.tool_mgr = tool_mgr
        self.user_config = user_config
        self.ltm_service = ltm_service
        self.client_max_buffer = client_max_buffer

        self.session_id = str(uuid.uuid4())[:8]
        self.runtime = SessionRuntime()
        self.queues = BackpressureQueues()
        self.splitter = SentenceSplitter()
        self.audio_processor = AudioProcessor()

        self.cancel_event = asyncio.Event()
        self._current_pipeline = None
        self._precomputed_skill_catalog: Optional[str] = None  # 预渲染的 skill catalog，避免首轮 Pipeline 阻塞

        # 通过构造函数注入会话记忆仓储（由接口层负责提供具体实现）
        repository = memory_repository
        self.conversation_memory = ConversationMemory(device_id=self.device_id, repository=repository)

        self._tts_playing = False
        self._tts_playing_lock = asyncio.Lock()
        self.tts_playback_done = asyncio.Event()
        self.tts_drain_ack = asyncio.Event()
        self.tts_audio_ended = asyncio.Event()

        self._device_buffer = client_max_buffer
        self._buffer_lock = asyncio.Lock()

        self._watchdog_task: asyncio.Task | None = None
        self._closed = False
        self.session_start_time = time.time()
        self.trace_id = ""
        self._wake_audio_played = asyncio.Event()
        self._waiting_wake_audio = False  # 标记 _do_wake_start 是否正在等待唤醒音频完成
        self._wake_audio_round = 0  # 唤醒轮次号，防止迟到消息串扰
        self._wake_audio_task_id = None  # 当前唤醒音频的 tts_task_id，用于区分音频来源
        self._last_emotion = None

        # 后台任务引用（防止被 GC 回收导致协程中途取消且无告警）
        self._bg_tasks: set = set()

        self.no_speech_timeout = no_speech_timeout
        self.silence_timeout = silence_timeout

    @property
    def tts_playing(self):
        return self._tts_playing

    async def set_tts_playing(self, value: bool):
        async with self._tts_playing_lock:
            self._tts_playing = value

    @property
    def device_buffer(self):
        return self._device_buffer

    async def set_device_buffer(self, value: int):
        async with self._buffer_lock:
            self._device_buffer = value

    async def start_asr(self, on_text, on_vad_end):
        # 业务指标：会话创建/激活（每轮 ASR 启动时记录）
        try:
            get_metrics().track_session_created()
        except Exception:
            pass
        if self.runtime.asr_task and not self.runtime.asr_task.done():
            logger.info(f"[Session:{self.session_id}] 检测到旧的 ASR 任务，先行取消")
            self.runtime.asr_task.cancel()
            self.runtime.asr_task = None
        if self.runtime.asr_stop_event:
            self.runtime.asr_stop_event.set()
        self.runtime.reset()
        self.audio_processor.reset()
        self.runtime.asr_start_time = time.time()
        self.runtime.asr_last_audio_time = None
        if not self.runtime.audio_queue:
            self.runtime.audio_queue = asyncio.Queue()
        elif not self.runtime.audio_queue.empty():
            logger.info(f"[Session:{self.session_id}] 清空旧音频队列，丢弃 {self.runtime.audio_queue.qsize()} 个数据包")
            while not self.runtime.audio_queue.empty():
                self.runtime.audio_queue.get_nowait()
                self.runtime.audio_queue.task_done()
        self.runtime.asr_stop_event = asyncio.Event()

        def _vad_cb():
            if not self.runtime.asr_processed:
                _t = asyncio.create_task(on_vad_end())
                self._bg_tasks.add(_t)
                _t.add_done_callback(self._bg_tasks.discard)

        pre_ws = None
        pre_wrapper = None
        pre_time = self.runtime._pre_asr_time
        self.runtime._pre_asr_time = 0

        if self.asr_client:
            try:
                pre_ws, pre_wrapper = self.asr_client.take_pre_ws()
            except Exception as e:
                logger.debug(f"[Session] 取走预连接 WS 异常: {e}")

        if pre_ws and time.time() - pre_time > 25:
            logger.debug(f"[Session] ASR 预连接已过期 ({time.time() - pre_time:.0f}s)，丢弃")
            try:
                _t = asyncio.create_task(self._safe_close_ws(pre_ws))
                self._bg_tasks.add(_t)
                _t.add_done_callback(self._bg_tasks.discard)
            except Exception as e:
                logger.debug(f"[Session] 关闭过期预连接 WS 异常: {e}")
            pre_ws = None
            pre_wrapper = None

        self.runtime.asr_task = asyncio.create_task(
            self._asr_streaming_loop(
                on_text, _vad_cb,
                self.runtime.asr_stop_event,
                pre_ws, pre_wrapper,
            )
        )
        logger.info(f"[Session:{self.session_id}] ASR 流式识别已启动")

    async def _connect_asr_ws(self, url: str, headers: dict):
        """创建 ASR WebSocket 连接"""
        import websockets as _websockets
        # 向下游 ASR 服务传播 trace_id（从 contextvar 读取，WS 日志已注入）
        _asr_headers = dict(headers) if headers else {}
        try:
            _tid = trace_id_var.get()
            if _tid:
                _asr_headers["X-Trace-Id"] = _tid
        except Exception:
            pass
        return await _websockets.connect(
            url,
            additional_headers=_asr_headers,
            max_size=self._WS_MAX_SIZE,
            ping_interval=self._WS_PING_INTERVAL,
        )

    async def _asr_streaming_loop(self, on_text, vad_end_callback, stop_event, pre_ws=None, pre_wrapper=None):
        import json as _json
        import struct as _struct
        import websockets as _websockets
        from websockets.exceptions import ConnectionClosed

        asr_client = self.asr_client
        audio_queue = self.runtime.audio_queue

        ws = pre_ws
        own_ws = pre_ws is None
        pool_wrapper = pre_wrapper
        send_done = False
        need_binary_protocol = getattr(asr_client, 'binary_protocol', False)
        reconnect_lock = asyncio.Lock()
        reconnect_event = asyncio.Event()
        reconnect_event.set()
        reconnect_result = {"success": False, "new_ws": None, "new_wrapper": None}

        async def handle_reconnect():
            nonlocal ws, own_ws, pool_wrapper
            reconnect_event.clear()
            reconnect_result["success"] = False
            reconnect_result["new_ws"] = None
            reconnect_result["new_wrapper"] = None
            try:
                logger.warning("[ASR] 池连接失效，自动重建新连接...")
                try:
                    await ws.close()
                except Exception as e:
                    logger.debug(f"[ASR] 关闭失效连接异常: {e}")
                if pool_wrapper and hasattr(asr_client, 'get_pool'):
                    pool = asr_client.get_pool()
                    if pool:
                        try:
                            await pool.release(pool_wrapper)
                        except Exception as ex:
                            logger.debug(f"[ASR] 归还失效连接异常: {ex}")
                        pool_wrapper = None
                headers = asr_client._get_headers()
                new_ws = await self._connect_asr_ws(
                    asr_client._ws_url if hasattr(asr_client, '_ws_url') else asr_client._build_url(),
                    headers,
                )
                if need_binary_protocol:
                    success = await asr_client.init_connection(new_ws)
                    if not success:
                        logger.error("[ASR] 重建新连接后初始化失败")
                        return
                reconnect_result["success"] = True
                reconnect_result["new_ws"] = new_ws
                ws = new_ws
                own_ws = True
                logger.info("[ASR] 新连接已建立，继续发送音频")
            except Exception as e:
                logger.error(f"[ASR] 重建连接失败: {e}")
            finally:
                reconnect_event.set()

        async def send_audio():
            nonlocal send_done, ws, own_ws, pool_wrapper

            audio_sent = 0
            audio_buffer = bytearray()
            # 性能优化：首个音频块使用更小缓冲（3200B=100ms），让 ASR 更快开始识别
            # 后续块恢复正常大小（6400B=200ms）以平衡网络开销
            target_chunk_size = 6400 if need_binary_protocol else 0
            first_chunk_size = 3200 if need_binary_protocol else 0
            first_chunk_logged = False

            while not send_done and not stop_event.is_set():
                try:
                    audio_data = await asyncio.wait_for(audio_queue.get(), timeout=0.5)
                    if stop_event.is_set():
                        break
                    if audio_data is None:
                        if need_binary_protocol and ws:
                            try:
                                end_request = asr_client._make_header(message_type=2, flags=2)
                                await ws.send(end_request)
                                logger.info("[ASR] 发送火山ASR音频结束标记")
                            except Exception as e:
                                logger.debug(f"发送火山ASR结束标记失败: {e}")
                        elif not need_binary_protocol and ws:
                            try:
                                await ws.send(b"")
                                logger.info("[ASR] 发送腾讯ASR音频结束标记")
                            except Exception as e:
                                logger.debug(f"发送腾讯ASR结束标记失败: {e}")
                        break
                    if ws:
                        try:
                            if need_binary_protocol:
                                audio_buffer.extend(audio_data)
                                # 首个块用小缓冲快速发送，后续块用正常缓冲
                                current_chunk_size = first_chunk_size if not first_chunk_logged else target_chunk_size
                                while len(audio_buffer) >= current_chunk_size:
                                    chunk = bytes(audio_buffer[:current_chunk_size])
                                    del audio_buffer[:current_chunk_size]
                                    await asr_client.send_audio_data(ws, chunk)
                                    audio_sent += len(chunk)
                                    if not first_chunk_logged:
                                        first_chunk_logged = True
                                        logger.info(f"[ASR] 首个音频块已发送: {len(chunk)} bytes, 总计: {audio_sent} bytes")
                                    elif audio_sent % (target_chunk_size * 20) == 0:
                                        logger.debug(f"[ASR] 已发送音频数据: {audio_sent} bytes")
                                    # 首块发送后切换到正常大小
                                    current_chunk_size = target_chunk_size
                            else:
                                await ws.send(audio_data)
                                audio_sent += len(audio_data)
                                if not first_chunk_logged:
                                    first_chunk_logged = True
                                    logger.info(f"[ASR] 首个音频块已发送: {len(audio_data)} bytes")
                                elif audio_sent % 4096 == 0:
                                    logger.debug(f"已发送音频数据: {audio_sent} bytes")
                        except Exception as e:
                            logger.info(f"ASR send_audio 失败: {e}")
                            break
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.info(f"ASR send_audio 异常: {e}")
                    break

            if audio_sent > 0:
                logger.info(f"[ASR] send_audio 结束, 共发送 {audio_sent} bytes")
            else:
                logger.warning(f"[ASR] send_audio 结束, 未发送任何音频数据!")

        async def recv_audio():
            nonlocal ws, send_done, own_ws, pool_wrapper
            first_message = True
            reconnect_attempts = 0
            max_reconnect = 2
            logger.info("[ASR] recv_audio 启动")
            while not send_done and not stop_event.is_set():
                try:
                    response = await asyncio.wait_for(ws.recv(), timeout=10.0)
                    logger.info(f"[ASR] 收到响应: {len(response) if isinstance(response, bytes) else response[:200] if isinstance(response, str) else type(response).__name__}")

                    if need_binary_protocol:
                        result = asr_client.parse_response(response)
                        if result is None:
                            if isinstance(response, bytes) and b"Timeout" in response:
                                logger.error("[ASR] 检测到超时错误，尝试重新连接...")
                                if not reconnect_event.is_set():
                                    await reconnect_event.wait()
                                    continue
                                if reconnect_attempts >= max_reconnect:
                                    logger.error("[ASR] 重新连接次数已达上限，停止")
                                    break
                                reconnect_attempts += 1
                                _t = asyncio.create_task(handle_reconnect())
                                self._bg_tasks.add(_t)
                                _t.add_done_callback(self._bg_tasks.discard)
                                await reconnect_event.wait()
                                if reconnect_result["success"]:
                                    reconnect_attempts = 0
                                continue
                            logger.debug(f"[ASR] parse_response 返回 None, raw={response[:100] if isinstance(response, (bytes, str)) else response}")
                            continue
                        text = result.get("text", "")
                        is_final = result.get("is_final", False)
                        if text:
                            logger.info(f"ASR 识别: {text}")
                        on_text(text)
                        if is_final:
                            logger.info("ASR 识别完成")
                            send_done = True
                            try:
                                if vad_end_callback and not stop_event.is_set():
                                    logger.info("[ASR] 调用 vad_end_callback 触发 LLM 流程")
                                    cb_result = vad_end_callback()
                                    if asyncio.iscoroutine(cb_result):
                                        await cb_result
                            except Exception as e:
                                logger.error(f"[ASR] vad_end_callback 异常: {e}")
                            break
                        if stop_event.is_set():
                            logger.info("[ASR] 检测到停止信号，退出recv_audio")
                            send_done = True
                            break
                    else:
                        result = _json.loads(response)
                        logger.debug(f"ASR 响应: {response}")

                        if first_message and not own_ws and result.get("code") != 0:
                            first_message = False
                            error_msg = result.get("message", "")
                            if "未发送音频" in error_msg or "timeout" in error_msg.lower():
                                logger.error(f"预连接 WS 已超时，尝试重连: {error_msg}")
                                try:
                                    await ws.close()
                                except Exception as e:
                                    logger.debug(f"[ASR] 关闭超时预连接 WS 异常: {e}")
                                enable_pool = getattr(asr_client, '_enable_pool', False)
                                if enable_pool and pool_wrapper and hasattr(asr_client, 'get_pool'):
                                    pool = asr_client.get_pool()
                                    if pool:
                                        await pool.release(pool_wrapper)
                                        pool_wrapper = None
                                if hasattr(asr_client, '_get_headers'):
                                    headers = asr_client._get_headers()
                                    url = asr_client._build_url()
                                    ws = await self._connect_asr_ws(url, headers)
                                else:
                                    url = asr_client._build_url()
                                    ws = await _websockets.connect(url, max_size=self._WS_MAX_SIZE)
                                own_ws = True
                                logger.info("ASR WebSocket 重连成功")
                                continue
                        first_message = False

                        if result.get("code") != 0:
                            logger.error(f"ASR 错误: {result.get('message', 'Unknown')}")
                            send_done = True
                            break
                        if result.get("result"):
                            text_data = result["result"]
                            text = text_data.get("voice_text_str", "") if isinstance(text_data, dict) else str(text_data)
                            if text:
                                logger.info(f"ASR 识别: {text}")
                        on_text(text)
                        if result.get("is_final", False):
                            logger.info("ASR 识别完成")
                            send_done = True
                            break
                        if result.get("result", {}).get("slice_type") == 2:
                            send_done = True
                            vad_end_callback()
                            break
                except asyncio.TimeoutError:
                    if not send_done and not stop_event.is_set():
                        logger.debug("[ASR] recv 等待超时(10s)，继续等待...")
                        continue
                    break
                except ConnectionClosed:
                    logger.info("[ASR] 连接已关闭")
                    break
                except Exception as e:
                    logger.error(f"ASR 接收异常: {e}")
                    send_done = True
                    break

        # 业务指标：ASR 请求计时起点
        _asr_track_start = time.time()
        _asr_track_status = "success"
        try:
            if own_ws:
                enable_pool = getattr(asr_client, '_enable_pool', False)
                if enable_pool and pool_wrapper and hasattr(asr_client, 'get_pool'):
                    pool = asr_client.get_pool()
                    if pool:
                        try:
                            wrapped = await pool.acquire(timeout=10.0)
                            ws = wrapped.connection
                            pool_wrapper = wrapped
                            logger.info("ASR WebSocket 已连接 (pool)")
                        except Exception as e:
                            logger.error(f"ASR 从池获取连接失败: {e}")
                            if hasattr(asr_client, '_get_headers'):
                                headers = asr_client._get_headers()
                                url = asr_client._build_url()
                                ws = await self._connect_asr_ws(url, headers)
                            else:
                                url = asr_client._build_url()
                                ws = await _websockets.connect(url, max_size=self._WS_MAX_SIZE)
                            own_ws = True
                            pool_wrapper = None
                            logger.info("ASR WebSocket 已连接")
                else:
                    if hasattr(asr_client, '_get_headers'):
                        headers = asr_client._get_headers()
                        url = asr_client._build_url()
                        logger.debug(f"ASR URL: {url[:80]}...")
                        ws = await self._connect_asr_ws(url, headers)
                    else:
                        url = asr_client._build_url()
                        logger.debug(f"ASR URL: {url[:80]}...")
                        ws = await _websockets.connect(url, max_size=self._WS_MAX_SIZE)
                    logger.info("ASR WebSocket 已连接")
            else:
                logger.debug("使用预连接的 ASR WebSocket")

            if need_binary_protocol:
                logger.info("[ASR] 发送 config 初始化会话...")
                init_success = False
                try:
                    init_success = await asr_client.init_connection(ws)
                except Exception as e:
                    logger.error(f"[ASR] config 初始化异常: {e}")

                if not init_success:
                    logger.warning("[ASR] config 初始化失败，尝试创建新连接")
                    try:
                        await ws.close()
                    except Exception as e:
                        logger.debug(f"[ASR] 关闭初始化失败连接异常: {e}")
                    if pool_wrapper and hasattr(asr_client, 'get_pool'):
                        pool = asr_client.get_pool()
                        if pool:
                            try:
                                await pool.release(pool_wrapper)
                            except Exception as e:
                                logger.debug(f"[ASR] 归还失效连接池异常: {e}")
                            pool_wrapper = None
                    try:
                        headers = asr_client._get_headers()
                        new_ws = await self._connect_asr_ws(
                            asr_client._ws_url if hasattr(asr_client, '_ws_url') else asr_client._build_url(),
                            headers,
                        )
                        init_success = await asr_client.init_connection(new_ws)
                        if init_success:
                            ws = new_ws
                            own_ws = True
                            pool_wrapper = None
                            logger.info("[ASR] 新连接 config 初始化成功")
                        else:
                            try:
                                await new_ws.close()
                            except Exception as e:
                                logger.debug(f"[ASR] 关闭新连接异常: {e}")
                            logger.error("[ASR] 新连接 config 初始化也失败，放弃")
                            return
                    except Exception as e2:
                        logger.error(f"[ASR] 创建新连接失败: {e2}")
                        return
                else:
                    logger.info("[ASR] config 初始化成功，会话已就绪")

            send_task = asyncio.create_task(send_audio())
            recv_task = asyncio.create_task(recv_audio())
            stop_waiter = asyncio.create_task(stop_event.wait())

            logger.info(f"[ASR] 任务已创建，stop_event.is_set()={stop_event.is_set()}")

            try:
                done, pending = await asyncio.wait([send_task, recv_task, stop_waiter], return_when=asyncio.FIRST_COMPLETED)
                send_done = True
                logger.info(f"[ASR] 有任务完成，完成的数量: {len(done)}, 等待中的数量: {len(pending)}")
                for t in pending:
                    t.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                await asyncio.gather(*done, return_exceptions=True)

                if stop_waiter in done and ws:
                    try:
                        await ws.close()
                    except Exception as e:
                        logger.debug(f"[ASR] 停止时关闭 WS 异常: {e}")
            except Exception as e:
                _asr_track_status = "error"
                logger.error(f"ASR 任务执行异常: {e}")
        except Exception as e:
            _asr_track_status = "error"
            logger.error(f"ASR 流式识别异常: {e}")
        finally:
            send_done = True
            enable_pool = getattr(asr_client, '_enable_pool', False)
            if enable_pool and pool_wrapper and hasattr(asr_client, 'get_pool'):
                pool = asr_client.get_pool()
                if pool:
                    try:
                        await pool.release(pool_wrapper)
                        logger.debug("ASR 连接已归还池")
                    except Exception as e:
                        logger.debug(f"ASR 归还连接池异常: {e}")
            elif ws and (not pre_ws or stop_event.is_set()):
                try:
                    await ws.close()
                except Exception as e:
                    logger.debug(f"[ASR] finally 关闭 WS 异常: {e}")

            # 业务指标：ASR 请求结果与耗时
            try:
                _asr_provider = "unknown"
                try:
                    _cfg = getattr(asr_client, "config", None) or {}
                    _asr_provider = _cfg.get("provider", "unknown") or "unknown"
                except Exception:
                    pass
                get_metrics().track_asr_request(_asr_provider, _asr_track_status, time.time() - _asr_track_start)
            except Exception:
                pass

    async def pre_connect_asr(self):
        if not self.asr_client:
            return
        try:
            if hasattr(self.asr_client, "pre_connect"):
                ws = await self.asr_client.pre_connect()
                if ws:
                    self.runtime.pre_asr_ws = ws
                    self.runtime._pre_asr_time = time.time()
                    logger.info(f"[Session:{self.session_id}] ASR 预连接成功")
        except Exception as e:
            logger.debug(f"[Session:{self.session_id}] ASR 预连接失败: {e}")

    def cancel_pre_asr(self):
        if self.runtime.pre_asr_ws:
            try:
                _t = asyncio.create_task(self._safe_close_ws(self.runtime.pre_asr_ws))
                self._bg_tasks.add(_t)
                _t.add_done_callback(self._bg_tasks.discard)
            except Exception as e:
                logger.debug(f"[Session] 取消预连接 ASR 异常: {e}")
        self.runtime.pre_asr_ws = None
        self.runtime._pre_asr_time = 0

    async def _safe_close_ws(self, ws):
        try:
            await ws.close()
        except Exception as e:
            logger.debug(f"[Session] 安全关闭 WS 异常: {e}")

    def stop_asr(self):
        if self.runtime.asr_stop_event:
            self.runtime.asr_stop_event.set()
        if self.runtime.asr_task and not self.runtime.asr_task.done():
            self.runtime.asr_task.cancel()
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            self._watchdog_task = None
        if self.runtime.audio_queue:
            while not self.runtime.audio_queue.empty():
                try:
                    self.runtime.audio_queue.get_nowait()
                    self.runtime.audio_queue.task_done()
                except asyncio.QueueEmpty:
                    break
        self.runtime.asr_task = None
        self.runtime.audio_queue = None
        self.runtime.asr_stop_event = None

    async def drain_asr(self):
        if self.runtime.audio_queue:
            with suppress(asyncio.QueueFull):
                self.runtime.audio_queue.put_nowait(None)
        self.stop_asr()

    def can_queue_audio(self):
        return (
            self.runtime.asr_task is not None
            and not self.runtime.asr_task.done()
            and self.runtime.audio_queue is not None
            and not self.runtime.asr_processed
        )

    async def queue_audio(self, data: bytes):
        if self.runtime.audio_queue and not self.runtime.asr_processed:
            await self.runtime.audio_queue.put(data)
            qsize = self.runtime.audio_queue.qsize()
            # 仅在队列积压时记录（正常消费时 qsize=0-1），避免每秒 60+ 行日志阻塞事件循环
            if qsize >= 10:
                logger.debug(f"[Session:{self.session_id}] 音频积压: 队列长度: {qsize}")

    async def run_pipeline(self, iat_text: str):
        """运行完整Pipeline"""
        self.cancel_event.clear()
        from src.use_cases.pipeline import PipelineConfig
        pipeline_config = PipelineConfig(client_max_buffer=self.client_max_buffer)
        pipeline = ConversationPipeline(
            llm_processor=self.llm_processor,
            tts_processor=self.tts_processor,
            channel=self.channel,
            fsm=self.fsm,
            voice_generator=self.voice_generator,
            conversation_memory=self.conversation_memory,
            user_config=self.user_config,
            cancel_event=self.cancel_event,
            device_id=self.device_id,
            ltm_service=self.ltm_service,
            config=pipeline_config,
            precomputed_skill_catalog=self._precomputed_skill_catalog,
        )
        self._current_pipeline = pipeline
        try:
            result = await pipeline.run(iat_text)
            return result
        except Exception as e:
            logger.error(f"[Session:{self.session_id}] Pipeline 异常: {e}")
            return None
        finally:
            self._current_pipeline = None

    async def interrupt(self):
        logger.info(f"[Session:{self.session_id}] 执行硬中断...")
        self.cancel_event.set()

        if self._current_pipeline is not None:
            pipeline = self._current_pipeline
            for t in pipeline._tasks:
                if not t.done():
                    t.cancel()
            pipeline._tasks.clear()
            logger.info(f"[Session:{self.session_id}] 已取消当前 Pipeline 的所有 tasks")

        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            self._watchdog_task = None

        self.stop_asr()
        self.queues.clear_all()
        self.splitter.reset()

        self.runtime.reset()

        await self.set_tts_playing(False)
        self.tts_playback_done.set()
        self.tts_audio_ended.set()

        await self.channel.send_bytes(self.voice_generator.make_end_frame("0001"))
        try:
            await self.channel.send_json({"type": "session_status", "status": "tts_real_end"})
        except Exception as e:
            logger.debug(f"[Session:{self.session_id}] 发送中断结束状态失败: {e}")

        logger.info(f"[Session:{self.session_id}] 硬中断完成")

    async def send_session_end(self):
        self.runtime.asr_processed = True
        await self.channel.send_json({"type": "session_status", "status": "iat_end"})
        await asyncio.sleep(0.03)
        await self.drain_asr()
        await self.fsm.set(SessionState.IDLE)
        await self.channel.send_json({"type": "session_status", "status": "session_end"})
        await asyncio.sleep(0.1)
        await self.channel.send_text("session_end")
        logger.info(f"[Session:{self.session_id}] 会话结束消息已发送")

    async def start_auto_conversation(self):
        """启动完整自动对话循环：ASR → Pipeline → 下一轮 ASR"""
        if self._closed:
            return

        await self.fsm.set(SessionState.ASR)
        await self.pre_connect_asr()

        def on_text(text):
            # 空文本（ASR 结束帧）不覆盖已有识别结果（同 ws_session_handler.on_asr_text 修复）
            if text:
                self.runtime.asr_full_text = text
                self.runtime.asr_last_result_time = time.time()

        async def _on_vad_end_auto():
            if self.runtime.asr_processed:
                return
            self.runtime.asr_processed = True

            await self.channel.send_json({"type": "session_status", "status": "iat_end"})
            await asyncio.sleep(0.03)

            text = self.runtime.asr_full_text
            logger.info(f"[Session:{self.session_id}] ASR 最终: {text}")
            await self.drain_asr()

            if not text.strip():
                await self.send_session_end()
                return

            try:
                await self.channel.send_json({"type": "instruct", "command_id": "on_iat_cb", "data": text})
                await asyncio.sleep(0.03)
            except Exception as e:
                logger.debug(f"[Session:{self.session_id}] 发送 on_iat_cb 失败: {e}")

            result = await self.run_pipeline(text)

            if self._closed or self.cancel_event.is_set():
                self.cancel_event.clear()
                return

            if result and getattr(result, 'stop_pipeline', False):
                logger.info(f"[Session:{self.session_id}] Pipeline 被 StopPipeline 终止，不启动下一轮")
                await self.fsm.set(SessionState.IDLE)
                return

            await self._start_next_cycle()

        await self.start_asr(on_text, _on_vad_end_auto)
        await self.channel.send_json({"type": "session_status", "status": "iat_start"})
        logger.info(f"[Session:{self.session_id}] 自动对话循环已启动")
        await self.start_watchdog(_on_vad_end_auto)

    async def _start_next_cycle(self):
        await self.fsm.set(SessionState.ASR)
        if self.runtime.asr_processed:
            self.runtime.asr_processed = False
        await self.pre_connect_asr()

        def on_text(text):
            # 空文本（ASR 结束帧）不覆盖已有识别结果（同 ws_session_handler.on_asr_text 修复）
            if text:
                self.runtime.asr_full_text = text
                self.runtime.asr_last_result_time = time.time()

        async def _on_vad_end_cycle():
            if self.runtime.asr_processed:
                return
            self.runtime.asr_processed = True

            await self.channel.send_json({"type": "session_status", "status": "iat_end"})
            await asyncio.sleep(0.03)

            text = self.runtime.asr_full_text
            await self.drain_asr()

            if not text.strip():
                await self.send_session_end()
                return

            try:
                await self.channel.send_json({"type": "instruct", "command_id": "on_iat_cb", "data": text})
                await asyncio.sleep(0.03)
            except Exception as e:
                logger.debug(f"[Session:{self.session_id}] 发送 on_iat_cb 失败: {e}")

            result = await self.run_pipeline(text)

            if self._closed or self.cancel_event.is_set():
                return

            if result and getattr(result, 'stop_pipeline', False):
                logger.info(f"[Session:{self.session_id}] Pipeline 被 StopPipeline 终止，不启动下一轮")
                await self.fsm.set(SessionState.IDLE)
                return

            await self._start_next_cycle()

        await self.start_asr(on_text, _on_vad_end_cycle)
        await self.channel.send_json({"type": "session_status", "status": "iat_start"})
        logger.info(f"[Session:{self.session_id}] 下一轮 ASR 已启动")
        await self.start_watchdog(_on_vad_end_cycle)

    async def start_watchdog(self, on_vad_end):
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()

        async def _watchdog():
            try:
                max_asr_duration = 30.0
                while not self.runtime.asr_processed:
                    await asyncio.sleep(0.2)
                    if self.fsm.get() != SessionState.ASR:
                        continue
                    now = time.time()
                    lat = self.runtime.asr_last_audio_time
                    lr = self.runtime.asr_last_result_time
                    st = self.runtime.asr_start_time

                    if st and lr is None and now - st > self.no_speech_timeout:
                        # ASR 一直未产出任何识别结果 → 用户没有说话（mic 一直在传底噪音频，
                        # asr_last_audio_time 会持续更新，不能用它判断"没说话"）。
                        # 注意：用户开口后火山 ASR 首结果一般 <2s，5s 超时足以覆盖；
                        # 若个别情况下用户已开口但结果延迟，会走 30s max_asr_duration 兜底。
                        if lat is None:
                            logger.warning(
                                f"[Session:{self.session_id}] {self.no_speech_timeout}s 未收到音频"
                            )
                        else:
                            logger.warning(
                                f"[Session:{self.session_id}] {self.no_speech_timeout}s 无有效语音"
                            )
                        await self.send_session_end()
                        return

                    if lr and now - lr > self.silence_timeout and not self.runtime.asr_processed:
                        await on_vad_end()
                        return

                    if st and now - st > max_asr_duration:
                        logger.warning(
                            f"[Session:{self.session_id}] ASR 运行超过 {max_asr_duration}s，强制停止"
                        )
                        self.stop_asr()
                        # 兜底：强制停止后必须通知设备结束会话，否则设备会一直停在"聆听中"
                        await self.send_session_end()
                        return
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"[Session:{self.session_id}] Watchdog 异常: {e}")

        self._watchdog_task = asyncio.create_task(_watchdog())

    async def close(self):
        if self._closed:
            return
        self._closed = True

        logger.info(f"[Session:{self.session_id}] 开始关闭...")

        self.cancel_event.set()

        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()

        # 清理预连接的 ASR WebSocket
        self.cancel_pre_asr()

        self.stop_asr()
        self.queues.clear_all()
        self.runtime.reset()

        await self.set_tts_playing(False)
        self.tts_playback_done.set()
        self.tts_audio_ended.set()
        self._wake_audio_played.set()  # 唤醒 _do_wake_start 防止卡死

        self.conversation_memory._messages.clear()

        # 业务指标：会话关闭，记录会话时长
        try:
            get_metrics().track_session_closed(time.time() - self.session_start_time)
        except Exception:
            pass

        logger.info(f"[Session:{self.session_id}] 已关闭")


__all__ = ["Session", "SessionRuntime"]
