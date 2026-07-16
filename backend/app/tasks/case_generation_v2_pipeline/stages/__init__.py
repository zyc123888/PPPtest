"""Typed boundaries for the trusted V2 pipeline stages."""

from .delivery import DeliveryStageInput, DeliveryStageResult, run_delivery_stage
from .requirement import RequirementStageInput, RequirementStageResult, run_requirement_stage
from .scope import ScopeStageInput, ScopeStageResult, run_scope_stage
from .testcase import TestcaseStageInput, TestcaseStageResult, run_testcase_stage

__all__ = [
    "DeliveryStageInput",
    "DeliveryStageResult",
    "RequirementStageInput",
    "RequirementStageResult",
    "ScopeStageInput",
    "ScopeStageResult",
    "TestcaseStageInput",
    "TestcaseStageResult",
    "run_delivery_stage",
    "run_requirement_stage",
    "run_scope_stage",
    "run_testcase_stage",
]
