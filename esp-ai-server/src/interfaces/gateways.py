"""External service gateways and adapters.

ASR 网关已按 provider 拆分到 ``src.interfaces.asr`` 子包，此处重新导出以保持向后兼容。
本模块保留 LLM、TTS、Tool、Memory、Emotion 等网关实现。
"""
from __future__ import annotations

import asyncio
import json
import struct
import time
import urllib.parse
from typing import Any, AsyncIterator, Optional

import websockets

from src.domain.entities import Conversation, Message
from src.domain.exceptions import *
from src.domain.repositories import LLMRepository, TTSRepository, ToolRepository
from src.infrastructure.logging import get_logger
from src.interfaces.asr import (
    AliYunASRGateway,
    BaseASRGateway,
    TencentASRGateway,
    VolcEngineASRConnectionPool,
    VolcEngineASRGateway,
    XunfeiASRGateway,
    create_asr_gateway,
)

logger = get_logger("gateways")


class BaseLLMGateway(LLMRepository):

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.model = config.get("model", "")
        self.api_key = config.get("api_key", "")
        self.base_url = config.get("base_url", "")
        self.system_prompt = config.get("system_prompt", "")
        self.temperature = config.get("temperature", 0.7)
        self.max_tokens = config.get("max_tokens", 2000)


class OpenAILLMGateway(BaseLLMGateway):

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.stream = config.get("stream", True)
        self.tools_config = config.get("tools", [])

    async def generate(
        self,
        messages: list[dict],
        **kwargs
    ) -> str:
        import httpx

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", self.temperature),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "stream": False,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()

        return result["choices"][0]["message"]["content"]

    async def generate_stream(
        self,
        messages: list[dict],
        **kwargs
    ) -> AsyncIterator[str]:
        import httpx

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", self.temperature),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "stream": True,
        }

        tools = kwargs.get("tools", self.tools_config)
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        try:
                            data = json.loads(line[6:])
                            delta = data["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            tool_calls = delta.get("tool_calls")

                            if content:
                                yield content

                            if tool_calls:
                                yield json.dumps({"tool_calls": tool_calls})

                            finish_reason = data["choices"][0].get("finish_reason", "")
                            if finish_reason == "stop":
                                break
                            elif finish_reason == "tool_calls":
                                choice = data["choices"][0]
                                if "message" in choice:
                                    msg = choice["message"]
                                    if "tool_calls" in msg:
                                        yield json.dumps({
                                            "tool_calls_complete": msg["tool_calls"]
                                        })
                        except json.JSONDecodeError:
                            continue

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict,
        **kwargs
    ) -> Any:
        tool_gateway = kwargs.get("tool_gateway")
        if tool_gateway:
            return await tool_gateway.execute_tool(tool_name, arguments)
        return {"error": "Tool gateway not configured"}


class BaseTTSGateway(TTSRepository):

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.voice_type = config.get("voice_type", "")
        self.speed = config.get("speed", 1.0)
        self.volume = config.get("volume", 1.0)
        self.pitch = config.get("pitch", 1.0)


class VolcEngineTTSGateway(BaseTTSGateway):

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.api_key = config.get("api_key", "")
        self.resource_id = config.get("resource_id", "")
        self._session = None
        self._sequence_number = 0

    async def synthesize(self, text: str, **kwargs) -> AsyncIterator[bytes]:
        session = await self.create_session(**kwargs)

        try:
            async for chunk in session.synthesize(text):
                yield chunk
        finally:
            await session.close()

    async def create_session(self, **kwargs) -> Any:
        return VolcEngineTTSSession(self.config, **kwargs)

    async def close_session(self, session: Any) -> None:
        if session:
            await session.close()


