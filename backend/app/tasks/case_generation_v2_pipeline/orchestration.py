from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .normalizers import normalize_pipeline_mode


@dataclass(frozen=True)
class PipelineDispatchInput:
    job_id: int
    pipeline_mode: str | None
    resume_from_stage: str | None = None


def dispatch_pipeline(
    dispatch_input: PipelineDispatchInput,
    *,
    run_lite: Callable[[int], None],
    run_trusted: Callable[[int], None],
    resume_trusted_from_testcase_gate: Callable[[int], None],
) -> None:
    mode = normalize_pipeline_mode(dispatch_input.pipeline_mode)
    if mode == "lite":
        run_lite(dispatch_input.job_id)
        return
    if str(dispatch_input.resume_from_stage or "").strip() == "testcase_gate":
        resume_trusted_from_testcase_gate(dispatch_input.job_id)
        return
    run_trusted(dispatch_input.job_id)
