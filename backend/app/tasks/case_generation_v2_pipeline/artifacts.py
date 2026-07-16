from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Callable

import yaml
from sqlalchemy import select

from app.models import CaseGenerationV2Artifact
from app.tasks.case_generation_runtime import current_attempt_id


logger = logging.getLogger(__name__)


def ensure_writable_dir(path: str) -> str:
    try:
        os.makedirs(path, exist_ok=True)
        os.chmod(path, 0o777)
    except PermissionError:
        pass
    except OSError as exc:
        logger.warning("unable to set directory permissions %s: %s", path, exc)
    return path


def ensure_output_dir_writable(output_dir: str) -> str:
    ensure_writable_dir(output_dir)
    if not os.access(output_dir, os.W_OK):
        raise PermissionError(f"输出目录不可写：{output_dir}")
    return output_dir


def make_writable_file(path: str) -> str:
    try:
        os.chmod(path, 0o666)
    except OSError as exc:
        logger.debug("unable to chmod generated file %s: %s", path, exc)
    return path


def atomic_replace_file(file_path: str, write_callback: Callable[[str], None]) -> str:
    output_dir = ensure_output_dir_writable(os.path.dirname(file_path))
    base_name = os.path.basename(file_path)
    temp_path = os.path.join(output_dir, f".{base_name}.tmp.{os.getpid()}")
    try:
        write_callback(temp_path)
        make_writable_file(temp_path)
        os.replace(temp_path, file_path)
        return make_writable_file(file_path)
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError as exc:
                logger.warning("unable to remove temporary file %s: %s", temp_path, exc)


def write_text_file(output_dir: str, file_name: str, content: str) -> str:
    file_path = os.path.join(output_dir, file_name)

    def write(path: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)

    return atomic_replace_file(file_path, write)


def write_json_file(output_dir: str, file_name: str, payload: dict | list) -> str:
    file_path = os.path.join(output_dir, file_name)

    def write(path: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)

    return atomic_replace_file(file_path, write)


def write_yaml_file(output_dir: str, file_name: str, payload: dict | list) -> str:
    file_path = os.path.join(output_dir, file_name)

    def write(path: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=False)

    return atomic_replace_file(file_path, write)


def read_text_if_exists(path: Path, limit: int = 12000) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[:limit]


def upsert_artifact(
    db,
    *,
    job_id: int,
    artifact_type: str,
    file_name: str | None = None,
    file_path: str | None = None,
    content_json: dict | list | None = None,
) -> None:
    attempt_id = current_attempt_id()
    filters = [
        CaseGenerationV2Artifact.job_id == job_id,
        CaseGenerationV2Artifact.artifact_type == artifact_type,
    ]
    if attempt_id is not None:
        filters.append(CaseGenerationV2Artifact.attempt_id == attempt_id)
    artifact = db.scalar(select(CaseGenerationV2Artifact).where(*filters))
    if artifact is None:
        db.add(
            CaseGenerationV2Artifact(
                job_id=job_id,
                attempt_id=attempt_id,
                artifact_type=artifact_type,
                file_name=file_name,
                file_path=file_path,
                content_json=content_json,
            )
        )
        return
    artifact.file_name = file_name
    artifact.file_path = file_path
    artifact.content_json = content_json
    artifact.expired_at = None


def persist_artifact(
    db,
    job_id: int,
    output_dir: str,
    artifact_type: str,
    file_name: str,
    payload: dict | list | str,
) -> str:
    if isinstance(payload, str):
        file_path = write_text_file(output_dir, file_name, payload)
        content_json = None
    else:
        file_path = write_json_file(output_dir, file_name, payload)
        content_json = payload
    upsert_artifact(
        db,
        job_id=job_id,
        artifact_type=artifact_type,
        file_name=file_name,
        file_path=file_path,
        content_json=content_json,
    )
    db.commit()
    return file_path


def artifact_record(
    db,
    job_id: int,
    artifact_type: str,
    *,
    allow_previous: bool = False,
) -> CaseGenerationV2Artifact | None:
    attempt_id = current_attempt_id()
    stmt = select(CaseGenerationV2Artifact).where(
        CaseGenerationV2Artifact.job_id == job_id,
        CaseGenerationV2Artifact.artifact_type == artifact_type,
    )
    if attempt_id is not None and not allow_previous:
        stmt = stmt.where(CaseGenerationV2Artifact.attempt_id == attempt_id)
    return db.scalar(stmt.order_by(CaseGenerationV2Artifact.id.desc()))


def artifact_content(db, job_id: int, artifact_type: str, *, allow_previous: bool = False) -> dict:
    artifact = artifact_record(db, job_id, artifact_type, allow_previous=allow_previous)
    if artifact is None or not isinstance(artifact.content_json, dict):
        raise ValueError(f"缺少可信模式产物：{artifact_type}")
    return artifact.content_json


def optional_artifact_content(
    db,
    job_id: int,
    artifact_type: str,
    *,
    allow_previous: bool = False,
) -> dict | None:
    artifact = artifact_record(db, job_id, artifact_type, allow_previous=allow_previous)
    if artifact is None or not isinstance(artifact.content_json, dict):
        return None
    return artifact.content_json


def artifact_text(db, job_id: int, artifact_type: str) -> str:
    artifact = artifact_record(db, job_id, artifact_type)
    if artifact is None:
        return ""
    if isinstance(artifact.content_json, dict) and isinstance(artifact.content_json.get("text"), str):
        return artifact.content_json["text"]
    if artifact.file_path and os.path.exists(artifact.file_path):
        return Path(artifact.file_path).read_text(encoding="utf-8", errors="replace")
    return ""


def artifact_json_payload(db, job_id: int, artifact_type: str) -> dict:
    artifact = artifact_record(db, job_id, artifact_type)
    if artifact is None:
        return {}
    if isinstance(artifact.content_json, dict):
        return artifact.content_json
    if artifact.file_path and os.path.exists(artifact.file_path):
        try:
            loaded = json.loads(Path(artifact.file_path).read_text(encoding="utf-8", errors="replace"))
            return loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}
    return {}
