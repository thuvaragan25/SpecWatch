from specwatch.agent.investigator import build_seed_message
from specwatch.domain.enums import CandidateMethod
from specwatch.domain.models import RequirementCandidate


def _candidate(req_id: str = "REQ-1") -> RequirementCandidate:
    return RequirementCandidate(requirement_id=req_id, symbol_qualified_name="pkg.Foo", score=1.0, method=CandidateMethod.LEXICAL)


def test_seed_message_lists_changed_symbols_and_candidates() -> None:
    message = build_seed_message(["pkg.Foo.bar"], [_candidate()])
    assert "pkg.Foo.bar" in message
    assert "REQ-1" in message


def test_seed_message_includes_test_gap_hint_when_flagged() -> None:
    message = build_seed_message(["pkg.Foo.bar"], [_candidate()], test_gap_hints={"REQ-1": True})
    assert "test_evidence_gap" in message
    assert "no candidate test evidence" in message


def test_seed_message_omits_hint_when_not_flagged() -> None:
    message = build_seed_message(["pkg.Foo.bar"], [_candidate()], test_gap_hints={"REQ-1": False})
    assert "test_evidence_gap" not in message


def test_seed_message_includes_stale_spec_hint_when_flagged() -> None:
    message = build_seed_message(["pkg.Foo.bar"], [_candidate()], stale_spec_hints={"REQ-1": True})
    assert "spec_may_be_stale" in message
    assert "doesn't share any number" in message


def test_seed_message_omits_stale_spec_hint_when_not_flagged() -> None:
    message = build_seed_message(["pkg.Foo.bar"], [_candidate()], stale_spec_hints={"REQ-1": False})
    assert "spec_may_be_stale" not in message


def test_seed_message_includes_requirement_text_when_provided() -> None:
    message = build_seed_message(
        ["pkg.Foo.bar"], [_candidate()], requirement_texts={"REQ-1": ("Expiry", "Tokens must expire.")}
    )
    assert "Tokens must expire." in message
    assert "inspect_requirement" in message
