"""
BackpressureQueues 单元测试

覆盖 src/use_cases/queues.py:
- BackpressureQueue       : 基础背压队列（block / drop_oldest / drop_newest）
- TextQueue / AudioQueue / SendQueue : 预设配置子类
- BackpressureQueues      : 三级队列组

测试策略：
- asyncio_mode="auto"，直接 await 异步方法
- 覆盖 put / put_nowait / get / get_nowait / clear / join / 统计字段
- 覆盖三种溢出策略与边界（空队列、满队列）
"""
from __future__ import annotations

import asyncio

import pytest

from src.use_cases.queues import (
    AudioQueue,
    BackpressureQueue,
    BackpressureQueues,
    SendQueue,
    TextQueue,
)


# ════════════════════════════════════════════════════════════
# BackpressureQueue — 基础队列
# ════════════════════════════════════════════════════════════
class TestBackpressureQueueBlock:
    """block 策略测试"""

    async def test_put_and_get(self):
        # 正常入队、出队
        q = BackpressureQueue(maxsize=5, name="t", on_full="block")
        await q.put("a")
        await q.put("b")
        assert await q.get() == "a"
        assert await q.get() == "b"

    async def test_put_nowait_and_get_nowait(self):
        q = BackpressureQueue(maxsize=5, name="t", on_full="block")
        q.put_nowait("x")
        q.put_nowait("y")
        assert q.get_nowait() == "x"
        assert q.get_nowait() == "y"

    async def test_put_nowait_full_raises(self):
        # block 策略下 put_nowait 满时抛 QueueFull
        q = BackpressureQueue(maxsize=1, name="t", on_full="block")
        q.put_nowait("a")
        with pytest.raises(asyncio.QueueFull):
            q.put_nowait("b")

    async def test_put_blocks_when_full(self):
        # block 策略：满时 put 会阻塞，直到有消费者取出
        q = BackpressureQueue(maxsize=1, name="t", on_full="block")
        await q.put("a")

        async def consumer():
            await asyncio.sleep(0.01)
            return await q.get()

        task = asyncio.create_task(consumer())
        # put 会阻塞直到 consumer 取走
        await q.put("b")
        first = await task
        assert first == "a"

    async def test_task_done_and_join(self):
        # join 等待所有 task_done 调用
        q = BackpressureQueue(maxsize=5, name="t", on_full="block")
        await q.put("a")
        await q.get()
        q.task_done()
        # 不应阻塞
        await asyncio.wait_for(q.join(), timeout=1.0)

    async def test_clear_returns_count(self):
        q = BackpressureQueue(maxsize=5, name="t", on_full="block")
        for i in range(3):
            await q.put(i)
        cleared = q.clear()
        assert cleared == 3
        assert q.empty()

    async def test_clear_empty_returns_zero(self):
        q = BackpressureQueue(maxsize=5, name="t", on_full="block")
        assert q.clear() == 0

    async def test_empty_and_full(self):
        q = BackpressureQueue(maxsize=2, name="t", on_full="block")
        assert q.empty()
        assert not q.full()
        await q.put("a")
        await q.put("b")
        assert q.full()
        assert not q.empty()

    async def test_qsize(self):
        q = BackpressureQueue(maxsize=5, name="t", on_full="block")
        assert q.qsize() == 0
        await q.put("a")
        await q.put("b")
        assert q.qsize() == 2

    async def test_dropped_initial_zero(self):
        q = BackpressureQueue(maxsize=5, name="t", on_full="block")
        assert q.dropped == 0

    async def test_reset_stats(self):
        q = BackpressureQueue(maxsize=1, name="t", on_full="drop_newest")
        q.put_nowait("a")
        q.put_nowait("b")  # 被丢弃
        assert q.dropped == 1
        q.reset_stats()
        assert q.dropped == 0

    async def test_queue_property(self):
        # queue 属性暴露底层 asyncio.Queue
        q = BackpressureQueue(maxsize=5, name="t", on_full="block")
        assert isinstance(q.queue, asyncio.Queue)


