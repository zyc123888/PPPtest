from app.permissions import project_role_allows


def test_project_role_policy_orders_roles_without_global_role_leakage() -> None:
    assert project_role_allows("viewer", "viewer")
    assert not project_role_allows("viewer", "member")
    assert project_role_allows("member", "member")
    assert not project_role_allows("member", "manager")
    assert project_role_allows("manager", "member")
    assert project_role_allows("owner", "manager")
    assert not project_role_allows("admin", "viewer")
    assert not project_role_allows("unknown", "viewer")
