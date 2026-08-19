"""
SessionFSM & WSChannel 单元测试

覆盖 src/use_cases/session_fsm.py:
- SessionFSM      : 带 transition guard 的状态机
- WSChannel       : WebSocket 双队列收发入口（_hi 高优先级 / _lo 低优先级）
- VALID_TRANSITIONS : 合法状态转换表

测试策略：
- asyncio_mode="auto"
- 使用本地 FakeWebSocket 模拟真实 websocket（不依赖网络）
- 覆盖正常状态转换、非法转换忽略、双队列优先级、send_loop 0.1s 轮询、
  clear_queue、interrupt_send_loop、close 等路径
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.domain.entities import SessionState
from src.use_cases.session_fsm import (
    VALID_TRANSITIONS,
    SessionFSM,
    WSChannel,
)


# ════════════════════════════════════════════════════════════
# 辅助：模拟 WebSocket
# ════════════════════════════════════════════════════════════
class FakeWebSocket:
    """模拟 starlette/FastAPI WebSocket 的发送接口"""

    def __init__(self, fail_on: str | None = None):
        self.sent_json: list[dict] = []
        self.sent_bytes: list[bytes] = []
        self.sent_text: list[str] = []
        self.fail_on = fail_on  # 指定某种 kind 触发发送异常
        self.closed = False

    async def send_json(self, data: dict):
        if self.fail_on == "json":
            raise RuntimeError("send_json failed")
        self.sent_json.append(data)

    async def send_bytes(self, data: bytes):
        if self.fail_on == "bytes":
            raise RuntimeError("send_bytes failed")
        self.sent_bytes.append(data)

    async def send_text(self, data: str):
        if self.fail_on == "text":
            raise RuntimeError("send_text failed")
        self.sent_text.append(data)

    async def close(self):
        self.closed = True


# ════════════════════════════════════════════════════════════
# VALID_TRANSITIONS 表
# ════════════════════════════════════════════════════════════
class TestValidTransitions:
    """合法状态转换表测试"""

    def test_idle_can_go_to_asr_and_tts(self):
        assert SessionState.ASR in VALID_TRANSITIONS[SessionState.IDLE]
        assert SessionState.TTS in VALID_TRANSITIONS[SessionState.IDLE]

    def test_asr_can_go_to_llm_and_idle(self):
        assert SessionState.LLM in VALID_TRANSITIONS[SessionState.ASR]
        assert SessionState.IDLE in VALID_TRANSITIONS[SessionState.ASR]

    def test_llm_can_go_to_tts_idle_asr(self):
        # LLM 可转 TTS（正常管线）、IDLE（超时/会话结束）、ASR（打断后直接续轮/唤醒）
        assert SessionState.TTS in VALID_TRANSITIONS[SessionState.LLM]
        assert SessionState.IDLE in VALID_TRANSITIONS[SessionState.LLM]
        assert SessionState.ASR in VALID_TRANSITIONS[SessionState.LLM]

    def test_tts_can_go_to_asr_and_idle(self):
        assert SessionState.ASR in VALID_TRANSITIONS[SessionState.TTS]
        assert SessionState.IDLE in VALID_TRANSITIONS[SessionState.TTS]

    def test_interrupted_not_in_table(self):
        # INTERRUPTED / CLOSED 不在转换表内（FSM 遇到时返回空列表）
        assert SessionState.INTERRUPTED not in VALID_TRANSITIONS
        assert SessionState.CLOSED not in VALID_TRANSITIONS


# ════════════════════════════════════════════════════════════
# SessionFSM
# ════════════════════════════════════════════════════════════
class TestSessionFSM:
    """SessionFSM 状态机测试"""

    def test_initial_state_idle(self):
        fsm = SessionFSM()
        assert fsm.state == SessionState.IDLE
        assert fsm.get() == SessionState.IDLE

    def test_is_busy_false_when_idle(self):
        fsm = SessionFSM()
        assert fsm.is_busy() is False

    async def test_set_same_state_noop(self):
        # 设置为当前状态应直接返回，不做任何变更
        fsm = SessionFSM()
        await fsm.set(SessionState.IDLE)
        assert fsm.state == SessionState.IDLE

    async def test_valid_transition_idle_to_asr(self):
        fsm = SessionFSM()
        await fsm.set(SessionState.ASR)
        assert fsm.state == SessionState.ASR
        assert fsm.is_busy() is True

    async def test_valid_transition_idle_to_tts(self):
        # IDLE -> TTS 是合法的（用于唤醒音频播放）
        fsm = SessionFSM()
        await fsm.set(SessionState.TTS)
        assert fsm.state == SessionState.TTS

    async def test_valid_transition_full_cycle(self):
        # IDLE -> ASR -> LLM -> TTS -> IDLE 完整循环
        fsm = SessionFSM()
        await fsm.set(SessionState.ASR)
        await fsm.set(SessionState.LLM)
        await fsm.set(SessionState.TTS)
        await fsm.set(SessionState.IDLE)
        assert fsm.state == SessionState.IDLE

    async def test_invalid_transition_ignored(self):
        # IDLE -> LLM 非法，应被忽略，状态不变
        fsm = SessionFSM()
        await fsm.set(SessionState.LLM)
        assert fsm.state == SessionState.IDLE

    async def test_llm_to_idle_valid(self):
        # LLM -> IDLE 合法（ASR 无语音超时/会话结束时归位，修复打断后状态卡死）
        fsm = SessionFSM()
        await fsm.set(SessionState.ASR)
        await fsm.set(SessionState.LLM)
        await fsm.set(SessionState.IDLE)
        assert fsm.state == SessionState.IDLE

    async def test_llm_to_asr_valid(self):
        # LLM -> ASR 合法（打断在 LLM 阶段后直接续轮）
        fsm = SessionFSM()
        await fsm.set(SessionState.ASR)
        await fsm.set(SessionState.LLM)
        await fsm.set(SessionState.ASR)
        assert fsm.state == SessionState.ASR

    async def test_invalid_transition_from_interrupted(self):
        # INTERRUPTED 不在表中，任何转换都被忽略
        fsm = SessionFSM()
        fsm.state = SessionState.INTERRUPTED
        await fsm.set(SessionState.IDLE)
        assert fsm.state == SessionState.INTERRUPTED

    async def test_invalid_transition_from_closed(self):
        fsm = SessionFSM()
        fsm.state = SessionState.CLOSED
        await fsm.set(SessionState.IDLE)
        assert fsm.state == SessionState.CLOSED

    async def test_concurrent_set_serialized_by_lock(self):
        # 多个协程并发 set，锁保证状态最终一致
        fsm = SessionFSM()
        await asyncio.gather(
            fsm.set(SessionState.ASR),
            fsm.set(SessionState.ASR),
            fsm.set(SessionState.ASR),
        )
        assert fsm.state == SessionState.ASR

    async def test_is_busy_true_when_asr(self):
        fsm = SessionFSM()
        await fsm.set(SessionState.ASR)
        assert fsm.is_busy() is True

    async def test_is_busy_false_when_back_to_idle(self):
        fsm = SessionFSM()
        await fsm.set(SessionState.ASR)
        await fsm.set(SessionState.IDLE)
        assert fsm.is_busy() is False

    async def test_tts_to_asr_valid(self):
        # TTS -> ASR 合法（连续对话）
        fsm = SessionFSM()
        await fsm.set(SessionState.TTS)
        await fsm.set(SessionState.ASR)
        assert fsm.state == SessionState.ASR

    async def test_asr_to_asr_noop(self):
        # ASR -> ASR 是相同状态，应 noop
        fsm = SessionFSM()
        await fsm.set(SessionState.ASR)
        await fsm.set(SessionState.ASR)
        assert fsm.state == SessionState.ASR


# ════════════════════════════════════════════════════════════
# WSChannel — 初始化与基础属性
# ════════════════════════════════════════════════════════════
class TestWSChannelInit:
    """WSChannel 初始化测试"""

    def test_defaults(self):
        ch = WSChannel()
        assert ch.websocket is None
        assert ch.connected is False
        assert ch._send_task is None
        assert ch._send_gen == 0
        # 双队列容量
        assert ch._hi.maxsize == 64
        assert ch._lo.maxsize == 500

    def test_send_queue_property_returns_hi(self):
        # send_queue 向后兼容，映射到高优先级队列 _hi
        ch = WSChannel()
        assert ch.send_queue is ch._hi

    def test_hi_and_lo_distinct(self):
        ch = WSChannel()
        assert ch._hi is not ch._lo


# ════════════════════════════════════════════════════════════
# WSChannel — 未连接时的发送方法
# ════════════════════════════════════════════════════════════
class TestWSChannelNotConnected:
    """未连接时 send_* 方法应静默丢弃"""

    async def test_send_json_when_not_connected(self):
        ch = WSChannel()
        # 不应抛异常，也不入队
        await ch.send_json({"type": "x"})
        assert ch._hi.empty()

    async def test_send_bytes_when_not_connected(self):
        ch = WSChannel()
        await ch.send_bytes(b"data")
        assert ch._lo.empty()

    async def test_send_text_when_not_connected(self):
        ch = WSChannel()
        await ch.send_text("hello")
        assert ch._hi.empty()

    def test_send_json_nowait_when_not_connected(self):
        ch = WSChannel()
        # 未连接时 send_json_nowait 直接 return
        ch.send_json_nowait({"type": "x"})
        assert ch._hi.empty()


# ════════════════════════════════════════════════════════════
# WSChannel — 连接后入队
# ════════════════════════════════════════════════════════════
class TestWSChannelEnqueue:
    """连接后 send_* 将消息放入对应优先级队列"""

    async def test_send_json_into_hi(self):
        ch = WSChannel()
        ch.connected = True
        await ch.send_json({"type": "test"})
        assert ch._hi.qsize() == 1
        msg = ch._hi.get_nowait()
        assert msg == {"kind": "json", "data": {"type": "test"}}

    async def test_send_bytes_into_lo(self):
        ch = WSChannel()
        ch.connected = True
        await ch.send_bytes(b"audio")
        assert ch._lo.qsize() == 1
        msg = ch._lo.get_nowait()
        assert msg == {"kind": "bytes", "data": b"audio"}

    async def test_send_text_into_hi(self):
        # text 进入高优先级队列
        ch = WSChannel()
        ch.connected = True
        await ch.send_text("session_end")
        assert ch._hi.qsize() == 1
        msg = ch._hi.get_nowait()
        assert msg == {"kind": "text", "data": "session_end"}

    def test_send_json_nowait_into_hi(self):
        ch = WSChannel()
        ch.connected = True
        ch.send_json_nowait({"type": "x"})
        assert ch._hi.qsize() == 1

    def test_send_json_nowait_full_keepalive_evicts_oldest(self):
        # _hi 满时，keepalive 消息会挤掉最旧的 keepalive
        ch = WSChannel()
        ch.connected = True
        # 填满 _hi（maxsize=64）
        for i in range(64):
            ch._hi.put_nowait({"kind": "json", "data": {"type": "keepalive", "seq": i}})
        # 再 put_nowait keepalive，应挤掉一个
        ch.send_json_nowait({"type": "keepalive", "seq": 999})
        assert ch._hi.qsize() == 64  # 仍然满
        # 最旧的一条已被挤掉
        first = ch._hi.get_nowait()
        assert first["data"]["seq"] == 1  # seq=0 被挤掉

    def test_send_json_nowait_full_non_keepalive_silently_drops(self):
        # _hi 满时非 keepalive 消息直接丢弃（不抛异常）
        ch = WSChannel()
        ch.connected = True
        for i in range(64):
            ch._hi.put_nowait({"kind": "json", "data": {"type": "other"}})
        # 不应抛异常
        ch.send_json_nowait({"type": "other", "seq": 1})
        assert ch._hi.qsize() == 64  # 数量不变


# ════════════════════════════════════════════════════════════
# WSChannel — bind 与 _send_loop
# ════════════════════════════════════════════════════════════
class TestWSChannelBindAndSendLoop:
    """bind 启动 _send_loop，实际向 websocket 发送数据"""

    async def test_bind_starts_send_loop(self):
        ch = WSChannel()
        ws = FakeWebSocket()
        ch.bind(ws)
        assert ch.connected is True
        assert ch.websocket is ws
        assert ch._send_task is not None
        assert ch._send_gen == 1
        await ch.close()

    async def test_send_json_dispatched_to_websocket(self):
        ch = WSChannel()
        ws = FakeWebSocket()
        ch.bind(ws)
        await ch.send_json({"type": "test", "data": "x"})
        # 等待 _send_loop 消费
        await asyncio.sleep(0.05)
        assert len(ws.sent_json) == 1
        assert ws.sent_json[0] == {"type": "test", "data": "x"}
        await ch.close()

    async def test_send_bytes_dispatched_to_websocket(self):
        ch = WSChannel()
        ws = FakeWebSocket()
        ch.bind(ws)
        await ch.send_bytes(b"audio-frame")
        await asyncio.sleep(0.15)  # _lo 用 0.1s timeout 轮询
        assert ws.sent_bytes == [b"audio-frame"]
        await ch.close()

    async def test_send_text_dispatched_to_websocket(self):
        ch = WSChannel()
        ws = FakeWebSocket()
        ch.bind(ws)
        await ch.send_text("hello-text")
        await asyncio.sleep(0.05)
        # text 进入 _hi，应优先被消费
        assert ws.sent_text == ["hello-text"]
        await ch.close()

    async def test_hi_priority_over_lo(self):
        # 同时入 hi 和 lo，hi 应先被发送
        ch = WSChannel()
        ws = FakeWebSocket()
        ch.bind(ws)
        # 先放入 lo（音频）
        await ch.send_bytes(b"audio")
        # 再放入 hi（控制帧）
        await ch.send_json({"type": "control"})
        await asyncio.sleep(0.2)
        # 两者都应被发送，但 control 先于 audio
        assert ws.sent_json[0] == {"type": "control"}
        assert b"audio" in ws.sent_bytes
        await ch.close()

    async def test_send_loop_handles_json_send_failure(self):
        # websocket.send_json 抛异常时，send_loop 应断开连接并退出
        ch = WSChannel()
        ws = FakeWebSocket(fail_on="json")
        ch.bind(ws)
        await ch.send_json({"type": "x"})
        await asyncio.sleep(0.1)
        # 发送失败后 connected 变为 False
        assert ch.connected is False

    async def test_send_loop_handles_bytes_send_failure(self):
        ch = WSChannel()
        ws = FakeWebSocket(fail_on="bytes")
        ch.bind(ws)
        await ch.send_bytes(b"x")
        await asyncio.sleep(0.2)
        assert ch.connected is False

    async def test_send_loop_handles_text_send_failure(self):
        ch = WSChannel()
        ws = FakeWebSocket(fail_on="text")
        ch.bind(ws)
        await ch.send_text("x")
        await asyncio.sleep(0.1)
        assert ch.connected is False

    async def test_send_loop_terminates_on_gen_mismatch(self):
        # bind 后 _send_gen 增加，旧 _send_loop 检测到 gen 不匹配应退出
        ch = WSChannel()
        ws = FakeWebSocket()
        ch.bind(ws)
        old_task = ch._send_task
        # 模拟 gen 变化（interrupt_send_loop 会做）
        ch._send_gen += 1
        await ch.send_json({"type": "x"})
        await asyncio.sleep(0.2)
        # 旧 task 应已完成
        assert old_task.done() or ch.connected is False
        await ch.close()

    async def test_send_loop_lo_timeout_continues(self):
        # _lo 空时，_send_loop 0.1s 超时后应继续循环检查 _hi
        ch = WSChannel()
        ws = FakeWebSocket()
        ch.bind(ws)
        # 等待超过 0.1s，确认 loop 仍在运行
        await asyncio.sleep(0.15)
        assert ch.connected is True
        assert ch._send_task is not None and not ch._send_task.done()
        await ch.close()


# ════════════════════════════════════════════════════════════
# WSChannel — clear_queue / interrupt_send_loop / close
# ════════════════════════════════════════════════════════════
class TestWSChannelClearAndInterrupt:
    """clear_queue / interrupt_send_loop / close 测试"""

    async def test_clear_queue_returns_count(self):
        ch = WSChannel()
        ch.connected = True
        await ch.send_json({"type": "a"})
        await ch.send_json({"type": "b"})
        await ch.send_bytes(b"x")
        cleared = ch.clear_queue()
        assert cleared == 3
        assert ch._hi.empty()
        assert ch._lo.empty()

    async def test_clear_queue_empty(self):
        ch = WSChannel()
        assert ch.clear_queue() == 0

    async def test_interrupt_send_loop_clears_and_restarts(self):
        # interrupt_send_loop 应清空队列并在连接时重启 send_loop
        ch = WSChannel()
        ws = FakeWebSocket()
        ch.bind(ws)
        await ch.send_json({"type": "a"})
        await ch.send_bytes(b"b")
        cleared = await ch.interrupt_send_loop()
        assert cleared == 2
        assert ch._hi.empty()
        assert ch._lo.empty()
        # gen 增加
        assert ch._send_gen == 2
        # 新 send_task 已创建
        assert ch._send_task is not None
        await ch.close()

    async def test_interrupt_send_loop_when_not_connected(self):
        # 未连接时 interrupt 不创建新 task
        ch = WSChannel()
        ch.connected = False
        cleared = await ch.interrupt_send_loop()
        assert cleared == 0
        assert ch._send_task is None

    async def test_close_sets_disconnected(self):
        ch = WSChannel()
        ws = FakeWebSocket()
        ch.bind(ws)
        await ch.close()
        assert ch.connected is False
        assert ch._send_task is None or ch._send_task.done()

    async def test_close_idempotent(self):
        # 重复 close 不出错
        ch = WSChannel()
        ws = FakeWebSocket()
        ch.bind(ws)
        await ch.close()
        await ch.close()  # 第二次不应抛异常

    async def test_close_without_bind(self):
        # 未 bind 就 close 不出错
        ch = WSChannel()
        await ch.close()
        assert ch.connected is False

    async def test_interrupt_then_send_works(self):
        # interrupt 后仍能正常发送（新 send_loop 已启动）
        ch = WSChannel()
        ws = FakeWebSocket()
        ch.bind(ws)
        await ch.interrupt_send_loop()
        await ch.send_json({"type": "post-interrupt"})
        await asyncio.sleep(0.05)
        assert ws.sent_json == [{"type": "post-interrupt"}]
        await ch.close()


# ════════════════════════════════════════════════════════════
# WSChannel — 端到端混合消息
# ════════════════════════════════════════════════════════════
class TestWSChannelMixed:
    """混合消息端到端测试"""

    async def test_mixed_messages_all_delivered(self):
        ch = WSChannel()
        ws = FakeWebSocket()
        ch.bind(ws)
        # 混合发送 json / bytes / text
        await ch.send_json({"type": "status", "value": 1})
        await ch.send_bytes(b"\x01\x02")
        await ch.send_text("end")
        await ch.send_bytes(b"\x03\x04")
        await asyncio.sleep(0.25)
        # 全部应被送达
        assert len(ws.sent_json) == 1
        assert ws.sent_bytes == [b"\x01\x02", b"\x03\x04"]
        assert ws.sent_text == ["end"]
        await ch.close()

    async def test_high_volume_bytes(self):
        # 大量音频帧应全部送达
        ch = WSChannel()
        ws = FakeWebSocket()
        ch.bind(ws)
        for i in range(20):
            await ch.send_bytes(bytes([i]))
        # 等待 send_loop 消费完（每帧 ~0.05s sleep 在 Pipeline，但 WSChannel 本身不 sleep）
        await asyncio.sleep(0.3)
        assert len(ws.sent_bytes) == 20
        await ch.close()

    async def test_session_status_not_logged(self):
        # session_status 类型不应被记录到日志（仅验证不抛异常即可）
        ch = WSChannel()
        ws = FakeWebSocket()
        ch.bind(ws)
        await ch.send_json({"type": "session_status", "status": "iat_start"})
        await asyncio.sleep(0.05)
        assert ws.sent_json[0]["type"] == "session_status"
        await ch.close()

    async def test_rebind_restarts_send_loop(self):
        # 重新 bind 应启动新的 send_loop（gen 递增）
        ch = WSChannel()
        ws1 = FakeWebSocket()
        ch.bind(ws1)
        gen1 = ch._send_gen
        await ch.close()

        ws2 = FakeWebSocket()
        ch.bind(ws2)
        assert ch._send_gen == gen1 + 1
        assert ch.connected is True
        await ch.close()
