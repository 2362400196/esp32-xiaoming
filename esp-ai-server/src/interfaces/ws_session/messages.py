"""WS 会话主消息循环：接收并分发设备消息。"""
from __future__ import annotations

import asyncio
import json
import time

from starlette.websockets import WebSocketDisconnect

from src.domain.entities import SessionState
from src.infrastructure.logging import get_logger
from src.infrastructure.monitoring import get_metrics
from src.infrastructure.task_manager import background_task
from src.infrastructure.web import get_device_registry
from src.use_cases.sdk.events import EVENT_SESSION_START, publish
from src.use_cases.session import AUDIO_QUEUE_MAX_SIZE

from .helpers import _get_wake_enable_audio

logger = get_logger(__name__)


class MessageLoopMixin:
    """设备消息主循环。"""

    async def run(self) -> None:
        """主消息循环 - 接收并分发设备消息

        对应原 handle_websocket 中 try 块内的 while 主循环。
        """
        session = self.session
        fsm = self.fsm
        channel = self.channel
        websocket = self.websocket
        device_key = self.device_key
        tool_mgr = self.tool_mgr
        asr_client = self.asr_client
        settings = self.settings

        while not session._closed:
            try:
                message = await websocket.receive()
                if isinstance(message, dict):
                    msg_type = message.get("type", "")
                    if msg_type in ("websocket.disconnect", "websocket.close"):
                        logger.info(f"[WS] Received disconnect: {msg_type}")
                        break

                    if "text" in message:
                        try:
                            data = json.loads(message["text"])
                        except Exception:
                            continue
                        t = data.get("type", "")
                        # 调试：记录所有设备消息
                        if t == "instruct":
                            logger.info(f"[WS] 收到 instruct: command_id={data.get('command_id')}")

                        # 业务指标：记录收到的 WebSocket 文本消息（按业务类型分类）
                        try:
                            get_metrics().track_ws_message_received(t or "unknown")
                        except Exception:
                            pass

                        if t == "ping":
                            channel.send_json_nowait({"type": "pong"})
                        elif t == "pong":
                            pass
                        elif t == "ota_progress":
                            progress = float(data.get("data", 0))
                            device_id_ota = data.get("device_id", device_key)
                            registry = get_device_registry()
                            if registry:
                                registry.update_ota_progress(device_key, progress)
                            logger.info(f"[OTA] 设备 {device_id_ota} 升级进度: {progress}%")
                        elif t == "ota_update_error":
                            device_id_ota = data.get("device_id", device_key)
                            registry = get_device_registry()
                            if registry:
                                registry.set_ota_updating(device_key, False)
                            logger.warning(f"[OTA] 设备 {device_id_ota} 升级失败")
                        elif t == "firmware_version":
                            fw_version = data.get("version", "")
                            registry = get_device_registry()
                            if registry and registry.has(device_key):
                                device = registry.resolve(device_key)
                                if device:
                                    device["firmware_version"] = fw_version
                                    logger.info(f"[WS] 设备 {device_key[:16]} firmware版本: {fw_version}")
                        elif t == "lua_result" or (t == "instruct" and data.get("command_id") == "lua_result"):
                            raw_data = data.get("data", "")
                            logger.info(f"[Lua] 设备返回结果: {raw_data[:200]}")
                            if tool_mgr and tool_mgr._pending_lua_future and not tool_mgr._pending_lua_future.done():
                                if isinstance(raw_data, str) and raw_data.startswith("error:"):
                                    tool_mgr._pending_lua_future.set_result(f"[Lua Error]\n{raw_data[6:]}")
                                elif isinstance(raw_data, str):
                                    tool_mgr._pending_lua_future.set_result(raw_data)
                                elif isinstance(raw_data, dict):
                                    output = raw_data.get("output", str(raw_data))
                                    success = raw_data.get("success", True)
                                    if success:
                                        tool_mgr._pending_lua_future.set_result(output)
                                    else:
                                        tool_mgr._pending_lua_future.set_result(f"[Lua Error]\n{output}")
                                tool_mgr._pending_lua_future = None
                        elif t == "device_state_result" or (t == "instruct" and data.get("command_id") == "device_state_result"):
                            # 设备状态查询回复（get_volume/get_brightness 内置工具）
                            raw_data = data.get("data", "")
                            logger.info(f"[WS] 设备状态回复: {raw_data[:200]}")
                            if tool_mgr and tool_mgr._pending_device_state_future and not tool_mgr._pending_device_state_future.done():
                                tool_mgr._pending_device_state_future.set_result(str(raw_data))
                                tool_mgr._pending_device_state_future = None
                        elif t == "instruct_ack" or (t == "instruct" and data.get("command_id") == "instruct_ack"):
                            # 设备指令 ack 确认（send_device_command_ack 等待的回执）
                            ack_data = data.get("data", "")
                            logger.info(f"[WS] 设备指令 ack: {ack_data}")
                            if (
                                tool_mgr
                                and tool_mgr._pending_command_ack_future
                                and not tool_mgr._pending_command_ack_future.done()
                            ):
                                tool_mgr._pending_command_ack_future.set_result(str(ack_data))
                                tool_mgr._pending_command_ack_future = None
                        elif t == "start":
                            # 固件 VAD 实时打断带的标记：用户的话正在说，
                            # 唤醒问候语（"我在呢"）会让 iat_start 晚 1.4~2.1 秒，
                            # 这半句话全丢——打断必须直接开麦。
                            is_barge_in = data.get("source") == "vad_barge_in"
                            if session._waiting_wake_audio:
                                # 唤醒提示音播放中设备又发来 start = AEC 实时打断。
                                # 提示音被固件 audio_spk_hard_stop 掐断后不会回
                                # client_out_audio_over，_do_wake_start 会白等满 10s
                                # 看门狗，期间 iat_start 不下发、麦克风不开（表现为
                                # "打断后麦克风失灵"）。这条 start 本身就是
                                # "提示音不用再等了"的确认，放行在途唤醒流程直接进 ASR。
                                logger.info(f"[Session:{session.session_id}] Start during wake prompt: releasing wake audio wait")
                                session._wake_audio_played.set()
                                continue
                            if self.wake_start_task and not self.wake_start_task.done() and not is_barge_in:
                                logger.info(f"[Session:{session.session_id}] Duplicate start ignored: wake flow already running")
                                continue

                            if fsm.get() == SessionState.ASR:
                                logger.info(f"[Session:{session.session_id}] Duplicate start during ASR: resetting session and restarting")
                                # 结束当前 ASR 会话，重置 FSM 到 IDLE
                                await session.send_session_end()
                                # 继续执行下面的正常 start 流程，重新开始会话

                            logger.info("[WS] Received start command")
                            # 新一轮语音会话开始 → 发布事件（publish 内部容错，不阻塞消息循环）
                            publish(EVENT_SESSION_START, device_key=self.device_key)

                            # 标记新一轮唤醒流程进行中：旧 pipeline 被取消时，
                            # _on_tts_complete 不应再启动下一轮 ASR（由 _do_wake_start 负责）
                            self._new_wake_pending = True

                            # 立即清除唤醒音频事件，防止上一轮迟到的 client_out_audio_over 触发
                            session._wake_audio_played.clear()

                            # 取消连接问候音频任务，避免其 session_end 与真实会话冲突
                            if self.connect_audio_task and not self.connect_audio_task.done():
                                logger.info(f"[Session:{session.session_id}] Cancelling connect audio on start")
                                self.connect_audio_task.cancel()
                                self.connect_audio_task = None

                            # 取消旧的 pipeline 任务
                            if self.pipeline_task and not self.pipeline_task.done():
                                logger.info(f"[Session:{session.session_id}] Cancelling old pipeline on new start")
                                # 必须先置位 cancel_event 再 cancel：本轮的唤醒提示音/新 pipeline
                                # 与旧 pipeline 共用 SID_TTS("0010") 音频流，旧 pipeline 退出时
                                # 补发的 end_frame+tts_real_end 会把刚打开的新流立刻关掉
                                # （表现为打断后"TTS 瞬间播完 + 多句叠播"）。
                                # pipeline.py 的 cancel_event 分支正是为此存在，
                                # 但只有 interrupt()/send_session_end() 会置位，
                                # tts_playing=False 的打断路径漏掉了它。
                                # 下一轮 run_pipeline 开头会 clear()，不会污染后续轮次。
                                session.cancel_event.set()
                                self.pipeline_task.cancel()
                                self.pipeline_task = None

                            if session.tts_playing:
                                logger.info(f"[Session:{session.session_id}] Interrupting TTS")
                                if self.tts_done_waiter and not self.tts_done_waiter.done():
                                    self.tts_done_waiter.cancel()
                                    self.tts_done_waiter = None
                                await session.interrupt()
                                try:
                                    await asyncio.wait_for(session.tts_playback_done.wait(), timeout=0.5)
                                except asyncio.TimeoutError:
                                    pass
                            else:
                                if self.tts_done_waiter and not self.tts_done_waiter.done():
                                    self.tts_done_waiter.cancel()
                                    self.tts_done_waiter = None

                            await channel.send_json({"type": "session_start", "session_id": "0001"})
                            session.tts_playback_done.set()
                            session.tts_audio_ended.set()
                            session.tts_playback_done.clear()
                            session.tts_audio_ended.clear()

                            if asr_client:
                                session.cancel_pre_asr()
                                background_task(session.pre_connect_asr(), name="pre_connect_asr")

                            if _get_wake_enable_audio(settings, self.user_config) and not is_barge_in:
                                # 取消旧的唤醒任务，避免多个 task 竞争 _waiting_wake_audio 标志
                                if self.wake_start_task and not self.wake_start_task.done():
                                    self.wake_start_task.cancel()
                                self.wake_start_task = background_task(self._do_wake_start(), name="wake_start")
                            else:
                                if is_barge_in:
                                    # 打断可能落在唤醒问候语的等待窗口里：那个工作中的
                                    # _do_wake_start 会把问候语放完才开麦，这里直接掐掉，
                                    # 由本分支立刻进 ASR。
                                    if self.wake_start_task and not self.wake_start_task.done():
                                        logger.info(f"[Session:{session.session_id}] Barge-in cancels in-flight wake start")
                                        self.wake_start_task.cancel()
                                        self.wake_start_task = None
                                    session._waiting_wake_audio = False
                                    logger.info(f"[Session:{session.session_id}] Barge-in start: 跳过唤醒问候语，立刻开麦")
                                # 无唤醒音频：直接启动 ASR，唤醒流程标志在此清除
                                self._new_wake_pending = False
                                await fsm.set(SessionState.ASR)
                                self._start_asr_session()
                                await asyncio.sleep(0.1)
                                await channel.send_json({"type": "session_status", "status": "iat_start"})
                                logger.info(f"[Session:{session.session_id}] iat_start sent (no wake audio)")

                        elif t == "iat_end":
                            if not session.runtime.asr_processed:
                                background_task(self.on_vad_end(), name="on_vad_end")

                        elif t == "play_audio_ws_conntceed":
                            self.connect_audio_task = background_task(self._play_connect_audio(), name="play_connect_audio")
                            logger.info("[WS] Device ready")

                        elif t == "client_out_audio_over":
                            logger.info(f"[WS] Received client_out_audio_over, tts_playing={session.tts_playing}, fsm={fsm.get()}, waiting_wake={session._waiting_wake_audio}, tts_playback_done={session.tts_playback_done.is_set()}")
                            # 只在 _do_wake_start 正在等待唤醒音频完成时才 set _wake_audio_played
                            # 额外校验轮次号，防止上一轮迟到的 client_out_audio_over 串扰本轮唤醒
                            # 这解决了"第二次唤醒只播尾音"的问题
                            if (session._waiting_wake_audio
                                and not session._wake_audio_played.is_set()
                                and getattr(session, '_wake_audio_expected_round', 0) == getattr(session, '_wake_audio_round', 0)):
                                session._wake_audio_played.set()
                            # 播放完成上报必须对应一次已下发的音频（_pending_out_audio_over），
                            # 否则是迟到的/意外的上报——忽略之，防止误取消新一轮 pipeline
                            if not session._pending_out_audio_over:
                                logger.debug(f"[Session:{session.session_id}] 无进行中的音频播放，忽略此次 client_out_audio_over")
                                continue
                            session._pending_out_audio_over = False
                            session.tts_playback_done.set()
                            await session.set_tts_playing(False)
                            # 如果 pipeline 还在运行（如看门狗超时导致客户端提前结束），取消 pipeline
                            if self.pipeline_task and not self.pipeline_task.done():
                                logger.info(f"[Session:{session.session_id}] client_out_audio_over while pipeline still running, cancelling pipeline")
                                self.pipeline_task.cancel()
                            # 注意：收到 client_out_audio_over 表示客户端音频播放完成
                            # 此时应该检查 FSM 状态并准备下一轮 ASR
                            # 修复：不要因为 FSM 是 IDLE 就跳过，而是检查会话是否已关闭
                            if session._closed:
                                logger.info(f"[Session:{session.session_id}] Session is closed, skip next ASR")
                            elif fsm.get() == SessionState.IDLE:
                                logger.info(f"[Session:{session.session_id}] FSM is IDLE, but session not closed, checking if should start next ASR")
                                # 如果 FSM 是 IDLE 但会话未关闭，可能是 Pipeline 提前结束
                                # 尝试启动下一轮 ASR
                                if session.runtime.asr_processed and session.runtime.audio_queue is None:
                                    session.runtime.asr_processed = False
                                    session.runtime.audio_queue = asyncio.Queue(maxsize=AUDIO_QUEUE_MAX_SIZE)
                                    logger.info(f"[Session:{session.session_id}] TTS playback done, pre-created audio queue (IDLE state)")
                            elif session.runtime.asr_processed and session.runtime.audio_queue is None:
                                session.runtime.asr_processed = False
                                session.runtime.audio_queue = asyncio.Queue(maxsize=AUDIO_QUEUE_MAX_SIZE)
                                logger.info(f"[Session:{session.session_id}] TTS playback done, pre-created audio queue")

                        elif t == "client_out_audio_ing":
                            pass

                        elif t == "music_play_next":
                            # 设备音乐自然播放结束，请求下一首随机歌曲（自动续播）
                            logger.info(f"[WS] 收到 music_play_next，自动续播下一首随机歌曲")
                            if channel and self.tool_mgr:
                                # 在后台任务中执行，避免阻塞消息循环
                                async def _play_next():
                                    try:
                                        # 白名单检查：设备未启用 media_player 插件时不再直调插件，
                                        # 只发送 stop_music 让设备停止自动续播（安全修复）
                                        checker = getattr(self.tool_mgr, "_device_tool_allowed", None)
                                        if callable(checker) and not checker("play_music"):
                                            logger.info("[WS] 音乐插件未启用，跳过自动续播")
                                            await channel.send_json({
                                                "type": "instruct",
                                                "command_id": "stop_music",
                                            })
                                            return
                                        # 走正规工具调用（song/artist 留空即随机推荐，
                                        # 等价原 play_random_music_to_channel）；
                                        # play_music 成功发送后抛 StopPipeline，
                                        # 正常返回字符串说明音乐未成功发出 → 通知设备停止续播
                                        from src.use_cases.tools_system import StopPipeline
                                        try:
                                            result = await self.tool_mgr.call_tool("play_music", {"song": "", "artist": ""})
                                            logger.warning(f"[WS] 自动续播失败: {result}")
                                            await channel.send_json({
                                                "type": "instruct",
                                                "command_id": "stop_music",
                                            })
                                        except StopPipeline:
                                            logger.info("[WS] 自动续播已发送")
                                    except Exception as e:
                                        logger.error(f"[WS] 自动续播异常: {e}", exc_info=True)
                                # 通过 task_manager 执行，持有引用且异常有日志
                                background_task(_play_next(), name="music_play_next")
                            else:
                                logger.warning("[WS] music_play_next 但 channel/user_config 不可用")

                        elif t == "client_available_audio":
                            value = int(data.get("value", 10240))
                            await session.set_device_buffer(value)
                            if session._current_pipeline is not None:
                                await session._current_pipeline.set_device_buffer(value)
                            session.tts_drain_ack.set()

                        elif t == "session_stop":
                            logger.info(f"[WS] Session stop request: {data.get('session_id', 'unknown')}")
                            session.runtime.asr_processed = True
                            await session.drain_asr()
                            if session.tts_playing:
                                await session.interrupt()
                            await fsm.set(SessionState.IDLE)
                            await channel.send_json({"type": "session_stop_ack", "session_id": "0001"})

                    elif "bytes" in message:
                        # 业务指标：记录收到的 WebSocket 二进制（音频）消息
                        try:
                            get_metrics().track_ws_message_received("audio_bytes")
                        except Exception:
                            pass
                        if session.can_queue_audio():
                            audio_data = message["bytes"]
                            session.audio_processor.process_audio_chunk(audio_data)
                            session.runtime.asr_last_audio_time = time.time()
                            await session.queue_audio(audio_data)
                        elif fsm.get() == SessionState.IDLE:
                            pass
                        else:
                            logger.debug(f"[Session:{session.session_id}] Audio dropped: can_queue_audio=False, fsm={fsm.get()}, asr_task={'None' if session.runtime.asr_task is None else 'done' if session.runtime.asr_task.done() else 'running'}, audio_queue={'None' if session.runtime.audio_queue is None else 'ok'}, asr_processed={session.runtime.asr_processed}")

            except WebSocketDisconnect as e:
                logger.info(f"[WS] Client disconnected (code={e.code})")
                break
            except OSError as e:
                logger.warning(f"[WS] OS error: {type(e).__name__}: {e}")
                break
            except Exception as e:
                logger.error(f"[WS] Unknown error: {type(e).__name__}: {e}", exc_info=True)
                break

