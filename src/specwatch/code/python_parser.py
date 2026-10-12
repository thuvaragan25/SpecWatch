"""Per-file Python AST parsing.

Produces symbols, raw (unresolved) call references, import bindings, and
constructor-attribute type hints for a single module. Cross-module call
resolution happens later in ``call_graph.py`` once every module in the
repository has been parsed.
"""

import ast
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from specwatch.domain.enums import SymbolKind
from specwatch.domain.models import CodeSymbol, SourceLocation


@dataclass(frozen=True)
class RawCall:
    """A call expression found in one module, not yet resolved."""

    caller_qualified_name: str
    callee_expression: str
    source: SourceLocation


@dataclass(frozen=True)
class ImportBinding:
    """Maps a name local to this module to the dotted path it refers to."""

    local_name: str
    target: str


@dataclass
class ParsedModule:
    module_qualified_name: str
    file: str
    symbols: list[CodeSymbol]
    calls: list[RawCall]
    imports: list[ImportBinding]
    # class_qualified_name -> {attribute_name: type_annotation_text}, derived
    # from typed __init__ parameters assigned straight onto self.<attr>.
    attribute_types: dict[str, dict[str, str]] = field(default_factory=dict)


def module_qualified_name(rel_path: Path) -> str:
    """Compute a dotted module path from a path already relative to the repo root."""
    stem_path = rel_path.with_suffix("")
    parts = list(stem_path.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else rel_path.stem


def parse_module(source: str, file: str, module_name: str) -> ParsedModule:
    """Parse one module's source into symbols, calls, and imports."""
    tree = ast.parse(source, filename=file)
    lines = source.splitlines()
    module_line_end = max(len(lines), 1)

    module_symbol = CodeSymbol(
        qualified_name=module_name,
        kind=SymbolKind.MODULE,
        name=module_name.rsplit(".", 1)[-1] if module_name else file,
        file=file,
        source=SourceLocation(file=file, line_start=1, line_end=module_line_end),
        signature=None,
        docstring=ast.get_docstring(tree),
        decorators=[],
        body_hash=_hash_node(tree),
    )

    visitor = _SymbolVisitor(module_name=module_name, file=file)
    for stmt in tree.body:
        visitor.visit(stmt)

    return ParsedModule(
        module_qualified_name=module_name,
        file=file,
        symbols=[module_symbol, *visitor.symbols],
        calls=visitor.calls,
        imports=visitor.imports,
        attribute_types=visitor.attribute_types,
    )


class _SymbolVisitor(ast.NodeVisitor):
    def __init__(self, module_name: str, file: str) -> None:
        self.module_name = module_name
        self.file = file
        self.symbols: list[CodeSymbol] = []
        self.calls: list[RawCall] = []
        self.imports: list[ImportBinding] = []
        self.attribute_types: dict[str, dict[str, str]] = {}
        self._scope_stack: list[str] = [module_name]
        self._scope_kind_stack: list[str] = ["module"]

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.asname:
                self.imports.append(ImportBinding(local_name=alias.asname, target=alias.name))
            else:
                top = alias.name.split(".")[0]
                self.imports.append(ImportBinding(local_name=top, target=top))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level:
            base = self._relative_import_base(node.level)
            if base is None:
                return
            prefix = ".".join(part for part in (base, node.module) if part)
        elif node.module is None:
            return
        else:
            prefix = node.module
        for alias in node.names:
            local = alias.asname or alias.name
            target = f"{prefix}.{alias.name}" if prefix else alias.name
            self.imports.append(ImportBinding(local_name=local, target=target))

    def _relative_import_base(self, level: int) -> str | None:
        """Dotted package a ``level``-dot relative import is anchored to,
        or ``None`` if it climbs above the repository root."""
        parts = self.module_name.split(".")
        if not self.file.endswith("__init__.py"):
            parts = parts[:-1]
        climb = level - 1
        if climb > len(parts):
            return None
        return ".".join(parts[: len(parts) - climb])

    def visit_Assign(self, node: ast.Assign) -> None:
        self._maybe_record_constant(node, targets=node.targets, value=node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self._maybe_record_constant(node, targets=[node.target], value=node.value)
        self.generic_visit(node)

    def _maybe_record_constant(
        self, node: ast.Assign | ast.AnnAssign, targets: list[ast.expr], value: ast.expr
    ) -> None:
        """Module- and class-level ``NAME = <literal>`` assignments become
        CONSTANT symbols. Assignments inside function bodies are local
        variables, not symbols, and are ignored."""
        if self._scope_kind_stack[-1] not in ("module", "class"):
            return
        if not _is_literal_expr(value):
            return
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            qualified = f"{self._scope_stack[-1]}.{target.id}"
            self.symbols.append(
                CodeSymbol(
                    qualified_name=qualified,
                    kind=SymbolKind.CONSTANT,
                    name=target.id,
                    file=self.file,
                    source=SourceLocation(
                        file=self.file,
                        line_start=node.lineno,
                        line_end=node.end_lineno or node.lineno,
                    ),
                    signature=_safe_unparse(value),
                    docstring=None,
                    decorators=[],
                    body_hash=_hash_node(node),
                )
            )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)

        qualified = f"{self._scope_stack[-1]}.{node.name}"
        self.symbols.append(_build_symbol(node, qualified, self.file, SymbolKind.CLASS))
        self.attribute_types[qualified] = _extract_attribute_types(node)

        self._scope_stack.append(qualified)
        self._scope_kind_stack.append("class")
        for stmt in node.body:
            self.visit(stmt)
        self._scope_kind_stack.pop()
        self._scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in [*node.args.defaults, *node.args.kw_defaults]:
            if default is not None:
                self.visit(default)

        parent_kind = self._scope_kind_stack[-1]
        kind = SymbolKind.METHOD if parent_kind == "class" else SymbolKind.FUNCTION
        qualified = f"{self._scope_stack[-1]}.{node.name}"
        self.symbols.append(_build_symbol(node, qualified, self.file, kind))

        self._scope_stack.append(qualified)
        self._scope_kind_stack.append("function")
        for stmt in node.body:
            self.visit(stmt)
        self._scope_kind_stack.pop()
        self._scope_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        try:
            expression = ast.unparse(node.func)
        except Exception:
            expression = "<unresolvable>"
        self.calls.append(
            RawCall(
                caller_qualified_name=self._scope_stack[-1],
                callee_expression=expression,
                source=SourceLocation(
                    file=self.file,
                    line_start=node.lineno,
                    line_end=node.end_lineno or node.lineno,
                ),
            )
        )
        self.generic_visit(node)


def _extract_attribute_types(class_node: ast.ClassDef) -> dict[str, str]:
    """Map ``self.<attr>`` names to their static type, from a typed
    ``__init__`` (``self.attr = typed_param``) or an explicit
    ``self.attr: Type = ...`` annotation."""
    init_node = next(
        (
            n
            for n in class_node.body
            if isinstance(n, ast.FunctionDef) and n.name == "__init__"
        ),
        None,
    )
    if init_node is None:
        return {}

    param_types: dict[str, str] = {}
    for arg in [*init_node.args.args, *init_node.args.kwonlyargs]:
        if arg.annotation is not None:
            try:
                param_types[arg.arg] = ast.unparse(arg.annotation)
            except Exception:  # noqa: BLE001 - best-effort static analysis
                continue

    attribute_types: dict[str, str] = {}
    for stmt in init_node.body:
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and _is_self_attribute(stmt.targets[0])
            and isinstance(stmt.value, ast.Name)
            and stmt.value.id in param_types
        ):
            attribute_types[stmt.targets[0].attr] = param_types[stmt.value.id]  # type: ignore[union-attr]
        elif isinstance(stmt, ast.AnnAssign) and _is_self_attribute(stmt.target):
            try:
                attribute_types[stmt.target.attr] = ast.unparse(stmt.annotation)  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001 - best-effort static analysis
                continue
    return attribute_types


