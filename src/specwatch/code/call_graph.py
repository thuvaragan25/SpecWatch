"""Best-effort resolution of call expressions to qualified symbol names.

This is a syntactic, not semantic, resolver (see plan.md's Static Analysis
Feasibility discussion). It resolves: ``self.method()`` / ``cls.method()``
direct dispatch, ``self.<typed_attr>.method()`` via constructor
dependency-injection type hints, module-qualified calls after ``import``/
``from ... import``, and same-module bare-name calls.

Everything else -- dynamic dispatch, calls through untyped local
variables, monkeypatching, decorator-rebound behavior -- is left
unresolved (``resolved=False``) rather than guessed. An unresolved call is
evidence that something *might* be there; treating it as "no caller
exists" would be the single biggest source of false positives this
architecture is exposed to.
"""

from typing import TYPE_CHECKING

from specwatch.code.python_parser import ParsedModule, RawCall
from specwatch.domain.enums import SymbolKind
from specwatch.domain.models import CallEdge

if TYPE_CHECKING:
    from specwatch.code.symbol_index import SymbolIndex


def resolve_calls(parsed_modules: list[ParsedModule], index: "SymbolIndex") -> list[CallEdge]:
    """Resolve every call collected across ``parsed_modules`` against ``index``."""
    attribute_types: dict[str, dict[str, str]] = {}
    for module in parsed_modules:
        attribute_types.update(module.attribute_types)

    edges: list[CallEdge] = []
    for module in parsed_modules:
        import_map = {binding.local_name: binding.target for binding in module.imports}
        for call in module.calls:
            qualified = _resolve_one(call, module, import_map, index, attribute_types)
            edges.append(
                CallEdge(
                    caller_qualified_name=call.caller_qualified_name,
                    callee_reference=call.callee_expression,
                    callee_qualified_name=qualified,
                    resolved=qualified is not None,
                    source=call.source,
                )
            )
    return edges


def _resolve_one(
    call: RawCall,
    module: ParsedModule,
    import_map: dict[str, str],
    index: "SymbolIndex",
    attribute_types: dict[str, dict[str, str]],
) -> str | None:
    parts = call.callee_expression.split(".")
    if not parts or not all(p.isidentifier() for p in parts):
        return None

    if parts[0] in ("self", "cls"):
        return _resolve_self_call(call, parts, index, attribute_types, module, import_map)

    if parts[0] in import_map:
        candidate = ".".join([import_map[parts[0]], *parts[1:]])
        return candidate if index.get(candidate) is not None else None

    same_module_candidate = ".".join([module.module_qualified_name, *parts])
    if index.get(same_module_candidate) is not None:
        return same_module_candidate

    return None


def _resolve_self_call(
    call: RawCall,
    parts: list[str],
    index: "SymbolIndex",
    attribute_types: dict[str, dict[str, str]],
    module: ParsedModule,
    import_map: dict[str, str],
) -> str | None:
    caller_symbol = index.get(call.caller_qualified_name)
    if caller_symbol is None or caller_symbol.kind != SymbolKind.METHOD:
        return None
    enclosing_class = call.caller_qualified_name.rsplit(".", 1)[0]

    if len(parts) == 2:
        candidate = ".".join([enclosing_class, parts[1]])
        return candidate if index.get(candidate) is not None else None

    if len(parts) == 3:
        attr_name, method_name = parts[1], parts[2]
        annotation = attribute_types.get(enclosing_class, {}).get(attr_name)
        if annotation is None:
            return None
        attr_type_qualified = _resolve_type_reference(annotation, module, import_map)
        candidate = f"{attr_type_qualified}.{method_name}"
        return candidate if index.get(candidate) is not None else None

    return None


def _resolve_type_reference(annotation: str, module: ParsedModule, import_map: dict[str, str]) -> str:
    parts = annotation.split(".")
    if parts[0] in import_map:
        return ".".join([import_map[parts[0]], *parts[1:]])
    return ".".join([module.module_qualified_name, *parts])
