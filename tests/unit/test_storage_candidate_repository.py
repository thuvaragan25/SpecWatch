from pathlib import Path

from specwatch.domain.enums import CandidateMethod
from specwatch.domain.models import RequirementCandidate, RequirementTestCandidate
from specwatch.storage.db import get_connection
from specwatch.storage.repositories import CandidateRepository


def test_replace_and_fetch_symbol_candidates(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / "specwatch.db")
    repo = CandidateRepository(conn)
    candidates = [
        RequirementCandidate(
            requirement_id="REQ-1", symbol_qualified_name="pkg.Foo", score=1.5, method=CandidateMethod.LEXICAL
        ),
        RequirementCandidate(
            requirement_id="REQ-1", symbol_qualified_name="pkg.Bar", score=0.5, method=CandidateMethod.LEXICAL
        ),
    ]

    repo.replace_symbol_candidates("REQ-1", candidates)
    fetched = repo.symbol_candidates_for_requirement("REQ-1")

    assert [c.symbol_qualified_name for c in fetched] == ["pkg.Foo", "pkg.Bar"]  # ordered by score desc


def test_replace_symbol_candidates_clears_old_rows(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / "specwatch.db")
    repo = CandidateRepository(conn)
    repo.replace_symbol_candidates(
        "REQ-1",
        [
            RequirementCandidate(
                requirement_id="REQ-1", symbol_qualified_name="pkg.Old", score=1.0, method=CandidateMethod.LEXICAL
            )
        ],
    )
    repo.replace_symbol_candidates(
        "REQ-1",
        [
            RequirementCandidate(
                requirement_id="REQ-1", symbol_qualified_name="pkg.New", score=1.0, method=CandidateMethod.LEXICAL
            )
        ],
    )

    fetched = repo.symbol_candidates_for_requirement("REQ-1")
    assert [c.symbol_qualified_name for c in fetched] == ["pkg.New"]


def test_requirements_for_symbol_reverse_lookup(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / "specwatch.db")
    repo = CandidateRepository(conn)
    repo.replace_symbol_candidates(
        "REQ-1",
        [
            RequirementCandidate(
                requirement_id="REQ-1", symbol_qualified_name="pkg.Foo", score=1.0, method=CandidateMethod.LEXICAL
            )
        ],
    )
    repo.replace_symbol_candidates(
        "REQ-2",
        [
            RequirementCandidate(
                requirement_id="REQ-2", symbol_qualified_name="pkg.Foo", score=2.0, method=CandidateMethod.LEXICAL
            )
        ],
    )

    results = repo.requirements_for_symbol("pkg.Foo")
    assert [c.requirement_id for c in results] == ["REQ-2", "REQ-1"]


def test_replace_and_fetch_test_candidates(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / "specwatch.db")
    repo = CandidateRepository(conn)
    repo.replace_test_candidates(
        "REQ-1",
        [
            RequirementTestCandidate(
                requirement_id="REQ-1",
                test_qualified_name="tests.test_foo",
                score=1.0,
                method=CandidateMethod.STATIC_ANALYSIS,
            )
        ],
    )

    fetched = repo.test_candidates_for_requirement("REQ-1")
    assert fetched[0].test_qualified_name == "tests.test_foo"
    assert fetched[0].method == CandidateMethod.STATIC_ANALYSIS
