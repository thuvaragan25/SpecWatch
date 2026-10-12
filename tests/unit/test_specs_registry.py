from specwatch.specs.registry import stable_requirement_id


def test_same_inputs_produce_same_id() -> None:
    id_a = stable_requirement_id("prd.md", "Invoice Approval", "All invoices must be approved.")
    id_b = stable_requirement_id("prd.md", "Invoice Approval", "All invoices must be approved.")
    assert id_a == id_b


def test_id_format() -> None:
    result = stable_requirement_id("prd.md", "Heading", "Statement.")
    assert result.startswith("REQ-")
    assert len(result) == len("REQ-") + 6


def test_different_statement_produces_different_id() -> None:
    id_a = stable_requirement_id("prd.md", "Heading", "Statement A.")
    id_b = stable_requirement_id("prd.md", "Heading", "Statement B.")
    assert id_a != id_b


def test_different_document_produces_different_id() -> None:
    id_a = stable_requirement_id("prd.md", "Heading", "Statement.")
    id_b = stable_requirement_id("architecture.md", "Heading", "Statement.")
    assert id_a != id_b


def test_whitespace_and_case_do_not_affect_id() -> None:
    id_a = stable_requirement_id("prd.md", "Heading", "Statement text.")
    id_b = stable_requirement_id(" prd.md ", "HEADING", "  statement   text.  ")
    assert id_a == id_b
