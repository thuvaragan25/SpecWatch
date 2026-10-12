"""Serves project documents to authorized members."""

from app.auth.membership import MembershipChecker


class DocumentService:
    """Retrieves documents for a project, enforcing membership."""

    def __init__(self, membership: MembershipChecker) -> None:
        self.membership = membership

    def get_documents(self, user_id: str, project_id: str) -> list[str]:
        """Return a project's documents if the user is a member."""
        if not self.membership.is_member(user_id, project_id):
            raise PermissionError("not a project member")
        return self._fetch(project_id)

    def _fetch(self, project_id: str) -> list[str]:
        return [f"{project_id}/doc1.txt", f"{project_id}/doc2.txt"]
