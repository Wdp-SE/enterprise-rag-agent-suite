from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest
from pydantic import ValidationError

from src.document_lifecycle import (
    ChangeType,
    Document,
    DocumentCatalog,
    DocumentVersion,
    DuplicateVersionError,
    RetrievalScope,
    SectionSnapshot,
    VersionLifecycleService,
    VersionStatus,
    compare_section_versions,
)


class KeywordEmbedder:
    def __init__(self, *, fail: bool = False):
        self.calls: list[list[str]] = []
        self.fail = fail

    def encode(self, texts):
        if self.fail:
            raise RuntimeError("synthetic embedding failure")
        self.calls.append(list(texts))
        rows = []
        for text in texts:
            if "并发" in text:
                rows.append([1.0, 0.0, 0.0, 0.0])
            elif "吞吐" in text:
                rows.append([0.0, 1.0, 0.0, 0.0])
            elif "设计" in text:
                rows.append([0.0, 0.0, 1.0, 0.0])
            else:
                rows.append([0.0, 0.0, 0.0, 1.0])
        return np.asarray(rows, dtype=np.float32)


def section(section_id, path, content, page):
    return SectionSnapshot(
        section_id=section_id,
        section_path=[path],
        content=content,
        page_start=page,
        page_end=page,
    )


@pytest.fixture
def versioned_store(tmp_path):
    service = VersionLifecycleService(tmp_path / "version-store")
    embedder = KeywordEmbedder()
    v1 = [
        section("req-v1-overview", "系统概述", "本系统用于版本治理。", 1),
        section("req-v1-capacity", "容量指标", "最大并发为 500。", 2),
        section("req-v1-legacy", "旧约束", "必须保留旧接口。", 3),
    ]
    report_v1 = service.ingest_version(
        document_id="REQ-001", project_id="P-001", document_type="requirements",
        title="需求规格说明书", version_id="REQ-001@1.0", version_label="V1.0",
        source_bytes=b"requirements-v1", source_name="requirements-v1.json",
        sections=v1, embedder=embedder,
    )
    design = [section("design-v1", "总体设计", "设计采用分层架构。", 8)]
    service.ingest_version(
        document_id="DESIGN-001", project_id="P-001", document_type="design",
        title="详细设计说明书", version_id="DESIGN-001@1.0", version_label="V1.0",
        source_bytes=b"design-v1", source_name="design-v1.json",
        sections=design, embedder=embedder,
    )
    v2 = [
        section("req-v2-overview", "系统概述", "本系统用于版本治理。", 1),
        section("req-v2-capacity", "容量指标", "最大并发为 1000。", 4),
        section("req-v2-throughput", "吞吐指标", "吞吐能力为 200 MB/s。", 5),
    ]
    report_v2 = service.ingest_version(
        document_id="REQ-001", project_id="P-001", document_type="requirements",
        title="需求规格说明书", version_id="REQ-001@2.0", version_label="V2.0",
        source_bytes=b"requirements-v2", source_name="requirements-v2.json",
        sections=v2, embedder=embedder,
    )
    return service, embedder, report_v1, report_v2


def test_version_governance_single_active_and_history_retained(versioned_store):
    service, _, _, _ = versioned_store
    assert service.catalog.active_version("REQ-001").version_id == "REQ-001@2.0"
    assert service.catalog.by_version["REQ-001@1.0"].status == VersionStatus.SUPERSEDED
    assert service.catalog.by_version["REQ-001@2.0"].status == VersionStatus.ACTIVE
    assert len(service.catalog.version_rows("REQ-001")) == 2
    reloaded = VersionLifecycleService(service.root)
    assert reloaded.catalog.active_version("REQ-001").version_id == "REQ-001@2.0"


def test_duplicate_active_catalog_is_rejected():
    document = Document(document_id="REQ", project_id="P", document_type="requirements", title="REQ")
    versions = [
        DocumentVersion(version_id="REQ@1", document_id="REQ", version_label="V1",
                        status=VersionStatus.ACTIVE, source_hash="a" * 64),
        DocumentVersion(version_id="REQ@2", document_id="REQ", version_label="V2",
                        status=VersionStatus.ACTIVE, source_hash="b" * 64),
    ]
    with pytest.raises(ValueError, match="at most one ACTIVE"):
        DocumentCatalog([document], versions)


def test_default_active_only_and_explicit_historical_retrieval(versioned_store):
    service, _, _, _ = versioned_store
    current = service.search([1, 0, 0, 0], top_k=5)
    assert current
    assert all(item["version_id"] != "REQ-001@1.0" for item in current)
    assert any("1000" in item["text"] for item in current)
    historical = service.search(
        [1, 0, 0, 0],
        RetrievalScope(version_ids=["REQ-001@1.0"], active_only=False),
        top_k=5,
    )
    assert historical and all(item["version_id"] == "REQ-001@1.0" for item in historical)
    assert any("500" in item["text"] for item in historical)