# ════════════════════════════════════════════════════════════
# BackpressureQueue — drop_oldest 策略
# ════════════════════════════════════════════════════════════
class TestBackpressureQueueDropOldest:
    """drop_oldest 策略测试"""

    async def test_put_drops_oldest(self):
        # 满时丢弃最旧元素，dropped 计数递增
        q = BackpressureQueue(maxsize=2, name="t", on_full="drop_oldest")
        await q.put("a")
        await q.put("b")
        await q.put("c")  # "a" 被丢弃
        assert q.dropped == 1
        assert await q.get() == "b"
        assert await q.get() == "c"

    async def test_put_nowait_drops_oldest(self):
        q = BackpressureQueue(maxsize=2, name="t", on_full="drop_oldest")
        q.put_nowait("a")
        q.put_nowait("b")
        q.put_nowait("c")  # 丢弃 "a"
        assert q.dropped == 1
        assert q.qsize() == 2

    async def test_put_nowait_drop_oldest_multiple(self):
        # 一次性入队多个超出 maxsize 的元素
        q = BackpressureQueue(maxsize=2, name="t", on_full="drop_oldest")
        q.put_nowait("a")
        q.put_nowait("b")
        q.put_nowait("c")
        q.put_nowait("d")
        q.put_nowait("e")
        # 最终保留最后两个
        assert q.qsize() == 2
        assert q.get_nowait() == "d"
        assert q.get_nowait() == "e"
        assert q.dropped == 3

    async def test_put_drop_oldest_does_not_block(self):
        # drop_oldest 的 async put 不应阻塞
        q = BackpressureQueue(maxsize=1, name="t", on_full="drop_oldest")
        await q.put("a")
        await asyncio.wait_for(q.put("b"), timeout=1.0)
        assert q.dropped == 1


# ════════════════════════════════════════════════════════════
# BackpressureQueue — drop_newest 策略
# ════════════════════════════════════════════════════════════
class TestBackpressureQueueDropNewest:
    """drop_newest 策略测试"""

    async def test_put_nowait_drops_new(self):
        # 满时新元素被丢弃，旧元素保留
        q = BackpressureQueue(maxsize=2, name="t", on_full="drop_newest")
        q.put_nowait("a")
        q.put_nowait("b")
        q.put_nowait("c")  # "c" 被丢弃
        assert q.dropped == 1
        assert q.qsize() == 2
        assert q.get_nowait() == "a"
        assert q.get_nowait() == "b"

    async def test_put_drops_new_async(self):
        # async put 也走 drop_newest
        q = BackpressureQueue(maxsize=1, name="t", on_full="drop_newest")
        await q.put("a")
        await q.put("b")  # 丢弃
        assert q.dropped == 1
        assert await q.get() == "a"

    async def test_drop_newest_keeps_old(self):
        q = BackpressureQueue(maxsize=2, name="t", on_full="drop_newest")
        q.put_nowait("old1")
        q.put_nowait("old2")
        for i in range(5):
            q.put_nowait(f"new{i}")
        # 旧的还在
        assert q.get_nowait() == "old1"
        assert q.get_nowait() == "old2"
        assert q.dropped == 5


# ════════════════════════════════════════════════════════════
# 预设子类 — TextQueue / AudioQueue / SendQueue
# ════════════════════════════════════════════════════════════
class TestPresetQueues:
    """预设子类的默认配置测试"""

    def test_text_queue_config(self):
        # TextQueue: block, maxsize=100（满时阻塞，保证长回复不丢句）
        q = TextQueue()
        assert q._on_full == "block"
        assert q._name == "text_queue"
        assert q.queue.maxsize == 100

    def test_text_queue_custom_maxsize(self):
        q = TextQueue(maxsize=50)
        assert q.queue.maxsize == 50

    def test_audio_queue_config(self):
        # AudioQueue: block, maxsize=20
        q = AudioQueue()
        assert q._on_full == "block"
        assert q._name == "audio_queue"
        assert q.queue.maxsize == 20

    def test_send_queue_config(self):
        # SendQueue: block, maxsize=500（构造默认）
        q = SendQueue()
        assert q._on_full == "block"
        assert q._name == "send_queue"
        assert q.queue.maxsize == 500

    async def test_text_queue_blocks_when_full(self):
        # 验证 TextQueue 的 block 行为：队列满后 put 挂起，取出一条后恢复
        q = TextQueue(maxsize=2)
        await q.put(("seq1", "text1"))
        await q.put(("seq2", "text2"))

        put_task = asyncio.create_task(q.put(("seq3", "text3")))
        await asyncio.sleep(0.05)
        assert not put_task.done()  # 队列满，put 阻塞中

        seq, _ = await q.get()
        assert seq == "seq1"
        await asyncio.wait_for(put_task, timeout=1)  # 取出后 put 完成
        assert q.qsize() == 2