class VolcEngineTTSSession:

    def __init__(self, config: dict, cancel_event=None):
        self.config = config
        self.cancel_event = cancel_event
        self.ws = None
        self._sequence_number = 0
        self.api_key = config.get("api_key", "")
        self.resource_id = config.get("resource_id", "")
        self.voice_type = config.get("voice_type", "")
        self.speed = config.get("speed", 1.0)
        self.volume = config.get("volume", 1.0)
        self.pitch = config.get("pitch", 1.0)

    async def connect(self) -> bool:
        host = "openspeech.bytedance.com"
        path = "/api/v1/tts"
        token = f"Bearer;{self.api_key}"

        url = f"wss://{host}{path}?{urllib.parse.quote(token)}"

        try:
            self.ws = await websockets.connect(url, max_size=20 * 1024 * 1024)
            return True
        except Exception as e:
            logger.error(f"TTS connection failed: {e}")
            return False

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        if not self.ws:
            if not await self.connect():
                raise TTSError("Failed to connect to TTS service", provider="volcengine")

        try:
            payload = {
                "app": {
                    "appid": "",
                    "cluster": "volc_tts_streaming_common",
                    "token": self.api_key,
                },
                "user": {
                    "uid": "esp_ai_server",
                },
                "audio": {
                    "voice_type": self.voice_type,
                    "encoding": "mp3",
                    "speed_ratio": self.speed,
                    "volume_ratio": self.volume,
                    "pitch_ratio": self.pitch,
                    "rate": 24000,
                },
                "request": {
                    "reqid": f"tts_{int(time.time() * 1000)}",
                    "text": text,
                    "text_type": "plain",
                    "operation": "query",
                }
            }

            data = json.dumps(payload).encode('utf-8')
            header = struct.pack(">II", len(data), 1)
            await self.ws.send(header + data)

            while True:
                if self.cancel_event and self.cancel_event.is_set():
                    break

                try:
                    response = await asyncio.wait_for(self.ws.recv(), timeout=30.0)

                    if isinstance(response, bytes) and len(response) >= 8:
                        header_data = response[:8]
                        payload = response[8:]

                        if len(payload) > 0:
                            yield payload
                    elif isinstance(response, str):
                        try:
                            result = json.loads(response)
                            if result.get("type") == "finish":
                                break
                        except json.JSONDecodeError:
                            pass

                except asyncio.TimeoutError:
                    break

        except Exception as e:
            raise TTSError(f"TTS synthesis failed: {e}", provider="volcengine")

    async def close(self) -> None:
        if self.ws:
            try:
                await self.ws.close()
            except Exception as e:
                logger.debug(f"[Gateways] TTS 关闭 WS 异常: {e}")
            self.ws = None


class ToolGateway(ToolRepository):

    def __init__(self, config: dict = None):
        self.config = config or {}
        self._tools: dict[str, Any] = {}
        self._mcp_clients: dict[str, Any] = {}

    async def get_available_tools(self) -> list[dict]:
        tools = []

        for name, tool in self._tools.items():
            tools.append({
                "name": name,
                "description": getattr(tool, 'description', ''),
                "parameters": getattr(tool, 'parameters', {}),
            })

        for mcp_name, client in self._mcp_clients.items():
            try:
                mcp_tools = await client.list_tools()
                tools.extend(mcp_tools)
            except Exception as e:
                logger.error(f"Failed to get MCP tools from {mcp_name}: {e}")

        return tools

    async def execute_tool(
        self,
        tool_name: str,
        arguments: dict,
        context: Optional[dict] = None
    ) -> Any:
        if tool_name in self._tools:
            tool = self._tools[tool_name]
            try:
                result = await tool.execute(arguments, context)
                return result
            except Exception as e:
                raise ToolExecutionError(tool_name=tool_name, reason=str(e))

        for mcp_name, client in self._mcp_clients.items():
            try:
                result = await client.call_tool(tool_name, arguments)
                return result
            except Exception:
                continue

        raise ToolNotFoundError(tool_name=tool_name)

    async def discover_tools(self) -> None:
        await self._load_builtin_tools()

        mcp_servers = self.config.get("mcp_servers", {})
        for server_name, server_config in mcp_servers.items():
            try:
                client = await self._create_mcp_client(server_config)
                self._mcp_clients[server_name] = client
                logger.info(f"MCP server '{server_name}' connected")
            except Exception as e:
                logger.error(f"Failed to connect MCP server '{server_name}': {e}")

    async def _load_builtin_tools(self) -> None:
        self._tools["speak"] = BuiltinSpeakTool()

    async def _create_mcp_client(self, config: dict) -> Any:
        class MockMCPClient:
            async def list_tools(self) -> list[dict]:
                return []
            async def call_tool(self, name: str, args: dict) -> Any:
                return {"error": "Not implemented"}
        return MockMCPClient()


