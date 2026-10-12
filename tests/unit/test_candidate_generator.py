from specwatch.mapping.candidate_generator import BM25Index, Document, tokenize


def test_tokenize_splits_snake_case() -> None:
    assert tokenize("send_invoice") == ["send", "invoice"]


def test_tokenize_splits_camel_case() -> None:
    assert tokenize("InvoiceService") == ["invoice", "service"]


def test_tokenize_splits_dotted_qualified_names() -> None:
    assert tokenize("app.services.invoice_service.InvoiceService") == [
        "app",
        "services",
        "invoice",
        "service",
        "invoice",
        "service",
    ]


def test_tokenize_empty_string() -> None:
    assert tokenize("") == []


def test_bm25_ranks_relevant_document_first() -> None:
    # BM25's IDF formula degenerates on tiny/uniform corpora (a term in
    # exactly half the documents scores IDF=0), so this needs enough
    # varied filler documents for the ranking signal to be meaningful.
    index = BM25Index(
        [
            Document(id="a", text="InvoiceService coordinates invoice approval and delivery"),
            Document(id="b", text="PostmarkClient wraps the postmark email api"),
            Document(id="c", text="UserRepository stores user records in the database"),
            Document(id="d", text="CacheManager evicts stale cache entries periodically"),
            Document(id="e", text="Logger writes structured log lines to stdout"),
        ]
    )
    results = index.search("invoice approval")
    assert results
    assert results[0][0] == "a"


def test_bm25_empty_corpus_returns_no_results() -> None:
    index = BM25Index([])
    assert index.search("anything") == []


def test_bm25_no_token_overlap_returns_no_results() -> None:
    index = BM25Index([Document(id="a", text="completely unrelated content here")])
    assert index.search("invoice approval") == []


def test_bm25_respects_limit() -> None:
    documents = [
        Document(id="a", text="invoice approval workflow one"),
        Document(id="b", text="invoice approval workflow two"),
        Document(id="c", text="unrelated database migration script"),
        Document(id="d", text="unrelated logging configuration"),
        Document(id="e", text="unrelated cache eviction policy"),
    ]
    index = BM25Index(documents)
    assert len(index.search("invoice approval", limit=1)) == 1
