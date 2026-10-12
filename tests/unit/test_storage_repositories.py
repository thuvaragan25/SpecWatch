from pathlib import Path

from specwatch.domain.enums import PassageType, RequirementStatus
from specwatch.domain.models import Requirement, SourceLocation
from specwatch.storage.db import get_connection
from specwatch.storage.repositories import RequirementRepository


def _make_requirement(req_id: str = "REQ-ABC123") -> Requirement:
    return Requirement(
        id=req_id,
        title="Invoice Approval",
        statement="All invoices must be approved.",
        passage_type=PassageType.REQUIREMENT,
        status=RequirementStatus.ACTIVE,
        source=SourceLocation(file="prd.md", line_start=5, line_end=7),
    )


def test_save_and_get_roundtrip(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / "specwatch.db")
    repo = RequirementRepository(conn)
    original = _make_requirement()

    repo.save(original)
    fetched = repo.get(original.id)

    assert fetched == original


def test_get_unknown_id_returns_none(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / "specwatch.db")
    repo = RequirementRepository(conn)
    assert repo.get("REQ-NOPE00") is None


def test_save_is_idempotent_upsert(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / "specwatch.db")
    repo = RequirementRepository(conn)
    requirement = _make_requirement()

    repo.save(requirement)
    updated = requirement.model_copy(update={"title": "Updated Title"})
    repo.save(updated)

    assert repo.get(requirement.id).title == "Updated Title"
    assert len(repo.list()) == 1


def test_list_filters_by_status(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / "specwatch.db")
    repo = RequirementRepository(conn)
    repo.save(_make_requirement("REQ-ACTIVE"))
    repo.save(
        _make_requirement("REQ-DEPREC").model_copy(
            update={"status": RequirementStatus.DEPRECATED}
        )
    )

    active = repo.list(status=RequirementStatus.ACTIVE)
    assert [r.id for r in active] == ["REQ-ACTIVE"]
    assert len(repo.list()) == 2


def test_db_path_parent_directory_is_created(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "dir" / "specwatch.db"
    conn = get_connection(db_path)
    assert db_path.exists()
    conn.close()