# ════════════════════════════════════════════════════════════
# BackpressureQueues — 三级队列组
# ════════════════════════════════════════════════════════════
class TestBackpressureQueues:
    """三级队列组测试"""

    def test_init_creates_three_queues(self):
        bq = BackpressureQueues()
        assert isinstance(bq.text, TextQueue)
        assert isinstance(bq.audio, AudioQueue)
        assert isinstance(bq.send, SendQueue)

    def test_all_queues_are_block(self):
        bq = BackpressureQueues()
        assert bq.text._on_full == "block"
        assert bq.audio._on_full == "block"
        assert bq.send._on_full == "block"

    async def test_clear_all(self):
        bq = BackpressureQueues()
        await bq.text.put("a")
        await bq.audio.put("b")
        await bq.send.put("c")
        bq.clear_all()
        assert bq.text.empty()
        assert bq.audio.empty()
        assert bq.send.empty()

    async def test_clear_all_empty(self):
        # 空队列 clear_all 不出错
        bq = BackpressureQueues()
        bq.clear_all()
        assert bq.text.empty()
        assert bq.audio.empty()
        assert bq.send.empty()

    async def test_put_sentinel_text(self):
        # put_sentinel 向 text/audio 投入终止标记 (-1, None)
        bq = BackpressureQueues()
        bq.put_sentinel()
        item = await bq.text.get()
        assert item == (-1, None)
        # audio 队列也收到 (-1, None, None)
        audio_item = await bq.audio.get()
        assert audio_item == (-1, None, None)

    async def test_put_sentinel_when_full_text(self):
        # text 队列满时（block 策略）put_sentinel 的 put_nowait 抛 QueueFull，
        # 内部 try/except 静默忽略（不抛异常、不入队）
        bq = BackpressureQueues()
        # 填满 text_queue（BackpressureQueues 中 maxsize=100）
        for i in range(100):
            await bq.text.put((i, f"t{i}"))
        bq.put_sentinel()
        # 队列仍满
        assert bq.text.full()

    async def test_put_sentinel_when_full_audio(self):
        # audio 队列满时（block 策略）put_sentinel 应捕获 QueueFull
        bq = BackpressureQueues()
        for i in range(20):
            await bq.audio.put((i, f"a{i}", None))
        # put_nowait 在 block 策略下满时抛 QueueFull，put_sentinel 内部 try/except
        # 不应抛异常
        bq.put_sentinel()

    async def test_independent_queues(self):
        # 三个队列互相独立
        bq = BackpressureQueues()
        await bq.text.put("text-item")
        await bq.audio.put("audio-item")
        await bq.send.put("send-item")
        assert bq.text.qsize() == 1
        assert bq.audio.qsize() == 1
        assert bq.send.qsize() == 1
        # 清空 text 不影响其他
        bq.text.clear()
        assert bq.text.empty()
        assert bq.audio.qsize() == 1
        assert bq.send.qsize() == 1

    async def test_full_pipeline_flow(self):
        # 模拟 text → audio → send 流转
        bq = BackpressureQueues()
        await bq.text.put((0, "hello"))
        seq, text = await bq.text.get()
        bq.text.task_done()
        await bq.audio.put((seq, text, text))
        aseq, atext, _ = await bq.audio.get()
        bq.audio.task_done()
        await bq.send.put((aseq, b"frame", atext))
        sseq, sframe, stext = await bq.send.get()
        bq.send.task_done()
        assert sseq == 0
        assert sframe == b"frame"
        assert stext == "hello"


# ════════════════════════════════════════════════════════════
# 边界条件
# ════════════════════════════════════════════════════════════
class TestEdgeCases:
    """边界条件测试"""

    async def test_get_nowait_empty_raises(self):
        # 空队列 get_nowait 抛 QueueEmpty
        q = BackpressureQueue(maxsize=5, name="t", on_full="block")
        with pytest.raises(asyncio.QueueEmpty):
            q.get_nowait()

    async def test_maxsize_one_block(self):
        # maxsize=1 的 block 队列
        q = BackpressureQueue(maxsize=1, name="t", on_full="block")
        await q.put("only")
        assert q.full()
        assert await q.get() == "only"
        assert q.empty()

    async def test_drop_oldest_with_empty_queue_no_crash(self):
        # drop_oldest 内部 while 循环：当 get_nowait 抛 QueueEmpty 时应 break
        q = BackpressureQueue(maxsize=1, name="t", on_full="drop_oldest")
        # 先填满
        q.put_nowait("a")
        # 再 put_nowait，触发丢弃
        q.put_nowait("b")
        assert q.dropped == 1

    async def test_clear_resets_task_counter(self):
        # clear 后 join 不阻塞（task_done 已对每个 get 调用）
        q = BackpressureQueue(maxsize=5, name="t", on_full="block")
        for i in range(3):
            await q.put(i)
        q.clear()
        await asyncio.wait_for(q.join(), timeout=1.0)

    async def test_unknown_on_full_strategy(self):
        # 未知策略时 put/put_nowait 不做任何处理（不抛错也不入队）
        q = BackpressureQueue(maxsize=5, name="t", on_full="unknown")
        await q.put("a")
        # 未知策略 -> 不入队
        assert q.empty()
        q.put_nowait("b")
        assert q.empty()
