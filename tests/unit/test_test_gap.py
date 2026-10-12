from specwatch.domain.enums import CandidateMethod, PassageType
from specwatch.domain.models import Requirement, RequirementTestCandidate, SourceLocation
from specwatch.mapping.test_gap import has_negative_case_language, has_test_evidence_gap


def _requirement(statement: str) -> Requirement:
    return Requirement(
        id="REQ-1",
        title="T",
        statement=statement,
        passage_type=PassageType.REQUIREMENT,
        source=SourceLocation(file="prd.md", line_start=1, line_end=1),
    )


def _candidate() -> RequirementTestCandidate:
    return RequirementTestCandidate(
        requirement_id="REQ-1", test_qualified_name="tests.test_a", score=1.0, method=CandidateMethod.LEXICAL
    )


def test_detects_various_negation_phrasings() -> None:
    assert has_negative_case_language("Non-members may not read project documents.")
    assert has_negative_case_language("The system must deny access to unauthorized users.")
    assert has_negative_case_language("Users who are not a member cannot retrieve documents.")


def test_does_not_flag_purely_affirmative_statement() -> None:
    assert not has_negative_case_language("Members may retrieve project documents.")


def test_gap_signal_true_when_negative_language_and_no_tests() -> None:
    requirement = _requirement("Non-members may not read project documents.")
    assert has_test_evidence_gap(requirement, []) is True


def test_gap_signal_false_when_tests_exist() -> None:
    requirement = _requirement("Non-members may not read project documents.")
    assert has_test_evidence_gap(requirement, [_candidate()]) is False


def test_gap_signal_false_when_no_negative_language() -> None:
    requirement = _requirement("Members may retrieve project documents.")
    assert has_test_evidence_gap(requirement, []) is False
