from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class DeliveryStageInput:
    scope_index: dict
    requirement_handoff: dict
    testcase_handoff: dict
    api_key: str
    model: str
    base_url: str
    image_links: list[str] | None = None
    downloaded_images: list[dict] | None = None
    image_analysis: list[dict] | None = None


@dataclass(frozen=True)
class DeliveryStageResult:
    testcase_gate: dict
    review_report: dict
    passed: bool


def run_delivery_stage(
    stage_input: DeliveryStageInput,
    *,
    rebuild_delivery: Callable[..., tuple[dict, dict]],
) -> DeliveryStageResult:
    testcase_gate, review_report = rebuild_delivery(
        stage_input.scope_index,
        stage_input.requirement_handoff,
        stage_input.testcase_handoff,
        api_key=stage_input.api_key,
        model=stage_input.model,
        base_url=stage_input.base_url,
        image_links=stage_input.image_links,
        downloaded_images=stage_input.downloaded_images,
        image_analysis=stage_input.image_analysis,
    )
    return DeliveryStageResult(
        testcase_gate=testcase_gate,
        review_report=review_report,
        passed=bool(testcase_gate.get("passed")),
    )
