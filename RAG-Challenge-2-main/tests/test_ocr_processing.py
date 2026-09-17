import json
from pathlib import Path

import pytest

from src.artifact_reuse import ArtifactBuildConfig, evaluate_artifact_reuse
from src.evaluation.corpus import CorpusManifest, load_corpus_manifest
from src.ocr_processing import (
    OcrConfig,
    OcrDocumentStatus,
    OcrPageStatus,
    PageOcrProcessor,
    RawOcrBlock,
    _filesystem_path,
    assemble_ocr_text,
    meaningful_char_count,
    normalize_text_for_detection,
    page_requires_ocr,
    sha256_file,
    sort_ocr_blocks,
)
from src.text_splitter import TextSplitter


BOX_TOP = [[0, 1], [10, 1], [10, 5], [0, 5]]
BOX_BOTTOM = [[0, 20], [10, 20], [10, 25], [0, 25]]


class FakePageSource:
    def __init__(self, texts):
        self.texts = texts
        self.page_count = len(texts)
        self.render_calls = []
        self.closed = False

    def get_native_text(self, page_number):
        return self.texts[page_number - 1]

    def render_page(self, page_number, scale):
        self.render_calls.append((page_number, scale))
        return {"page": page_number}

    def get_page_size(self, page_number):
        return (595.0, 842.0)

    def close(self):
        self.closed = True


class FakeBackend:
    engine_name = "fake-ocr-1"

    def __init__(self, results=None, error=None):
        self.results = results or [RawOcrBlock(text="识别正文", confidence=0.99, bbox=BOX_TOP)]
        self.error = error
        self.calls = 0

    def recognize(self, image):
        self.calls += 1
        if self.error:
            raise self.error
        return self.results


def make_processor(tmp_path, source, backend, config=None):
    return PageOcrProcessor(
        tmp_path / "ocr_cache",
        config=config or OcrConfig(),
        page_source_factory=lambda _: source,
        ocr_backend_factory=lambda _: backend,
    )


def make_pdf(tmp_path, content=b"pdf-fixture"):
    path = tmp_path / "fixture.pdf"
    path.write_bytes(content)
    return path


def build_config(**updates):
    payload = {
        "source_sha256": "a" * 64,
        "embedding_provider": "dashscope",
        "embedding_model": "text-embedding-v1",
        "embedding_normalized": True,
        "chunk_size": 300,
        "chunk_overlap": 50,
        "metadata_schema_version": "generic-document-v1",
    }
    payload.update(updates)
    return ArtifactBuildConfig(**payload)


def test_meaningful_character_normalization_removes_control_and_collapses_space():
    assert normalize_text_for_detection("\x00  特\t种  \n\n\n设备  ") == "特 种\n\n设备"
    assert meaningful_char_count("  特 种\nA-1 ") == 4


def test_ocr_required_detection_uses_meaningful_character_threshold():
    assert page_requires_ocr("页 1", native_text_min_chars=4)
    assert not page_requires_ocr("有效正文123", native_text_min_chars=4)


def test_native_text_page_bypasses_ocr(tmp_path):
    source = FakePageSource(["这是超过阈值的原生文本内容"])
    backend = FakeBackend()
    result = make_processor(
        tmp_path, source, backend, OcrConfig(native_text_min_chars=5)
    ).process_document(make_pdf(tmp_path), document_id="doc-native")

    assert result.pages[0].ocr_status == OcrPageStatus.TEXT_NATIVE
    assert result.pages[0].source_type == "NATIVE_TEXT"
    assert result.pages[0].ocr_used is False
    assert backend.calls == 0
    assert source.render_calls == []


def test_ocr_page_success_preserves_identity_and_physical_page(tmp_path):
    source = FakePageSource(["", ""])
    backend = FakeBackend()
    result = make_processor(tmp_path, source, backend).process_document(
        make_pdf(tmp_path), document_id="doc-scan", page_numbers=[2]
    )

    page = result.pages[0]
    assert page.document_id == "doc-scan"
    assert page.page_number == 2
    assert page.source_type == "OCR"
    assert page.ocr_status == OcrPageStatus.OCR_SUCCEEDED
    assert page.text == "识别正文"


