import json

import faiss
import numpy as np
import pytest

from src.ingestion import VectorDBIngestor
from src.retrieval import VectorRetriever
from src.vector_utils import faiss_index_has_unit_norm_vectors, l2_normalize_rows


def test_ingestion_stores_unit_norm_embeddings():
    ingestor = VectorDBIngestor(
        embedding_provider="dashscope",
        embedding_model="text-embedding-v1",
    )
    index = ingestor._create_vector_db([[3.0, 4.0], [5.0, 12.0]])

    norms = [np.linalg.norm(index.reconstruct(i)) for i in range(index.ntotal)]
    assert norms == pytest.approx([1.0, 1.0], abs=1e-6)
    assert faiss_index_has_unit_norm_vectors(index)


def test_query_embedding_normalization_has_unit_norm():
    normalized = l2_normalize_rows([3.0, 4.0])

    assert np.linalg.norm(normalized[0]) == pytest.approx(1.0, abs=1e-6)


def test_zero_embedding_is_rejected():
    with pytest.raises(ValueError, match="zero-length"):
        l2_normalize_rows([[0.0, 0.0]])


def test_legacy_non_normalized_faiss_requires_rebuild(tmp_path):
    vector_dir = tmp_path / "vector_dbs"
    document_dir = tmp_path / "chunked_reports"
    vector_dir.mkdir()
    document_dir.mkdir()

    legacy_index = faiss.IndexFlatIP(2)
    legacy_index.add(np.asarray([[3.0, 4.0]], dtype=np.float32))
    faiss.write_index(legacy_index, str(vector_dir / "doc.faiss"))

    document = {
        "metainfo": {"sha1_name": "doc", "company_name": "Example"},
        "content": {
            "chunks": [{"page": 1, "text": "text"}],
            "pages": [{"page": 1, "text": "text"}],
        },
    }
    (document_dir / "doc.json").write_text(
        json.dumps(document), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="legacy non-normalized"):
        VectorRetriever(vector_dir, document_dir)


def test_retrieval_normalizes_query_before_inner_product_search(tmp_path, monkeypatch):
    vector_dir = tmp_path / "vector_dbs"
    document_dir = tmp_path / "chunked_reports"
    vector_dir.mkdir()
    document_dir.mkdir()

    index = faiss.IndexFlatIP(2)
    index.add(np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32))
    faiss.write_index(index, str(vector_dir / "doc.faiss"))

    document = {
        "metainfo": {"sha1_name": "doc", "company_name": "Example"},
        "content": {
            "chunks": [
                {"page": 1, "text": "x axis"},
                {"page": 2, "text": "y axis"},
            ],
            "pages": [
                {"page": 1, "text": "x axis"},
                {"page": 2, "text": "y axis"},
            ],
        },
    }
    (document_dir / "doc.json").write_text(
        json.dumps(document), encoding="utf-8"
    )

    retriever = VectorRetriever(vector_dir, document_dir)
    monkeypatch.setattr(retriever, "_get_embedding", lambda query: [3.0, 4.0])

    result = retriever.retrieve_by_company_name("Example", "query", top_n=1)

    assert result[0]["page"] == 2
    assert result[0]["distance"] == pytest.approx(0.8, abs=1e-4)
