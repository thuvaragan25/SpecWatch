"""Maps tests to the implementation symbols they exercise.

V1 uses only the resolved static call graph -- direct, high-confidence
evidence. Weaker lexical candidate matching between tests and
implementation belongs to the Phase 4 mapping layer, not here.
"""

from specwatch.code.symbol_index import SymbolIndex


def referenced_symbols_for_test(index: SymbolIndex, test_qualified_name: str) -> list[str]:
    """Qualified names this test's body resolves a call to, deduplicated,
    in first-seen order."""
    seen: dict[str, None] = {}
    for edge in index.callees_of(test_qualified_name):
        if edge.resolved and edge.callee_qualified_name:
            seen.setdefault(edge.callee_qualified_name, None)
    return list(seen)