def test_ocr_failure_is_cached_as_explicit_page_state(tmp_path):
    source = FakePageSource([""])
    backend = FakeBackend(error=RuntimeError("fixture failure"))
    result = make_processor(tmp_path, source, backend).process_document(
        make_pdf(tmp_path), document_id="doc-fail"
    )

    page = result.pages[0]
    assert page.ocr_status == OcrPageStatus.OCR_FAILED
    assert "fixture failure" in page.error
    assert result.ocr_status == OcrDocumentStatus.OCR_FAILED


def test_document_ocr_partial_when_success_and_failure_are_mixed(tmp_path):
    source = FakePageSource(["", ""])

    class MixedBackend(FakeBackend):
        def recognize(self, image):
            self.calls += 1
            if image["page"] == 2:
                raise RuntimeError("page two failed")
            return self.results

    result = make_processor(tmp_path, source, MixedBackend()).process_document(
        make_pdf(tmp_path), document_id="doc-partial"
    )
    assert result.ocr_status == OcrDocumentStatus.OCR_PARTIAL
    assert result.ocr_success_pages == [1]
    assert result.ocr_failed_pages == [2]


def test_raw_ocr_blocks_round_trip_through_page_cache(tmp_path):
    blocks = [RawOcrBlock(text="条款", confidence=0.98, bbox=BOX_TOP)]
    source = FakePageSource([""])
    result = make_processor(tmp_path, source, FakeBackend(blocks)).process_document(
        make_pdf(tmp_path), document_id="doc-blocks"
    )
    cache_path = _filesystem_path(
        tmp_path
        / "ocr_cache"
        / "doc-blocks"
        / result.file_sha256
        / OcrConfig().config_sha256
        / "pages"
        / "page_0001.json"
    )
    cached = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cached["raw_blocks"] == [blocks[0].model_dump()]
    assert result.pages[0].raw_blocks == blocks


def test_ocr_blocks_have_deterministic_top_left_order():
    blocks = [
        RawOcrBlock(text="bottom", confidence=1, bbox=BOX_BOTTOM),
        RawOcrBlock(text="right", confidence=1, bbox=[[20, 1], [30, 1], [30, 5], [20, 5]]),
        RawOcrBlock(text="left", confidence=1, bbox=BOX_TOP),
    ]
    assert [block.text for block in sort_ocr_blocks(blocks)] == ["left", "right", "bottom"]
    assert assemble_ocr_text(blocks, 0.5) == "left\nright\nbottom"


def test_successful_page_cache_is_reused_without_second_ocr_call(tmp_path):
    pdf = make_pdf(tmp_path)
    first_source = FakePageSource([""])
    backend = FakeBackend()
    processor = make_processor(tmp_path, first_source, backend)
    first = processor.process_document(pdf, document_id="doc-cache")
    processor.page_source_factory = lambda _: FakePageSource([""])
    second = processor.process_document(pdf, document_id="doc-cache")

    assert first.cache_hits == 0
    assert second.cache_hits == 1
    assert second.pages[0].cache_hit is True
    assert backend.calls == 1


def test_file_hash_change_invalidates_page_cache(tmp_path):
    pdf = make_pdf(tmp_path, b"first")
    backend = FakeBackend()
    processor = make_processor(tmp_path, FakePageSource([""]), backend)
    processor.process_document(pdf, document_id="doc-hash")
    pdf.write_bytes(b"second")
    processor.page_source_factory = lambda _: FakePageSource([""])
    second = processor.process_document(pdf, document_id="doc-hash")
    assert second.cache_hits == 0
    assert backend.calls == 2
    assert len(list((tmp_path / "ocr_cache" / "doc-hash").iterdir())) == 2


