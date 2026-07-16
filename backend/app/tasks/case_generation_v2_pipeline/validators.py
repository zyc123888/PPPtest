from __future__ import annotations

import re


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_xmindmark(text: str) -> None:
    lines = text.splitlines()
    if not lines:
        raise ValueError("XMindMark 内容为空")
    if lines[0].startswith("- "):
        raise ValueError("XMindMark 第一行必须是根节点纯文本")
    for index, line in enumerate(lines[1:], start=2):
        if not line.strip():
            raise ValueError(f"XMindMark 第 {index} 行为空行")
        if not line.startswith("- ") and not re.match(r"^(  )+- ", line):
            raise ValueError(f"XMindMark 第 {index} 行不是标准列表节点")
        indent = len(line) - len(line.lstrip(" "))
        if indent % 2 != 0:
            raise ValueError(f"XMindMark 第 {index} 行缩进不是 2 空格倍数")
        if line.lstrip().startswith("#"):
            raise ValueError(f"XMindMark 第 {index} 行不能使用 Markdown 标题")


def count_xmindmark_nodes(text: str, prefix: str) -> int:
    separator = r"(?:[：:｜\s]|$)" if prefix == "SRC" else r"(?:[：:\s-]|$)"
    pattern = re.compile(rf"^\s*-\s+({re.escape(prefix)}-[A-Za-z0-9_-]+){separator}")
    return len(
        {
            match.group(1)
            for line in text.splitlines()
            for match in [pattern.match(line)]
            if match
        }
    )


def count_xmindmark_testcase_nodes(text: str) -> int:
    return count_xmindmark_nodes(text, "TC")


def count_xmindmark_source_nodes(text: str) -> int:
    return count_xmindmark_nodes(text, "SRC")


def count_xmindmark_function_point_nodes(text: str) -> int:
    return count_xmindmark_nodes(text, "FP")
