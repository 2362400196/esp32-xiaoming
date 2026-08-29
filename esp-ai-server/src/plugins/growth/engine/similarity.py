"""文本相似度工具（自学习 / 用户画像去重共用）"""
from __future__ import annotations

import re


def text_similarity(a: str, b: str) -> float:
    """字符 bigram 相似度：Jaccard 与包含度取较高者，用于内容去重。"""
    def bigrams(text: str) -> set:
        text = re.sub(r"\s+", "", text)
        if len(text) < 2:
            return {text} if text else set()
        return {text[i:i + 2] for i in range(len(text) - 1)}

    ga, gb = bigrams(a), bigrams(b)
    if not ga or not gb:
        return 0.0
    union = ga | gb
    jaccard = len(ga & gb) / len(union) if union else 0.0
    containment = len(ga & gb) / len(ga) if ga else 0.0
    return max(jaccard, containment)