def test_ocr_config_hash_change_invalidates_page_cache(tmp_path):
    pdf = make_pdf(tmp_path)
    backend = FakeBackend()
    make_processor(
        tmp_path,
        FakePageSource([""]),
        backend,
        OcrConfig(ocr_block_confidence_threshold=0.60),
    ).process_document(pdf, document_id="doc-config")
    second = make_processor(
        tmp_path,
        FakePageSource([""]),
        backend,
        OcrConfig(ocr_block_confidence_threshold=0.70),
    ).process_document(pdf, document_id="doc-config")
    assert second.cache_hits == 0
    assert backend.calls == 2


def test_failed_page_only_retries_when_explicitly_requested(tmp_path):
    pdf = make_pdf(tmp_path)
    backend = FakeBackend(error=RuntimeError("temporary"))
    processor = make_processor(tmp_path, FakePageSource([""]), backend)
    processor.process_document(pdf, document_id="doc-retry")
    processor.page_source_factory = lambda _: FakePageSource([""])
    cached_failure = processor.process_document(pdf, document_id="doc-retry")
    assert cached_failure.cache_hits == 1
    assert backend.calls == 1

    backend.error = None
    retried = processor.process_document(pdf, document_id="doc-retry", retry_failed=True)
    assert retried.pages[0].ocr_status == OcrPageStatus.OCR_SUCCEEDED
    assert backend.calls == 2


def test_atomic_page_cache_leaves_no_temporary_file(tmp_path):
    processor = make_processor(tmp_path, FakePageSource([""]), FakeBackend())
    processor.process_document(make_pdf(tmp_path), document_id="doc-atomic")
    cache_files = list((tmp_path / "ocr_cache").rglob("*"))
    assert any(path.name == "page_0001.json" for path in cache_files)
    assert not any(path.suffix == ".tmp" for path in cache_files)


def test_ocr_metadata_propagates_from_page_to_chunk(monkeypatch):
    splitter = TextSplitter()
    monkeypatch.setattr(splitter, "count_tokens", lambda _: 1)
    page = {
        "page": 14,
        "page_number": 14,
        "text": "使用登记",
        "source_type": "OCR",
        "ocr_used": True,
        "ocr_engine": "easyocr-1.7.2",
        "ocr_status": "OCR_SUCCEEDED",
    }
    result = splitter._split_report(
        {
            "metainfo": {"document_id": "tsg-08-2026", "title": "TSG", "source": "fixture"},
            "content": {"pages": [page]},
        }
    )
    chunk = result["content"]["chunks"][0]
    assert chunk["document_id"] == "tsg-08-2026"
    assert chunk["page"] == chunk["page_number"] == 14
    assert {key: chunk[key] for key in ("source_type", "ocr_used", "ocr_engine", "ocr_status")} == {
        "source_type": "OCR",
        "ocr_used": True,
        "ocr_engine": "easyocr-1.7.2",
        "ocr_status": "OCR_SUCCEEDED",
    }


def test_physical_page_mapping_survives_chunking_and_citation_shape(monkeypatch):
    splitter = TextSplitter()
    monkeypatch.setattr(splitter, "count_tokens", lambda _: 1)
    result = splitter._split_report(
        {
            "metainfo": {"document_id": "doc-a", "title": "A", "source": "fixture"},
            "content": {"pages": [{"page": 4, "text": "条款正文"}]},
        }
    )
    chunk = result["content"]["chunks"][0]
    citation = {"document_id": chunk["document_id"], "page_number": chunk["page"]}
    assert citation == {"document_id": "doc-a", "page_number": 4}


def test_v01_manifest_remains_backward_compatible():
    manifest = load_corpus_manifest("data/domain_corpus/domain_corpus_manifest.json")
    assert manifest.corpus_version == "0.1"
    assert all(document.ocr_status is None for document in manifest.documents)