class BuiltinSpeakTool:

    description = "通过语音向用户传达信息"
    parameters = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "要说的内容",
            }
        },
        "required": ["text"],
    }

    async def execute(self, arguments: dict, context: dict = None) -> dict:
        text = arguments.get("text", "")
        return {
            "success": True,
            "message": f"Speaking: {text}",
            "text": text,
        }


class MemoryGateway:

    def __init__(self, config: dict = None):
        self.config = config or {}
        self._conversations: dict[str, Conversation] = {}
        self.default_max_messages = config.get("max_messages", 20)
        self.default_max_tokens = config.get("max_tokens", 2000)

    def get_or_create_conversation(self, session_id: str) -> Conversation:
        if session_id not in self._conversations:
            self._conversations[session_id] = Conversation(
                max_messages=self.default_max_messages,
                max_tokens=self.default_max_tokens,
            )
        return self._conversations[session_id]

    def add_message(self, session_id: str, message: Message) -> None:
        conv = self.get_or_create_conversation(session_id)
        conv.add_message(message)

    def build_context(
        self,
        session_id: str,
        system_prompt: str,
        user_input: str,
    ) -> list[dict]:
        conv = self.get_or_create_conversation(session_id)
        return conv.build_messages_for_llm(system_prompt, user_input)

    def clear_conversation(self, session_id: str) -> None:
        if session_id in self._conversations:
            self._conversations[session_id].clear()

    def get_conversation(self, session_id: str) -> Optional[Conversation]:
        return self._conversations.get(session_id)


class EmotionGateway:

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.enabled = config.get("enabled", False)
        self.gif_dir = config.get("gif_dir", "emos")
        self.static_dir = config.get("static_dir", "static_emos")
        self._last_emotions: dict[str, str] = {}

    async def detect_emotion(self, text: str, device_id: str = "") -> Optional[str]:
        if not self.enabled:
            return None

        emotion_keywords = {
            "happy": ["开心", "高兴", "快乐", "哈哈", "棒", "好"],
            "sad": ["伤心", "难过", "悲伤", "哭", "难过"],
            "angry": ["生气", "愤怒", "讨厌", "烦"],
            "surprised": ["惊讶", "意外", "哇", "天哪"],
            "negative": ["不", "不是", "没有", "别", "不要"],
        }

        for emotion, keywords in emotion_keywords.items():
            for keyword in keywords:
                if keyword in text:
                    if device_id:
                        self._last_emotions[device_id] = emotion
                    return emotion

        return None

    async def get_emotion_image_path(
        self,
        emotion: str,
        static: bool = False,
    ) -> Optional[str]:
        if not emotion:
            return None

        emotion_map = {
            "happy": "快乐.gif",
            "sad": "伤心.gif",
            "angry": "愤怒.gif",
            "surprised": "意外.gif",
            "neutral": "无情绪.gif",
            "negative": "否定.gif",
        }

        filename = emotion_map.get(emotion)
        if not filename:
            return None

        directory = self.static_dir if static else self.gif_dir
        return f"{directory}/{filename}"

    async def should_send_emotion(
        self,
        emotion: str,
        device_id: str,
    ) -> bool:
        if not emotion or not device_id:
            return False

        last_emotion = self._last_emotions.get(device_id)
        if last_emotion == emotion:
            return False

        return True


__all__ = [
    "BaseASRGateway",
    "TencentASRGateway",
    "VolcEngineASRGateway",
    "AliYunASRGateway",
    "XunfeiASRGateway",
    "VolcEngineASRConnectionPool",
    "create_asr_gateway",
    "BaseLLMGateway",
    "OpenAILLMGateway",
    "BaseTTSGateway",
    "VolcEngineTTSGateway",
    "VolcEngineTTSSession",
    "ToolGateway",
    "BuiltinSpeakTool",
    "MemoryGateway",
    "EmotionGateway",
]
