from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class RequirementStageInput:
    scope_index: dict
    markdown_text: str
    image_analysis: list[dict]
    api_key: str
    model: str
    base_url: str
    progress_callback: Callable[[str], None] | None = field(default=None, repr=False)


@dataclass(frozen=True)
class RequirementStageResult:
    requirement_handoff: dict
    function_point_count: int


def run_requirement_stage(
    stage_input: RequirementStageInput,
    *,
    build_requirement_handoff: Callable[..., dict],
) -> RequirementStageResult:
    handoff = build_requirement_handoff(
        stage_input.scope_index,
        stage_input.markdown_text,
        stage_input.image_analysis,
        api_key=stage_input.api_key,
        model=stage_input.model,
        base_url=stage_input.base_url,
        progress_callback=stage_input.progress_callback,
    )
    return RequirementStageResult(
        requirement_handoff=handoff,
        function_point_count=len(handoff.get("function_points") or []),
    )