def test_v02_manifest_accepts_and_serializes_optional_ocr_status():
    payload = json.loads(Path("data/domain_corpus/domain_corpus_manifest.json").read_text(encoding="utf-8"))
    payload["corpus_version"] = "0.2"
    for document in payload["documents"]:
        document["ocr_status"] = "NOT_REQUIRED"
    manifest = CorpusManifest.model_validate(payload)
    assert manifest.documents[0].ocr_status == "NOT_REQUIRED"
    assert "ocr_status" in manifest.model_dump()["documents"][0]


def test_reassemble_uses_cached_raw_blocks_without_backend(tmp_path):
    backend = FakeBackend()
    processor = make_processor(tmp_path, FakePageSource([""]), backend)
    page = processor.process_document(make_pdf(tmp_path), document_id="doc-raw").pages[0]
    before = backend.calls
    rebuilt = processor.reassemble_from_raw_blocks(page)
    assert rebuilt.text == page.text
    assert backend.calls == before


def test_artifact_reuse_requires_source_hash_match():
    result = evaluate_artifact_reuse(build_config(), build_config(source_sha256="b" * 64))
    assert result.reusable is False
    assert result.mismatches == ["source_sha256"]


def test_artifact_reuse_rejects_embedding_config_mismatch():
    result = evaluate_artifact_reuse(build_config(), build_config(embedding_model="other-model"))
    assert result.reusable is False
    assert result.mismatches == ["embedding_model"]


def test_artifact_reuse_rejects_normalization_mismatch():
    result = evaluate_artifact_reuse(build_config(), build_config(embedding_normalized=False))
    assert result.reusable is False
    assert result.mismatches == ["embedding_normalized"]


def test_artifact_reuse_rejects_chunk_config_mismatch():
    result = evaluate_artifact_reuse(build_config(), build_config(chunk_size=512))
    assert result.reusable is False
    assert result.mismatches == ["chunk_size"]


def test_artifact_reuse_requires_metadata_schema_compatibility():
    result = evaluate_artifact_reuse(
        build_config(), build_config(metadata_schema_version="incompatible-v2")
    )
    assert result.reusable is False
    assert result.mismatches == ["metadata_schema_version"]


def test_artifact_reuse_accepts_only_complete_match():
    result = evaluate_artifact_reuse(build_config(), build_config())
    assert result.reusable is True
    assert result.mismatches == []


def test_cache_identity_contains_document_file_and_config_hash(tmp_path):
    pdf = make_pdf(tmp_path)
    config = OcrConfig()
    processor = make_processor(tmp_path, FakePageSource([""]), FakeBackend(), config)
    processor.process_document(pdf, document_id="doc-identity")
    expected = (
        tmp_path
        / "ocr_cache"
        / "doc-identity"
        / sha256_file(pdf)
        / config.config_sha256
        / "pages"
        / "page_0001.json"
    )
    assert _filesystem_path(expected).is_file()


def test_ocr_config_hash_is_deterministic_and_covers_behavior_fields():
    first = OcrConfig()
    second = OcrConfig()
    changed = OcrConfig(render_scale=4.0)
    assert first.config_sha256 == second.config_sha256
    assert first.config_sha256 != changed.config_sha256


def test_calibrated_block_retention_boundary():
    block = RawOcrBlock(text="1.1 目的", confidence=0.621376, bbox=BOX_TOP)
    assert assemble_ocr_text([block], 0.65) == ""
    assert assemble_ocr_text([block], 0.60) == "1.1 目的"


def test_all_native_document_reports_not_required_and_never_builds_backend(tmp_path):
    constructed = []

    def forbidden_backend(_):
        constructed.append(True)
        raise AssertionError("OCR backend must not be constructed")

    processor = PageOcrProcessor(
        tmp_path / "ocr_cache",
        config=OcrConfig(native_text_min_chars=2),
        page_source_factory=lambda _: FakePageSource(["正文一", "正文二"]),
        ocr_backend_factory=forbidden_backend,
    )
    result = processor.process_document(make_pdf(tmp_path), document_id="doc-all-native")
    assert result.ocr_status == OcrDocumentStatus.NOT_REQUIRED
    assert constructed == []
