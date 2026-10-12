from specwatch.code.python_parser import parse_module
from specwatch.code.symbol_index import SymbolIndex
from specwatch.code.call_graph import resolve_calls


def _index_of(*parsed_modules) -> SymbolIndex:
    index = SymbolIndex()
    for module in parsed_modules:
        for symbol in module.symbols:
            index.symbols[symbol.qualified_name] = symbol
    index.call_edges = resolve_calls(list(parsed_modules), index)
    return index


def test_self_method_call_resolves() -> None:
    source = (
        "class Foo:\n"
        "    def a(self):\n"
        "        self.b()\n"
        "    def b(self):\n"
        "        pass\n"
    )
    module = parse_module(source, file="a.py", module_name="pkg.a")
    index = _index_of(module)
    edge = index.call_edges[0]
    assert edge.resolved
    assert edge.callee_qualified_name == "pkg.a.Foo.b"


def test_module_level_function_call_resolves() -> None:
    source = "def a():\n    b()\n\n\ndef b():\n    pass\n"
    module = parse_module(source, file="a.py", module_name="pkg.a")
    index = _index_of(module)
    edge = next(e for e in index.call_edges if e.callee_reference == "b")
    assert edge.resolved
    assert edge.callee_qualified_name == "pkg.a.b"


def test_cross_module_import_call_resolves() -> None:
    lib = parse_module("def helper():\n    pass\n", file="lib.py", module_name="pkg.lib")
    main = parse_module(
        "from pkg.lib import helper\n\n\ndef run():\n    helper()\n",
        file="main.py",
        module_name="pkg.main",
    )
    index = _index_of(lib, main)
    edge = next(e for e in index.call_edges if e.callee_reference == "helper")
    assert edge.resolved
    assert edge.callee_qualified_name == "pkg.lib.helper"


def test_call_through_untyped_local_variable_is_unresolved() -> None:
    lib = parse_module("class Foo:\n    def bar(self):\n        pass\n", file="lib.py", module_name="pkg.lib")
    main = parse_module(
        "from pkg.lib import Foo\n\n\ndef run():\n    instance = Foo()\n    instance.bar()\n",
        file="main.py",
        module_name="pkg.main",
    )
    index = _index_of(lib, main)
    bar_call = next(e for e in index.call_edges if e.callee_reference == "instance.bar")
    assert not bar_call.resolved
    assert bar_call.callee_qualified_name is None


def test_self_attr_method_call_resolves_via_constructor_type_hint() -> None:
    delivery_module = parse_module(
        "class Delivery:\n    def send(self):\n        pass\n",
        file="delivery.py",
        module_name="pkg.delivery",
    )
    service_module = parse_module(
        "from pkg.delivery import Delivery\n\n\n"
        "class Service:\n"
        "    def __init__(self, delivery: Delivery) -> None:\n"
        "        self.delivery = delivery\n"
        "    def run(self):\n"
        "        self.delivery.send()\n",
        file="service.py",
        module_name="pkg.service",
    )
    index = _index_of(delivery_module, service_module)
    edge = next(e for e in index.call_edges if e.callee_reference == "self.delivery.send")
    assert edge.resolved
    assert edge.callee_qualified_name == "pkg.delivery.Delivery.send"


def test_self_attr_method_call_without_type_hint_is_unresolved() -> None:
    service_module = parse_module(
        "class Service:\n"
        "    def __init__(self, delivery) -> None:\n"
        "        self.delivery = delivery\n"
        "    def run(self):\n"
        "        self.delivery.send()\n",
        file="service.py",
        module_name="pkg.service",
    )
    index = _index_of(service_module)
    edge = next(e for e in index.call_edges if e.callee_reference == "self.delivery.send")
    assert not edge.resolved


def test_builtin_call_is_unresolved() -> None:
    module = parse_module("def f():\n    len([1, 2])\n", file="a.py", module_name="pkg.a")
    index = _index_of(module)
    edge = next(e for e in index.call_edges if e.callee_reference == "len")
    assert not edge.resolved
