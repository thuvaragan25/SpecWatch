"""Deterministic numeric-mismatch signal for stale-spec detection.

Compares a changed CONSTANT symbol's literal value against numbers
mentioned in a candidate requirement's statement (plan.md §3.2's own
TOKEN_TTL_MINUTES example). A mismatch is only a HINT for the agent to
investigate -- never a standalone verdict. A number in the requirement
text may be coincidental or refer to something else entirely; the agent
must confirm the two are actually talking about the same parameter
before concluding the spec is stale. Deliberately scoped to numeric
constants only -- general prose staleness detection is explicitly
"harder" per the plan and out of scope for V1.1.
"""

import re

from specwatch.domain.models import CodeSymbol, Requirement

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def extract_numbers(text: str) -> set[float]:
    return {float(match) for match in _NUMBER_RE.findall(text)}


def has_constant_value_mismatch(symbol: CodeSymbol, requirement: Requirement) -> bool:
    """True when a changed constant's literal value shares no number with
    the requirement's statement, but the requirement DOES mention at
    least one number -- suggesting (not proving) they describe the same
    parameter."""
    if symbol.signature is None:
        return False
    code_numbers = extract_numbers(symbol.signature)
    spec_numbers = extract_numbers(requirement.statement)
    if not code_numbers or not spec_numbers:
        return False
    return code_numbers.isdisjoint(spec_numbers)
