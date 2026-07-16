from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class TestcaseStageInput:
    scope_index: dict
    requirement_handoff: dict
    api_key: str
    model: str
    base_url: str
    previous_handoff: dict | None = None
    progress_callback: Callable[[str], None] | None = field(default=None, repr=False)


@dataclass(frozen=True)
class TestcaseStageResult:
    testcase_handoff: dict
    testcase_count: int
    failed_source_count: int


def run_testcase_stage(
    stage_input: TestcaseStageInput,
    *,
    build_testcase_handoff: Callable[..., dict],
) -> TestcaseStageResult:
    handoff = build_testcase_handoff(
        stage_input.scope_index,
        stage_input.requirement_handoff,
        api_key=stage_input.api_key,
        model=stage_input.model,
        base_url=stage_input.base_url,
        existing_testcase_handoff=stage_input.previous_handoff,
        progress_callback=stage_input.progress_callback,
    )
    failed_sources = handoff.get("failed_sources") or []
    return TestcaseStageResult(
        testcase_handoff=handoff,
        testcase_count=len(handoff.get("testcases") or []),
        failed_source_count=len(failed_sources),
    )
