import json

import faiss
import numpy as np
import pytest

from src.retrieval import VectorRetriever


def _write_document(root, document_id, title, vectors, chunks):
    document_dir = root / "documents"
    vector_dir = root / "vectors"
    document_dir.mkdir(exist_ok=True)
    vector_dir.mkdir(exist_ok=True)

    document = {
        "metainfo": {
            "document_id": document_id,
            "title": title,
            "document_type": "policy",
            "source": f"{document_id}.pdf",
            "source_url": f"https://example.test/{document_id}",
            "category": "safety",
            "tags": ["demo"],
        },
        "content": {
            "chunks": chunks,
            "pages": [
                {
                    "page": page_number,
                    "text": f"{title} full page {page_number}",
                }
                for page_number in sorted({chunk["page"] for chunk in chunks})
            ],
        },
    }
    (document_dir / f"{document_id}.json").write_text(
        json.dumps(document), encoding="utf-8"
    )
    index = faiss.IndexFlatIP(2)
    index.add(np.asarray(vectors, dtype=np.float32))
    faiss.write_index(index, str(vector_dir / f"{document_id}.faiss"))
    return vector_dir, document_dir


def test_generic_retrieval_merges_local_top_k_across_documents(tmp_path, monkeypatch):
    vector_dir, document_dir = _write_document(
        tmp_path,
        "doc-a",
        "Document A",
        [[1.0, 0.0], [0.8, 0.6]],
        [{"page": 1, "text": "A best"}, {"page": 2, "text": "A second"}],
    )
    _write_document(
        tmp_path,
        "doc-b",
        "Document B",
        [[0.9, 0.4358899], [0.0, 1.0]],
        [{"page": 1, "text": "B best"}, {"page": 2, "text": "B second"}],
    )
    retriever = VectorRetriever(vector_dir, document_dir)
    monkeypatch.setattr(retriever, "_get_embedding", lambda query: [1.0, 0.0])

    results = retriever.retrieve("generic question", top_n=2, per_document_top_k=1)

    assert [result["document_id"] for result in results] == ["doc-a", "doc-b"]
    assert [result["text"] for result in results] == ["A best", "B best"]
    assert results[0]["chunk_id"] == "doc-a:0"


def test_parent_page_deduplication_uses_document_and_page(tmp_path, monkeypatch):
    vector_dir, document_dir = _write_document(
        tmp_path,
        "doc-a",
        "Document A",
        [[1.0, 0.0]],
        [{"page": 1, "text": "A chunk"}],
    )
    _write_document(
        tmp_path,
        "doc-b",
        "Document B",
        [[0.8, 0.6]],
        [{"page": 1, "text": "B chunk"}],
    )
    retriever = VectorRetriever(vector_dir, document_dir)
    monkeypatch.setattr(retriever, "_get_embedding", lambda query: [1.0, 0.0])

    results = retriever.retrieve(
        "generic question", top_n=2, per_document_top_k=1, return_parent_pages=True
    )

    assert {(result["document_id"], result["page"]) for result in results} == {
        ("doc-a", 1),
        ("doc-b", 1),
    }
    assert {result["text"] for result in results} == {
        "Document A full page 1",
        "Document B full page 1",
    }


def test_duplicate_document_id_is_rejected(tmp_path):
    vector_dir, document_dir = _write_document(
        tmp_path,
        "same-id",
        "Document A",
        [[1.0, 0.0]],
        [{"page": 1, "text": "A"}],
    )
    duplicate = json.loads((document_dir / "same-id.json").read_text(encoding="utf-8"))
    (document_dir / "different-file.json").write_text(
        json.dumps(duplicate), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="Duplicate document_id"):
        VectorRetriever(vector_dir, document_dir)
