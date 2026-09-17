from src.ingestion import VectorDBIngestor
from src.reranking import LLMReranker


def test_embedding_error_log_does_not_contain_source_text(tmp_path):
    secret_text = "confidential enterprise document content"
    log_path = tmp_path / "embedding_error.log"

    VectorDBIngestor._write_safe_embedding_error(
        str(log_path),
        [secret_text],
        0,
        "empty embedding",
    )

    logged = log_path.read_text(encoding="utf-8")
    assert secret_text not in logged
    assert "text_length=" in logged
    assert "text_sha256_prefix=" in logged


def test_missing_rerank_diagnostic_does_not_print_source_text(monkeypatch, capsys):
    secret_text = "confidential source paragraph that must not reach stdout"
    reranker = LLMReranker(provider="dashscope", model="qwen-turbo")
    monkeypatch.setattr(
        reranker,
        "get_rank_for_multiple_blocks",
        lambda query, texts: {"block_rankings": []},
    )

    reranker.rerank_documents(
        "query",
        [{"text": secret_text, "distance": 0.5, "page": 7}],
        documents_batch_size=2,
    )

    output = capsys.readouterr().out
    assert secret_text not in output
    assert "Text length:" in output
    assert "SHA256 prefix:" in output
