from specwatch.domain.enums import SymbolKind
from specwatch.code.python_parser import parse_module


def test_module_symbol_is_always_present() -> None:
    parsed = parse_module("x = 1\n", file="a.py", module_name="pkg.a")
    module_symbols = [s for s in parsed.symbols if s.kind == SymbolKind.MODULE]
    assert len(module_symbols) == 1
    assert module_symbols[0].qualified_name == "pkg.a"


def test_function_symbol_has_signature_and_docstring() -> None:
    source = (
        "def greet(name: str, *, loud: bool = False) -> str:\n"
        '    """Say hello."""\n'
        "    return name\n"
    )
    parsed = parse_module(source, file="a.py", module_name="pkg.a")
    func = next(s for s in parsed.symbols if s.kind == SymbolKind.FUNCTION)
    assert func.qualified_name == "pkg.a.greet"
    assert func.name == "greet"
    assert func.signature == "def greet(name: str, *, loud: bool=False) -> str"
    assert func.docstring == "Say hello."


def test_class_and_method_qualified_names() -> None:
    source = "class Foo:\n" "    def bar(self) -> None:\n" "        pass\n"
    parsed = parse_module(source, file="a.py", module_name="pkg.a")
    kinds = {s.qualified_name: s.kind for s in parsed.symbols}
    assert kinds["pkg.a.Foo"] == SymbolKind.CLASS
    assert kinds["pkg.a.Foo.bar"] == SymbolKind.METHOD


def test_nested_function_gets_its_own_symbol() -> None:
    source = "def outer():\n" "    def inner():\n" "        pass\n" "    return inner\n"
    parsed = parse_module(source, file="a.py", module_name="pkg.a")
    qualified_names = {s.qualified_name for s in parsed.symbols}
    assert "pkg.a.outer" in qualified_names
    assert "pkg.a.outer.inner" in qualified_names


def test_decorators_are_captured() -> None:
    source = "class Foo:\n" "    @property\n" "    def bar(self):\n" "        return 1\n"
    parsed = parse_module(source, file="a.py", module_name="pkg.a")
    bar = next(s for s in parsed.symbols if s.qualified_name == "pkg.a.Foo.bar")
    assert bar.decorators == ["property"]


def test_body_hash_ignores_comments_and_whitespace() -> None:
    a = parse_module("def f():\n    return 1\n", file="a.py", module_name="pkg.a")
    b = parse_module("def f():\n    # a comment\n    return 1  \n", file="a.py", module_name="pkg.a")
    func_a = next(s for s in a.symbols if s.qualified_name == "pkg.a.f")
    func_b = next(s for s in b.symbols if s.qualified_name == "pkg.a.f")
    assert func_a.body_hash == func_b.body_hash


def test_body_hash_changes_on_behavior_change() -> None:
    a = parse_module("def f():\n    return 1\n", file="a.py", module_name="pkg.a")
    b = parse_module("def f():\n    return 2\n", file="a.py", module_name="pkg.a")
    func_a = next(s for s in a.symbols if s.qualified_name == "pkg.a.f")
    func_b = next(s for s in b.symbols if s.qualified_name == "pkg.a.f")
    assert func_a.body_hash != func_b.body_hash


def test_calls_are_attributed_to_enclosing_function() -> None:
    source = "def outer():\n" "    helper()\n"
    parsed = parse_module(source, file="a.py", module_name="pkg.a")
    assert len(parsed.calls) == 1
    call = parsed.calls[0]
    assert call.caller_qualified_name == "pkg.a.outer"
    assert call.callee_expression == "helper"


def test_module_level_call_attributed_to_module() -> None:
    parsed = parse_module("do_setup()\n", file="a.py", module_name="pkg.a")
    assert parsed.calls[0].caller_qualified_name == "pkg.a"


def test_call_in_argument_expression_is_also_captured() -> None:
    source = "def outer():\n" "    outer_call(inner_call())\n"
    parsed = parse_module(source, file="a.py", module_name="pkg.a")
    expressions = {c.callee_expression for c in parsed.calls}
    assert expressions == {"outer_call", "inner_call"}