def _is_literal_expr(node: ast.expr) -> bool:
    """A plain literal, or a unary +/- applied to one (e.g. ``-1``).
    Deliberately narrow for V1 -- no tuples/lists/dicts, no expressions."""
    if isinstance(node, ast.Constant):
        return True
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, (ast.USub, ast.UAdd))
        and isinstance(node.operand, ast.Constant)
    ):
        return True
    return False


def _is_self_attribute(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    )


def _build_symbol(
    node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
    qualified_name: str,
    file: str,
    kind: SymbolKind,
) -> CodeSymbol:
    signature = _signature(node) if kind in (SymbolKind.FUNCTION, SymbolKind.METHOD) else None
    return CodeSymbol(
        qualified_name=qualified_name,
        kind=kind,
        name=node.name,
        file=file,
        source=SourceLocation(
            file=file, line_start=node.lineno, line_end=node.end_lineno or node.lineno
        ),
        signature=signature,
        docstring=ast.get_docstring(node),
        decorators=[_safe_unparse(d) for d in node.decorator_list],
        body_hash=_hash_node(node),
    )


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    args = ast.unparse(node.args)
    returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"{prefix} {node.name}({args}){returns}"


def _hash_node(node: ast.AST) -> str:
    try:
        normalized = ast.unparse(node)
    except Exception:
        normalized = ast.dump(node)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _safe_unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return "<unparseable>"
