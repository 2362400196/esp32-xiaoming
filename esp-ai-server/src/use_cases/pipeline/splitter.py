"""流式 token 句子分割器。"""
from __future__ import annotations

import re


class SentenceSplitter:
    """句子分割器：将流式token组装成完整句子"""

    def __init__(self):
        self.buffer = ""

    def feed(self, token: str) -> list:
        if not token:
            return []

        self.buffer += token
        sentences = []

        # 硬切分点：句号、问号、感叹号
        if any(p in self.buffer for p in ["。", "！", "？", ".", "!", "?"]):
            parts = re.split(r"([。！？.!?])", self.buffer)
            tmp = ""
            for p in parts:
                tmp += p
                if p in "。！？.!?":
                    stripped = tmp.strip()
                    if stripped and len(stripped) > 1:
                        sentences.append(stripped)
                    tmp = ""
            self.buffer = tmp

        # 软切分点：逗号、分号、顿号、冒号、省略号、破折号
        # （子句长度 >= 2 时切分，让首句更快产出送入 TTS）
        # 性能优化：从 4 字符降到 2 字符，首句 TTS 提前 ~500ms 启动；
        # 扩充软切分符（"——" 等口语停顿）避免首句等到很远的逗号才切出
        # （如"正数着呢——你今天…"要等 20 字后的逗号，白等 ~600ms）
        if not sentences:
            last_soft = -1
            for i, ch in enumerate(self.buffer):
                if ch in "，；,、：…":
                    last_soft = i
            # 破折号"——"是双字符：切分点算在第二个"-"上（连同符号一起送 TTS）
            dash = self.buffer.find("——")
            if dash >= 0:
                last_soft = max(last_soft, dash + 1)
            if last_soft >= 1:  # 子句至少 2 个字符（索引>=1）
                sentence = self.buffer[:last_soft + 1].strip()
                if sentence and len(sentence) > 1:
                    sentences.append(sentence)
                self.buffer = self.buffer[last_soft + 1:]

        return sentences

    def flush(self) -> str:
        remaining = self.buffer.strip()
        self.buffer = ""
        return remaining if remaining and len(remaining) > 1 else ""

    def reset(self):
        self.buffer = ""
