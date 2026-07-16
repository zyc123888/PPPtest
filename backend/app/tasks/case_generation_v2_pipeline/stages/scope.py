from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class ScopeStageInput:
    markdown_text: str
    image_analysis: list[dict]
    api_key: str
    model: str
    base_url: str
    progress_callback: Callable[[str], None] | None = field(default=None, repr=False)


@dataclass(frozen=True)
class ScopeStageResult:
    scope_index: dict
    source_count: int


def run_scope_stage(
    stage_input: ScopeStageInput,
    *,
    build_scope_index: Callable[..., dict],
) -> ScopeStageResult:
    scope_index = build_scope_index(
        stage_input.markdown_text,
        stage_input.image_analysis,
        api_key=stage_input.api_key,
        model=stage_input.model,
        base_url=stage_input.base_url,
        progress_callback=stage_input.progress_callback,
    )
    sources = scope_index.get("direct_testcase_sources") or scope_index.get("source_blocks") or []
    return ScopeStageResult(scope_index=scope_index, source_count=len(sources))
