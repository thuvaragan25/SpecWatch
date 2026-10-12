from app.auth.membership import MembershipChecker
from app.services.document_service import DocumentService


def test_member_can_retrieve_documents():
    membership = MembershipChecker()
    service = DocumentService(membership)
    docs = service.get_documents("user-1", "proj-1")
    assert docs
