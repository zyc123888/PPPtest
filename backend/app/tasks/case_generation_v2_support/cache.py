from __future__ import annotations

import hashlib
import json
from typing import Any


CACHE_CONTRACT_VERSION = "trusted-shard-cache-v1"


def stable_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def can_reuse_trusted_scope_index(
    previous_scope_index: dict | None,
    previous_source_manifest: dict | None,
    current_source_manifest: dict,
    previous_scope_gate: dict | None,
    *,
    generation_contract_version: str,
) -> bool:
    return bool(
        previous_scope_index
        and previous_scope_index.get("generation_contract_version") == generation_contract_version
        and previous_source_manifest
        and previous_source_manifest.get("content_sha256") == current_source_manifest.get("content_sha256")
        and previous_source_manifest.get("unified_rules_sha256") == current_source_manifest.get("unified_rules_sha256")
        and (previous_scope_gate or {}).get("passed")
    )


def can_reuse_trusted_requirement(
    previous_requirement_handoff: dict | None,
    scope_fingerprint: str,
    previous_requirement_gate: dict | None,
    *,
    generation_contract_version: str,
) -> bool:
    return bool(
        previous_requirement_handoff
        and previous_requirement_handoff.get("generation_contract_version") == generation_contract_version
        and previous_requirement_handoff.get("scope_fingerprint") == scope_fingerprint
        and (previous_requirement_gate or {}).get("passed")
    )


def build_shard_cache_metadata(
    source: dict,
    function_points: list[dict],
    *,
    rules_sha256: str | None,
    model: str,
    generation_contract_version: str,
    generation_density: str,
) -> dict:
    source_payload = {
        "source_id": source.get("source_id"),
        "source_content_sha256": source.get("source_content_sha256"),
        "source_excerpt": source.get("source_excerpt"),
        "title_path": source.get("title_path"),
        "primary_sections": source.get("primary_sections") or [],
        "dependency_sections": source.get("dependency_sections") or [],
        "rule_clusters": source.get("rule_clusters") or [],
        "source_state_semantics": source.get("source_state_semantics") or {},
        "image_refs": source.get("image_refs") or [],
    }
    profile_payload = source.get("test_design_profile") or {}
    fp_payload = [
        {
            "fp_id": item.get("fp_id"),
            "source_id": item.get("source_id"),
            "title": item.get("title"),
            "description": item.get("description"),
            "rules": item.get("rules") or [],
            "test_hints": item.get("test_hints") or [],
            "priority_hint": item.get("priority_hint"),
        }
        for item in function_points
        if isinstance(item, dict)
    ]
    metadata = {
        "cache_contract_version": CACHE_CONTRACT_VERSION,
        "generation_contract_version": generation_contract_version,
        "generation_density": generation_density,
        "model": model,
        "rules_sha256": rules_sha256,
        "source_sha256": stable_sha256(source_payload),
        "function_points_sha256": stable_sha256(fp_payload),
        "test_design_profile_sha256": stable_sha256(profile_payload),
    }
    metadata["reuse_fingerprint"] = stable_sha256(metadata)
    return metadata


def shard_cache_mismatch(cached_shard: dict, expected_metadata: dict) -> list[str]:
    cached = cached_shard.get("cache_metadata")
    if not isinstance(cached, dict):
        return ["missing_cache_metadata"]
    keys = (
        "cache_contract_version",
        "generation_contract_version",
        "generation_density",
        "model",
        "rules_sha256",
        "source_sha256",
        "function_points_sha256",
        "test_design_profile_sha256",
        "reuse_fingerprint",
    )
    return [key for key in keys if cached.get(key) != expected_metadata.get(key)]
