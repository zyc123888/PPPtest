from __future__ import annotations

import os
import re
from pathlib import Path

from app.tasks.case_generation_common import convert_xmindmark_to_xmind, write_xmind_archive

from .artifacts import ensure_output_dir_writable
from .validators import validate_xmindmark


SAFE_FILENAME_PATTERN = re.compile(r'[\\/:*?"<>|]+')


def sanitize_file_stem(value: str | None, fallback: str = "testcases") -> str:
    raw = (value or fallback).strip() or fallback
    stem = Path(raw).stem if Path(raw).suffix else raw
    stem = SAFE_FILENAME_PATTERN.sub("_", stem).strip(" ._")
    return stem[:120] or fallback


def clean_node_text(value) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").replace("\t", " ").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:260] or "-"


def append_node(lines: list[str], depth: int, text: str) -> None:
    lines.append(f"{'  ' * depth}- {clean_node_text(text)}")


def write_xmind_file(xmind_path: str, xmindmark_text: str) -> str:
    validate_xmindmark(xmindmark_text)
    return write_xmind_archive(xmind_path, xmindmark_text)


def convert_xmindmark(output_dir: str, xmindmark_file_path: str, output_stem: str) -> str:
    ensure_output_dir_writable(output_dir)
    normalized_stem = sanitize_file_stem(output_stem, fallback="trusted_v2_testcases")
    return convert_xmindmark_to_xmind(output_dir, xmindmark_file_path, normalized_stem)
