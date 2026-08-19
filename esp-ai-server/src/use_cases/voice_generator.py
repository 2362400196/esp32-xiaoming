from __future__ import annotations


class VoiceGenerator:
    """
    TTS音频帧生成器

    帧结构（与 esp-ai audio_sender.js 一致）：
    会话ID(4字节 utf-8) + 会话状态(2字节 utf-8) + 原始音频数据
    """

    def __init__(self):
        # 缓存 (session_id, status) → 编码后的字节前缀，避免每帧重复 encode
        self._prefix_cache: dict[tuple[str, str], bytes] = {}

    def make_tts_frame(self, session_id: str, audio_data: bytes, status: str = "00") -> bytes:
        """
        创建 TTS 数据帧

        Args:
            session_id: 会话ID（4字符）
            audio_data: 原始音频数据
            status: 状态码（"00"=正常, "03"=结束）

        Returns:
            完整的TTS帧数据
        """
        key = (session_id, status)
        prefix = self._prefix_cache.get(key)
        if prefix is None:
            prefix = session_id.encode("utf-8") + status.encode("utf-8")
            self._prefix_cache[key] = prefix
        return prefix + audio_data

    def make_end_frame(self, session_id: str, status: str = "03") -> bytes:
        """
        创建结束帧

        帧结构：会话ID(4字节) + 状态码(2字节)

        Args:
            session_id: 会话ID（4字符）
            status: 状态码（"02"=继续对话, "03"=会话结束）

        Returns:
            结束帧数据
        """
        return session_id.encode("utf-8") + status.encode("utf-8")


__all__ = ["VoiceGenerator"]
