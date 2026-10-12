from specwatch.domain.enums import PassageType, SymbolKind
from specwatch.domain.models import CodeSymbol, Requirement, SourceLocation
from specwatch.mapping.stale_spec import extract_numbers, has_constant_value_mismatch


def _constant(signature: str) -> CodeSymbol:
    return CodeSymbol(
        qualified_name="pkg.TOKEN_TTL_MINUTES",
        kind=SymbolKind.CONSTANT,
        name="TOKEN_TTL_MINUTES",
        file="pkg.py",
        source=SourceLocation(file="pkg.py", line_start=1, line_end=1),
        signature=signature,
        body_hash="h",
    )


def _requirement(statement: str) -> Requirement:
    return Requirement(
        id="REQ-1",
        title="T",
        statement=statement,
        passage_type=PassageType.REQUIREMENT,
        source=SourceLocation(file="prd.md", line_start=1, line_end=1),
    )


def test_extract_numbers_finds_integers_and_decimals() -> None:
    assert extract_numbers("retry up to 3 times, wait 1.5 seconds") == {3.0, 1.5}


def test_extract_numbers_empty_when_no_digits() -> None:
    assert extract_numbers("no numbers here") == set()


def test_mismatch_true_when_numbers_disjoint() -> None:
    constant = _constant("60")
    requirement = _requirement("Password reset tokens shall expire after 30 minutes.")
    assert has_constant_value_mismatch(constant, requirement) is True


def test_mismatch_false_when_numbers_match() -> None:
    constant = _constant("30")
    requirement = _requirement("Password reset tokens shall expire after 30 minutes.")
    assert has_constant_value_mismatch(constant, requirement) is False


def test_mismatch_false_when_requirement_has_no_number() -> None:
    constant = _constant("60")
    requirement = _requirement("Password reset tokens must eventually expire.")
    assert has_constant_value_mismatch(constant, requirement) is False


def test_mismatch_false_when_constant_has_no_signature() -> None:
    constant = _constant("60").model_copy(update={"signature": None})
    requirement = _requirement("Password reset tokens shall expire after 30 minutes.")
    assert has_constant_value_mismatch(constant, requirement) is False
