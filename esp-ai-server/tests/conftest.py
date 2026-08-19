"""
Pytest fixtures and configuration
"""
import pytest
import asyncio


@pytest.fixture
def mock_channel():
    """Mock WSChannel for testing."""

    class MockSendQueue:
        def __init__(self, owner):
            self._owner = owner

        async def put(self, msg):
            if msg.get("kind") == "json":
                self._owner.sent_json.append(msg["data"])
            elif msg.get("kind") == "bytes":
                self._owner.sent_bytes.append(msg["data"])
            elif msg.get("kind") == "text":
                self._owner.sent_json.append({"type": "text", "data": msg["data"]})

        def put_nowait(self, msg):
            if msg.get("kind") == "json":
                self._owner.sent_json.append(msg["data"])
            elif msg.get("kind") == "bytes":
                self._owner.sent_bytes.append(msg["data"])
            elif msg.get("kind") == "text":
                self._owner.sent_json.append({"type": "text", "data": msg["data"]})

        async def get(self):
            return {}

        def task_done(self):
            pass

        def empty(self):
            return True

    class MockChannel:
        def __init__(self):
            self.sent_json = []
            self.sent_bytes = []
            self.sent_text = []
            self.connected = True
            self._fsm_state = "idle"
            self.send_queue = MockSendQueue(self)
            self.websocket = self

        async def send_json(self, data):
            self.sent_json.append(data)

        async def send_bytes(self, data):
            self.sent_bytes.append(data)

        async def close(self):
            self.connected = False

        def send_json_nowait(self, data):
            self.sent_json.append(data)

        def clear_queue(self):
            count = len(self.sent_json) + len(self.sent_bytes)
            self.sent_json.clear()
            self.sent_bytes.clear()
            return count

        async def interrupt_send_loop(self) -> int:
            return self.clear_queue()

        async def send_text(self, data):
            self.sent_json.append({"type": "text", "data": data})

    return MockChannel()


@pytest.fixture
def mock_fsm():
    class MockFSM:
        def __init__(self):
            self.state = "idle"
            self.transitions = []

        async def set(self, new_state):
            self.transitions.append((self.state, new_state))
            self.state = new_state

        def get(self):
            return self.state

        def is_busy(self):
            return self.state != "idle"

    return MockFSM()


@pytest.fixture
def mock_voice_generator():
    """Mock VoiceGenerator for testing."""
    from src.use_cases.voice_generator import VoiceGenerator
    return VoiceGenerator()


@pytest.fixture
def mock_memory():
    """Mock ConversationMemory for testing."""
    from src.use_cases.auxiliary_services import ConversationMemory
    return ConversationMemory(max_messages=10)


@pytest.fixture
def mock_session_runtime():
    """Mock SessionRuntime for testing."""
    from src.use_cases.session import SessionRuntime
    return SessionRuntime()


@pytest.fixture
def sample_audio_chunk():
    """Sample audio chunk for testing."""
    return b"\x00\x01\x02\x03" * 160  # 640 bytes


@pytest.fixture
def sample_text():
    """Sample text for testing."""
    return "这是一段测试文本"


@pytest.fixture
def sample_messages():
    """Sample messages for testing."""
    return [
        {"role": "system", "content": "你是一个有帮助的助手"},
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好！有什么可以帮助你的吗？"},
    ]


@pytest.fixture
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
