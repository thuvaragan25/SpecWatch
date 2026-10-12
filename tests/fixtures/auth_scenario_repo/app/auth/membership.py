"""Project membership checks."""

_PROJECT_MEMBERS = {"proj-1": {"user-1", "user-2"}}


class MembershipChecker:
    """Checks whether a user belongs to a project."""

    def is_member(self, user_id: str, project_id: str) -> bool:
        return user_id in _PROJECT_MEMBERS.get(project_id, set())
