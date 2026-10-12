from pathlib import Path

from specwatch.code.symbol_index import build_symbol_index
from specwatch.domain.enums import CandidateMethod
from specwatch.domain.models import RequirementCandidate
from specwatch.mapping.requirement_mapper import expand_candidates_via_callers


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_enforcer_that_raises_a_named_exception_becomes_a_candidate(tmp_path: Path) -> None:
    _write(tmp_path, "lib/__init__.py", "")
    _write(tmp_path, "lib/exceptions.py", "class ExpiredError(Exception):\n    pass\n")
    _write(
        tmp_path,
        "lib/api.py",
        "from .exceptions import ExpiredError\n\n"
        "def check(exp, now):\n    if exp <= now:\n        raise ExpiredError('x')\n",
    )
    _write(
        tmp_path,
        "lib/test_api.py",
        "from .exceptions import ExpiredError\n\ndef test_it():\n    raise ExpiredError('x')\n",
    )
    index = build_symbol_index(tmp_path)
    lexical = [
        RequirementCandidate(
            requirement_id="REQ-1",
            symbol_qualified_name="lib.exceptions.ExpiredError",
            score=10.0,
            method=CandidateMethod.LEXICAL,
        )
    ]

    expanded = expand_candidates_via_callers(lexical, index)

    by_name = {c.symbol_qualified_name: c for c in expanded}
    assert by_name["lib.exceptions.ExpiredError"].method == CandidateMethod.LEXICAL
    assert by_name["lib.api.check"].method == CandidateMethod.STATIC_ANALYSIS
    assert by_name["lib.api.check"].score < 10.0
    assert not any("test_api" in name for name in by_name)
