from pathlib import Path

from specwatch.code.symbol_index import build_symbol_index, discover_python_files
from specwatch.domain.enums import SymbolKind

FIXTURE_ROOT = Path(__file__).parent.parent / "fixtures" / "sample_code_repo"


def test_discover_python_files_skips_pycache(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "a.py").write_text("x = 1\n")
    cache_dir = tmp_path / "app" / "__pycache__"
    cache_dir.mkdir()
    (cache_dir / "a.cpython-312.pyc.py").write_text("junk = 1\n")

    files = discover_python_files(tmp_path)
    assert files == [tmp_path / "app" / "a.py"]


def test_fixture_repo_indexes_all_modules_and_symbols() -> None:
    index = build_symbol_index(FIXTURE_ROOT)

    assert index.get("app.services.invoice_service.InvoiceService") is not None
    invoice_service_send = index.get("app.services.invoice_service.InvoiceService.send")
    assert invoice_service_send is not None
    assert invoice_service_send.kind == SymbolKind.METHOD
    assert invoice_service_send.signature == "def send(self, invoice_id: str) -> None"

    tool_symbol = index.get("app.tools.invoice_tool.send_invoice")
    assert tool_symbol is not None
    assert tool_symbol.kind == SymbolKind.FUNCTION


def test_fixture_repo_resolves_typed_attribute_call_chain() -> None:
    """InvoiceService.send -> self.delivery.deliver, and
    InvoiceDeliveryService.deliver -> self.client.send_email both resolve
    via constructor type hints -- the two hops of the plan's own
    trace_execution_path example that static analysis *can* handle."""
    index = build_symbol_index(FIXTURE_ROOT)

    callees = index.callees_of("app.services.invoice_service.InvoiceService.send")
    deliver_edge = next(e for e in callees if e.callee_reference == "self.delivery.deliver")
    assert deliver_edge.resolved
    assert deliver_edge.callee_qualified_name == "app.services.delivery_service.InvoiceDeliveryService.deliver"

    callees = index.callees_of("app.services.delivery_service.InvoiceDeliveryService.deliver")
    send_email_edge = next(e for e in callees if e.callee_reference == "self.client.send_email")
    assert send_email_edge.resolved
    assert send_email_edge.callee_qualified_name == "app.providers.postmark_client.PostmarkClient.send_email"


def test_fixture_repo_leaves_untyped_local_variable_call_unresolved() -> None:
    """send_invoice() calls `service.send(...)` through an untyped local
    variable -- exactly the case V1 static analysis cannot resolve, and
    must not silently treat as "no caller". This is precisely why the
    agent layer (search_code, inspect_diff) exists on top of this index."""
    index = build_symbol_index(FIXTURE_ROOT)

    callees = index.callees_of("app.tools.invoice_tool.send_invoice")
    send_edge = next(e for e in callees if e.callee_reference == "service.send")
    assert send_edge.resolved is False
    assert send_edge.callee_qualified_name is None


def test_callers_of_finds_the_resolved_edge() -> None:
    index = build_symbol_index(FIXTURE_ROOT)
    callers = index.callers_of("app.services.delivery_service.InvoiceDeliveryService.deliver")
    assert len(callers) == 1
    assert callers[0].caller_qualified_name == "app.services.invoice_service.InvoiceService.send"
