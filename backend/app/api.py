"""API 路由聚合入口。

具体路由实现已按领域拆分至 ``app.routers.*``，共享鉴权与领域逻辑分别位于
``app.deps.*`` 与 ``app.domain.*``。本文件负责汇总 ``public_router`` 与
``protected_router``，并保留核心兼容导出。
"""

from fastapi import APIRouter, Depends

from app.deps.auth import (  # noqa: F401
    _accessible_project_ids,
    _can_access_project,
    _can_access_workspace,
    _dispatch_task_or_run_inline,
    _ensure_workspace_owner_guard,
    _guard_project_member_change,
    _is_project_member,
    _project_has_members,
    _require_project_access,
    _require_project_member,
    _require_workspace_access,
    _resolve_project_role,
    _serialize_user,
    _workspace_ids_for_user,
    auth_scheme,
    get_current_user,
    require_admin,
    require_tester,
)
from app.domain.case_generation import _inherit_case_generation_v2_artifacts  # noqa: F401
from app.domain.cases import (  # noqa: F401
    _load_case_entity,
    _normalize_case_type,
    _record_case_history,
)
from app.routers import (
    auth as auth_routers,
    case_generation_v1,
    case_generation_v2,
    cases_api,
    cases_perf,
    cases_ui,
    cases_unified,
    environments,
    executions,
    projects,
    reports_defects,
    test_plans,
    workspaces,
)
from app.routers.system import (  # noqa: F401
    _health_response,
    _mock_path_matches,
    _normalize_mock_path,
    mock_service,
    register_admin_system_routes,
    system_health,
    system_health_live,
    system_health_ready,
    system_info,
    system_protected_router,
    system_public_router,
)
from app.routers.tools import tools_router

public_router = APIRouter()
protected_router = APIRouter(dependencies=[Depends(get_current_user)])

public_router.include_router(system_public_router)
public_router.include_router(auth_routers.public_router)
public_router.include_router(reports_defects.public_router)

protected_router.include_router(system_protected_router)
protected_router.include_router(tools_router)
register_admin_system_routes(protected_router, require_admin)

protected_router.include_router(auth_routers.protected_router)
protected_router.include_router(auth_routers.users_router)
protected_router.include_router(workspaces.router)
protected_router.include_router(projects.router)
# Keep unified routes (/api-cases/import-spec etc.) ahead of /{case_id} routes.
protected_router.include_router(cases_unified.router)
protected_router.include_router(cases_api.router)
protected_router.include_router(cases_ui.router)
protected_router.include_router(cases_perf.router)
protected_router.include_router(case_generation_v1.router)
protected_router.include_router(case_generation_v2.router)
protected_router.include_router(environments.router)
protected_router.include_router(test_plans.router)
protected_router.include_router(executions.router)
protected_router.include_router(reports_defects.router)
protected_router.include_router(reports_defects.defects_router)
