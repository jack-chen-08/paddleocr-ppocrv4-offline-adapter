"""全角/半角统一。

口径（需求原文）：数字、括号、冒号、小数点统一（同一份合同中不出现两种写法）。
中文句读（，；。、！？）与书名号（「」《》【】）保持原样——把它们改成半角会破坏语义。

实现要点：不用整串 NFKC（它会把「，」「；」一起转半角），改为逐字符白名单映射，
再加一条「数字之间的逗号视为千分位」的规则。
"""
from __future__ import annotations

import re

_PUNCT_MAP = {
    "（": "(",
    "）": ")",
    "：": ":",
    "．": ".",
    "％": "%",
    "／": "/",
    "－": "-",
    "＿": "_",
    "\u3000": " ",
}

# 全角数字 / 拉丁字母 -> 半角
for _i in range(10):
    _PUNCT_MAP[chr(0xFF10 + _i)] = str(_i)
for _i in range(26):
    _PUNCT_MAP[chr(0xFF21 + _i)] = chr(ord("A") + _i)
    _PUNCT_MAP[chr(0xFF41 + _i)] = chr(ord("a") + _i)
del _i

_DIGIT = "0-9"
# 数字之间的全角逗号 = 千分位，转半角逗号
_THOUSANDS_COMMA = re.compile(r"(?<=[0-9０-９])[，](?=[0-9０-９])")


def to_halfwidth(text: str) -> str:
    """全角数字/字母/括号/冒号/小数点 -> 半角；中文句读不动。"""
    if not text:
        return ""
    out = "".join(_PUNCT_MAP.get(ch, ch) for ch in text)
    return _THOUSANDS_COMMA.sub(",", out)


def normalize_numbers(text: str) -> str:
    """数字串内部再做一次统一（容错：处理「98 ， 000」这种带空格的千分位）。"""
    return re.sub(r"(?<=[0-9])\s*,\s*(?=[0-9]{3}\b)", ",", text)


def normalize_text(text: str) -> str:
    """对外统一入口。"""
    return normalize_numbers(to_halfwidth(text))


def normalize_line_with_map(text: str) -> tuple[str, list[int]]:
    """归一化并返回「归一化字符 -> 原字符下标」映射（逐字符映射，长度一一对应）。"""
    chars: list[str] = []
    index_map: list[int] = []
    for i, ch in enumerate(text):
        for c in to_halfwidth(ch):
            chars.append(c)
            index_map.append(i)
    return "".join(chars), index_map
