"""Shared project-role policy helpers."""

PROJECT_ROLE_RANK = {"viewer": 0, "member": 1, "manager": 2, "owner": 3}


def project_role_allows(role: str, minimum_role: str) -> bool:
    """Return whether a project role meets the requested minimum role."""
    if role not in PROJECT_ROLE_RANK or minimum_role not in PROJECT_ROLE_RANK:
        return False
    return PROJECT_ROLE_RANK[role] >= PROJECT_ROLE_RANK[minimum_role]
