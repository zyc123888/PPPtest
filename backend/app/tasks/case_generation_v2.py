"""Public Celery entry point for case generation V2.

The implementation lives in :mod:`case_generation_v2_pipeline`.  This module
keeps the historical import and Celery task path stable while the pipeline is
split into deterministic utilities and typed stage boundaries.
"""

from __future__ import annotations

import sys
from types import ModuleType

from app.tasks.case_generation_v2_pipeline import engine as _engine
from app.tasks.case_generation_v2_pipeline import artifacts as _artifacts
from app.tasks.case_generation_v2_pipeline.stages import delivery_impl as _delivery_impl
from app.tasks.case_generation_v2_pipeline.stages import requirement_impl as _requirement_impl
from app.tasks.case_generation_v2_pipeline.stages import scope_impl as _scope_impl
from app.tasks.case_generation_v2_pipeline.stages import testcase_impl as _testcase_impl


_PATCH_ALIASES = {
    "_trusted_artifact_record": ((_artifacts, "artifact_record"),),
}
_PATCH_MODULES = (_scope_impl, _requirement_impl, _testcase_impl, _delivery_impl)


class _CompatibilityModule(ModuleType):
    """Forward legacy private imports and test patches to the pipeline engine."""

    def __getattr__(self, name: str):
        return getattr(_engine, name)

    def __setattr__(self, name: str, value) -> None:
        if name.startswith("__") or name == "_engine" or not hasattr(_engine, name):
            super().__setattr__(name, value)
            return
        setattr(_engine, name, value)
        for module in _PATCH_MODULES:
            if hasattr(module, name):
                setattr(module, name, value)
        for module, target_name in _PATCH_ALIASES.get(name, ()):
            setattr(module, target_name, value)

    def __dir__(self) -> list[str]:
        return sorted(set(super().__dir__()) | set(dir(_engine)))


sys.modules[__name__].__class__ = _CompatibilityModule