def test_scope_modes_and_true_topk_inside_scope(versioned_store):
    service, _, _, _ = versioned_store
    by_project = service.search([1, 0, 0, 0], RetrievalScope(project_ids=["P-001"]), top_k=10)
    assert {item["document_id"] for item in by_project} == {"REQ-001", "DESIGN-001"}
    by_type = service.search(
        [1, 0, 0, 0], RetrievalScope(document_types=["requirements"]), top_k=10
    )
    assert {item["document_id"] for item in by_type} == {"REQ-001"}
    by_document = service.search(
        [1, 0, 0, 0], RetrievalScope(document_ids=["DESIGN-001"]), top_k=5
    )
    assert len(by_document) == 1 and by_document[0]["document_id"] == "DESIGN-001"
    multi = service.search(
        [0, 0, 0, 1],
        RetrievalScope(document_ids=["REQ-001", "DESIGN-001"]),
        top_k=3,
    )
    assert len(multi) == 3
    # DESIGN is not present in the global best result for this query, but its
    # scoped search still returns the true best row inside DESIGN.
    global_one = service.search([1, 0, 0, 0], top_k=1)
    assert global_one[0]["document_id"] == "REQ-001"
    assert service.search(
        [1, 0, 0, 0], RetrievalScope(document_ids=["DESIGN-001"]), top_k=1
    )[0]["document_id"] == "DESIGN-001"


def test_scope_conflict_is_rejected():
    with pytest.raises(ValidationError, match="active_only"):
        RetrievalScope(version_ids=["REQ@1"], active_only=True)


def test_incremental_change_detection_embedding_reuse_and_removal(versioned_store):
    service, _, first, second = versioned_store
    assert first.added_sections == 3
    assert second.total_sections == 3
    assert second.unchanged_sections == 1
    assert second.modified_sections == 1
    assert second.added_sections == 1
    assert second.removed_sections == 1
    assert second.reused_embeddings == 1
    assert second.new_embeddings == 2
    current_text = " ".join(item["text"] for item in service.search([0, 0, 0, 1], top_k=20))
    assert "旧接口" not in current_text
    historical_text = " ".join(item["text"] for item in service.search(
        [0, 0, 0, 1], RetrievalScope(version_ids=["REQ-001@1.0"], active_only=False), top_k=20
    ))
    assert "旧接口" in historical_text


def test_failed_build_preserves_current_active_and_duplicate_source_is_rejected(versioned_store):
    service, _, _, _ = versioned_store
    before = service.catalog.active_version("REQ-001").version_id
    with pytest.raises(RuntimeError, match="embedding failure"):
        service.ingest_version(
            document_id="REQ-001", project_id="P-001", document_type="requirements",
            title="需求规格说明书", version_id="REQ-001@3.0", version_label="V3.0",
            source_bytes=b"requirements-v3", source_name="requirements-v3.json",
            sections=[section("req-v3", "新增章节", "全新内容。", 9)],
            embedder=KeywordEmbedder(fail=True),
        )
    assert VersionLifecycleService(service.root).catalog.active_version("REQ-001").version_id == before
    with pytest.raises(DuplicateVersionError, match="identical source"):
        service.ingest_version(
            document_id="REQ-001", project_id="P-001", document_type="requirements",
            title="需求规格说明书", version_id="REQ-001@duplicate", version_label="duplicate",
            source_bytes=b"requirements-v2", source_name="duplicate.json",
            sections=[section("dup", "重复", "重复。", 1)], embedder=KeywordEmbedder(),
        )


def test_activation_is_catalog_last_and_can_restore_historical(versioned_store):
    service, _, _, _ = versioned_store
    service.activate_version("REQ-001@1.0")
    assert service.catalog.active_version("REQ-001").version_id == "REQ-001@1.0"
    assert service.catalog.by_version["REQ-001@2.0"].status == VersionStatus.SUPERSEDED
    payload = json.loads(service.catalog_path.read_text(encoding="utf-8"))
    assert payload["status"] == "COMPLETE"
    assert payload["active_index"]["strategy"] == "CACHED_VECTOR_EXACT_MATRIX_REFRESH"


def test_version_diff_detects_all_change_types_with_citations_and_no_llm(versioned_store):
    service, _, _, _ = versioned_store
    first = service.diff("REQ-001", "REQ-001@1.0", "REQ-001@2.0")
    second = service.diff("REQ-001", "REQ-001@1.0", "REQ-001@2.0")
    assert first == second
    assert first.summary == {"ADDED": 1, "REMOVED": 1, "MODIFIED": 1, "UNCHANGED": 1}
    assert {row.change_type for row in first.sections} == set(ChangeType)
    modified = next(row for row in first.sections if row.change_type == ChangeType.MODIFIED)
    assert modified.old_page_range == [2, 2]
    assert modified.new_page_range == [4, 4]
    assert modified.old_content_hash and modified.new_content_hash


def test_catalog_hash_and_artifact_references_fail_closed(versioned_store):
    service, _, _, _ = versioned_store
    payload = json.loads(service.catalog_path.read_text(encoding="utf-8"))
    payload["index_refresh_version"] += 1
    service.catalog_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="manifest hash mismatch"):
        VersionLifecycleService(service.root)


def test_source_hash_is_sha256(versioned_store):
    service, _, _, _ = versioned_store
    version = service.catalog.by_version["REQ-001@2.0"]
    assert version.source_hash == hashlib.sha256(b"requirements-v2").hexdigest()

