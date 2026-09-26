from pathlib import Path

from fastapi.testclient import TestClient

from src.engineering_change import CandidateVersionService
from src.rd_v2_api import create_app
from tests.test_candidate_version_service import FixedEmbedder, build, document_bytes
from tests.test_rd_v3_runtime_api import _runtime


def test_candidate_store_exposes_catalog_and_text_dense_search(tmp_path: Path) -> None:
    text = "DES-014 支持 1000 并发和异步任务状态。"
    versions = CandidateVersionService(tmp_path / "store", FixedEmbedder())
    record = build(
        versions,
        document_bytes(tmp_path / "design.docx", text),
        version_id="design-v1",
        label="V1.0",
        expected=text,
    )
    versions.activate(record.candidate_id)

    with TestClient(create_app(_runtime(tmp_path / "runtime"), candidate_service=versions)) as client:
        documents = client.get("/engineering/versions/documents")
        assert documents.status_code == 200
        assert documents.json()["documents"][0]["active_version"]["version_id"] == "design-v1"

        searched = client.post("/engineering/versions/search", json={
            "query": "REQ-023 并发影响",
            "scope": {"project_ids": ["PAYMENT"], "active_only": True},
            "top_k": 5,
        })
        assert searched.status_code == 200
        assert searched.json()["results"][0]["version_id"] == "design-v1"
