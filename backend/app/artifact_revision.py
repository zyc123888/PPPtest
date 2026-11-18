from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def revision_from_bytes(file_name: str | None, content: bytes) -> str:
    if file_name and file_name.lower().endswith(".json"):
        try:
            return hashlib.sha256(_canonical_json_bytes(json.loads(content))).hexdigest()
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
    return hashlib.sha256(content).hexdigest()


def artifact_revision(
    *,
    content_json: dict | list | None = None,
    file_name: str | None = None,
    file_path: str | None = None,
) -> str | None:
    if content_json is not None:
        return hashlib.sha256(_canonical_json_bytes(content_json)).hexdigest()
    if not file_path:
        return None
    path = Path(file_path)
    try:
        if path.suffix.lower() == ".json":
            return revision_from_bytes(file_name or path.name, path.read_bytes())
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
    except OSError:
        return None