def test_import_bindings() -> None:
    source = (
        "import os\n"
        "import app.services.invoice_service\n"
        "import app.services.invoice_service as inv\n"
        "from app.providers import postmark_client\n"
        "from app.providers.postmark_client import PostmarkClient as PMC\n"
        "from . import sibling\n"
        "from .exceptions import Boom\n"
        "from ..core import util\n"
    )
    parsed = parse_module(source, file="a.py", module_name="pkg.a")
    bindings = {b.local_name: b.target for b in parsed.imports}
    assert bindings["os"] == "os"
    assert bindings["app"] == "app"
    assert bindings["inv"] == "app.services.invoice_service"
    assert bindings["postmark_client"] == "app.providers.postmark_client"
    assert bindings["PMC"] == "app.providers.postmark_client.PostmarkClient"
    assert bindings["sibling"] == "pkg.sibling"
    assert bindings["Boom"] == "pkg.exceptions.Boom"
    assert bindings["util"] == "core.util"


def test_constructor_attribute_types_from_typed_init_param() -> None:
    source = (
        "class Foo:\n"
        "    def __init__(self, delivery: InvoiceDeliveryService) -> None:\n"
        "        self.delivery = delivery\n"
    )
    parsed = parse_module(source, file="a.py", module_name="pkg.a")
    assert parsed.attribute_types["pkg.a.Foo"] == {"delivery": "InvoiceDeliveryService"}


def test_constructor_attribute_types_from_explicit_annotation() -> None:
    source = "class Foo:\n" "    def __init__(self, x) -> None:\n" "        self.delivery: Delivery = x\n"
    parsed = parse_module(source, file="a.py", module_name="pkg.a")
    assert parsed.attribute_types["pkg.a.Foo"] == {"delivery": "Delivery"}


def test_class_without_init_has_no_attribute_types() -> None:
    parsed = parse_module("class Foo:\n    pass\n", file="a.py", module_name="pkg.a")
    assert parsed.attribute_types["pkg.a.Foo"] == {}


def test_module_level_constant_is_extracted() -> None:
    parsed = parse_module("TOKEN_TTL_MINUTES = 30\n", file="a.py", module_name="pkg.a")
    constant = next(s for s in parsed.symbols if s.kind == SymbolKind.CONSTANT)
    assert constant.qualified_name == "pkg.a.TOKEN_TTL_MINUTES"
    assert constant.signature == "30"


def test_class_level_constant_is_extracted() -> None:
    source = "class Foo:\n    MAX_RETRIES = 3\n"
    parsed = parse_module(source, file="a.py", module_name="pkg.a")
    constant = next(s for s in parsed.symbols if s.kind == SymbolKind.CONSTANT)
    assert constant.qualified_name == "pkg.a.Foo.MAX_RETRIES"
    assert constant.signature == "3"


def test_negative_literal_constant_is_extracted() -> None:
    parsed = parse_module("DEFAULT_OFFSET = -1\n", file="a.py", module_name="pkg.a")
    constant = next(s for s in parsed.symbols if s.kind == SymbolKind.CONSTANT)
    assert constant.signature == "-1"


def test_annotated_constant_is_extracted() -> None:
    parsed = parse_module("MAX_SIZE: int = 100\n", file="a.py", module_name="pkg.a")
    constant = next(s for s in parsed.symbols if s.kind == SymbolKind.CONSTANT)
    assert constant.qualified_name == "pkg.a.MAX_SIZE"
    assert constant.signature == "100"


def test_local_variable_inside_function_is_not_a_constant_symbol() -> None:
    source = "def f():\n    x = 1\n    return x\n"
    parsed = parse_module(source, file="a.py", module_name="pkg.a")
    assert not any(s.kind == SymbolKind.CONSTANT for s in parsed.symbols)


def test_non_literal_assignment_is_not_a_constant_symbol() -> None:
    parsed = parse_module("CONFIG = load_config()\n", file="a.py", module_name="pkg.a")
    assert not any(s.kind == SymbolKind.CONSTANT for s in parsed.symbols)
    # the call itself is still tracked
    assert parsed.calls[0].callee_expression == "load_config"


def test_constant_body_hash_changes_when_value_changes() -> None:
    a = parse_module("TTL = 30\n", file="a.py", module_name="pkg.a")
    b = parse_module("TTL = 60\n", file="a.py", module_name="pkg.a")
    const_a = next(s for s in a.symbols if s.kind == SymbolKind.CONSTANT)
    const_b = next(s for s in b.symbols if s.kind == SymbolKind.CONSTANT)
    assert const_a.body_hash != const_b.body_hash


def test_relative_imports_in_package_init_anchor_to_the_package() -> None:
    parsed = parse_module("from .exceptions import Boom\n", file="pkg/__init__.py", module_name="pkg")
    assert {b.local_name: b.target for b in parsed.imports} == {"Boom": "pkg.exceptions.Boom"}
