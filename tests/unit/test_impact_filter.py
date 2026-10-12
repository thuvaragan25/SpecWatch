from pathlib import Path

from specwatch.domain.enums import CandidateMethod, SymbolChangeType
from specwatch.domain.models import ChangedSymbol, RequirementCandidate
from specwatch.impact_filter import filter_changed_symbols, symbols_requiring_investigation
from specwatch.storage.db import get_connection
from specwatch.storage.repositories import CandidateRepository


def _candidate_repo(tmp_path: Path) -> CandidateRepository:
    conn = get_connection(tmp_path / "specwatch.db")
    return CandidateRepository(conn)


def test_no_candidate_relationship_means_skip(tmp_path: Path) -> None:
    candidate_repo = _candidate_repo(tmp_path)
    changed = ChangedSymbol(qualified_name="pkg.unrelated", change_type=SymbolChangeType.MODIFIED)

    decisions = filter_changed_symbols([changed], candidate_repo)

    assert decisions[0].should_investigate is False
    assert decisions[0].candidate_requirements == []
    assert symbols_requiring_investigation(decisions) == []


def test_candidate_relationship_means_investigate(tmp_path: Path) -> None:
    candidate_repo = _candidate_repo(tmp_path)
    candidate_repo.replace_symbol_candidates(
        "REQ-1",
        [
            RequirementCandidate(
                requirement_id="REQ-1",
                symbol_qualified_name="pkg.relevant",
                score=1.0,
                method=CandidateMethod.LEXICAL,
            )
        ],
    )
    changed = ChangedSymbol(qualified_name="pkg.relevant", change_type=SymbolChangeType.MODIFIED)

    decisions = filter_changed_symbols([changed], candidate_repo)

    assert decisions[0].should_investigate is True
    assert [c.requirement_id for c in decisions[0].candidate_requirements] == ["REQ-1"]


def test_multiple_changed_symbols_decided_independently(tmp_path: Path) -> None:
    candidate_repo = _candidate_repo(tmp_path)
    candidate_repo.replace_symbol_candidates(
        "REQ-1",
        [
            RequirementCandidate(
                requirement_id="REQ-1", symbol_qualified_name="pkg.a", score=1.0, method=CandidateMethod.LEXICAL
            )
        ],
    )
    changed = [
        ChangedSymbol(qualified_name="pkg.a", change_type=SymbolChangeType.MODIFIED),
        ChangedSymbol(qualified_name="pkg.b", change_type=SymbolChangeType.MODIFIED),
    ]

    decisions = filter_changed_symbols(changed, candidate_repo)

    investigate = symbols_requiring_investigation(decisions)
    assert [d.changed_symbol.qualified_name for d in investigate] == ["pkg.a"]
    assert len(decisions) == 2


def test_class_is_skipped_when_one_of_its_members_also_changed(tmp_path: Path) -> None:
    from specwatch.domain.enums import SymbolKind
    from specwatch.domain.models import CodeSymbol, SourceLocation

    candidate_repo = _candidate_repo(tmp_path)
    for name in ("pkg.Foo", "pkg.Foo.bar"):
        candidate_repo.replace_symbol_candidates(
            f"REQ-{name}",
            [RequirementCandidate(requirement_id=f"REQ-{name}", symbol_qualified_name=name, score=1.0, method=CandidateMethod.LEXICAL)],
        )

    def _symbol(name: str, kind: SymbolKind) -> CodeSymbol:
        return CodeSymbol(
            qualified_name=name, kind=kind, name=name.rsplit(".", 1)[-1], file="pkg.py",
            source=SourceLocation(file="pkg.py", line_start=1, line_end=2), body_hash="h",
        )

    changed = [
        ChangedSymbol(qualified_name="pkg.Foo", change_type=SymbolChangeType.MODIFIED, head_symbol=_symbol("pkg.Foo", SymbolKind.CLASS)),
        ChangedSymbol(qualified_name="pkg.Foo.bar", change_type=SymbolChangeType.MODIFIED, head_symbol=_symbol("pkg.Foo.bar", SymbolKind.METHOD)),
    ]

    decisions = filter_changed_symbols(changed, candidate_repo)

    assert [d.changed_symbol.qualified_name for d in symbols_requiring_investigation(decisions)] == ["pkg.Foo.bar"]


def test_class_with_no_changed_member_is_still_investigated(tmp_path: Path) -> None:
    from specwatch.domain.enums import SymbolKind
    from specwatch.domain.models import CodeSymbol, SourceLocation

    candidate_repo = _candidate_repo(tmp_path)
    candidate_repo.replace_symbol_candidates(
        "REQ-1",
        [RequirementCandidate(requirement_id="REQ-1", symbol_qualified_name="pkg.Foo", score=1.0, method=CandidateMethod.LEXICAL)],
    )
    cls = CodeSymbol(
        qualified_name="pkg.Foo", kind=SymbolKind.CLASS, name="Foo", file="pkg.py",
        source=SourceLocation(file="pkg.py", line_start=1, line_end=2), body_hash="h",
    )
    changed = [ChangedSymbol(qualified_name="pkg.Foo", change_type=SymbolChangeType.MODIFIED, head_symbol=cls)]

    assert len(symbols_requiring_investigation(filter_changed_symbols(changed, candidate_repo))) == 1
