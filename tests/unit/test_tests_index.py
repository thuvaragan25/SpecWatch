from pathlib import Path

from specwatch.code.symbol_index import build_symbol_index
from specwatch.tests_index.index import build_test_index

FIXTURE_ROOT = Path(__file__).parent.parent / "fixtures" / "sample_code_repo"


def test_fixture_repo_test_is_indexed_with_fixtures_and_assertions() -> None:
    symbol_index = build_symbol_index(FIXTURE_ROOT)
    test_index = build_test_index(FIXTURE_ROOT, symbol_index)

    test = test_index.get("tests.test_invoice_service.test_send_invoice_delivers_via_client")
    assert test is not None
    assert test.fixtures == ["capsys"]
    assert test.assertions == ["'INV-1' in captured.out"]


def test_fixture_repo_test_referenced_symbols_come_from_call_graph() -> None:
    """The test directly instantiates all three services (resolved calls),
    but calls `service.send(...)` through an untyped local variable -- the
    same honest static-analysis limit demonstrated in Phase 2. Only the
    resolved references show up here."""
    symbol_index = build_symbol_index(FIXTURE_ROOT)
    test_index = build_test_index(FIXTURE_ROOT, symbol_index)

    test = test_index.get("tests.test_invoice_service.test_send_invoice_delivers_via_client")
    assert set(test.referenced_symbols) == {
        "app.providers.postmark_client.PostmarkClient",
        "app.services.delivery_service.InvoiceDeliveryService",
        "app.services.invoice_service.InvoiceService",
    }


def test_tests_referencing_finds_the_test_for_a_symbol() -> None:
    symbol_index = build_symbol_index(FIXTURE_ROOT)
    test_index = build_test_index(FIXTURE_ROOT, symbol_index)

    referencing = test_index.tests_referencing("app.services.invoice_service.InvoiceService")
    assert [t.name for t in referencing] == ["test_send_invoice_delivers_via_client"]


def test_non_test_files_are_not_indexed_as_tests() -> None:
    symbol_index = build_symbol_index(FIXTURE_ROOT)
    test_index = build_test_index(FIXTURE_ROOT, symbol_index)

    assert all(t.file.startswith("tests/") for t in test_index.list())
