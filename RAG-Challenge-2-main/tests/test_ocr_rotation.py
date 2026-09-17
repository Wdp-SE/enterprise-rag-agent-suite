from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from scripts.build_domain_corpus_v02 import build, build_parser
from src.ocr_processing import OcrConfig, OcrPageStatus, PageOcrResult, RawOcrBlock, sha256_file
from src.ocr_retention import (
    HybridRetentionConfig,
    ReassembledPage,
    build_repeat_stats,
)
from src.ocr_rotation import (
    OrientationStatus,
    RenderedPageEvidence,
    RotationOcrProcessor,
    RotationRecoveryConfig,
    build_rotation_candidate,
    replace_reassembled_page,
    rotation_preconditions_met,
    select_rotation_candidate,
    should_attempt_rotation,
)


def block(text, confidence=0.95, *, top=20, bottom=35):
    return RawOcrBlock(
        text=text,
        confidence=confidence,
        bbox=[[10, top], [180, top], [180, bottom], [10, bottom]],
    )


GOOD_BLOCKS = [
    block("设备基础信息汇总表", top=20, bottom=35),
    block("使用单位名称", top=45, bottom=60),
    block("设备编号和工作压力", top=70, bottom=85),
]
BAD_BLOCKS = [block("x@", 0.10)]


class FakePageSource:
    page_count = 54

    def __init__(self, image):
        self.image = image
        self.rendered_pages = []

    def get_native_text(self, page_number):
        return ""

    def render_page(self, page_number, scale):
        self.rendered_pages.append(page_number)
        return self.image.copy()

    def get_page_size(self, page_number):
        return (100.0, 200.0)

    def close(self):
        return None


class FakeBackend:
    engine_name = "fake-easyocr-1.7.2"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def recognize(self, image):
        response = self.responses[self.calls]
        self.calls += 1
        if isinstance(response, Exception):
            raise response
        return response


def rendered_image():
    image = Image.new("RGB", (100, 200), "white")
    ImageDraw.Draw(image).rectangle((10, 10, 90, 190), outline="black", width=3)
    return image


def make_pdf(tmp_path):
    path = tmp_path / "fixture.pdf"
    path.write_bytes(b"rotation-fixture")
    return path


def normal_page(pdf_path, *, page_number=37):
    return PageOcrResult(
        document_id="fixture-document",
        page_number=page_number,
        text="normal OCR header only",
        source_type="OCR",
        ocr_used=True,
        ocr_engine="fake-easyocr-1.7.2",
        ocr_status=OcrPageStatus.OCR_SUCCEEDED,
        file_sha256=sha256_file(pdf_path),
        ocr_config_sha256=OcrConfig(render_scale=1).config_sha256,
        meaningful_char_count=19,
        raw_blocks=[block("页眉")],
        page_width=100,
        page_height=200,
    )


def assembled(page, text=""):
    return ReassembledPage(
        document_id=page.document_id,
        page_number=page.page_number,
        text=text,
        source_type="OCR",
        ocr_used=True,
        ocr_engine=page.ocr_engine,
        ocr_status="OCR_SUCCEEDED",
        file_sha256=page.file_sha256,
        source_ocr_config_sha256=page.ocr_config_sha256,
        assembly_config_sha256=HybridRetentionConfig(render_scale=1).assembly_config_sha256,
        retained_block_indices=[],
        dropped_block_indices=[],
        decisions=[],
    )


def make_processor(tmp_path, source, backend, *, rotation_config=None):
    return RotationOcrProcessor(
        tmp_path / "ocr_cache",
        ocr_config=OcrConfig(render_scale=1),
        rotation_config=rotation_config or RotationRecoveryConfig(),
        retention_config=HybridRetentionConfig(render_scale=1),
        page_source_factory=lambda _: source,
        ocr_backend_factory=lambda _: backend,
    )


def recover(tmp_path, responses, *, rotation_config=None):
    pdf = make_pdf(tmp_path)
    page = normal_page(pdf)
    source = FakePageSource(rendered_image())
    backend = FakeBackend(responses)
    processor = make_processor(
        tmp_path, source, backend, rotation_config=rotation_config
    )
    result = processor.recover_page(
        pdf,
        normal_page=page,
        assembled_page=assembled(page),
        orientation_status=OrientationStatus.OCR_ORIENTATION_SUSPECTED,
        context_pages=[page],
    )
    return pdf, page, source, backend, processor, result


def test_normal_success_page_does_not_trigger_rotation(tmp_path):
    pdf = make_pdf(tmp_path)
    page = normal_page(pdf)
    source = FakePageSource(rendered_image())
    backend = FakeBackend([])
    result = make_processor(tmp_path, source, backend).recover_page(
        pdf,
        normal_page=page,
        assembled_page=assembled(page, "已经存在完整的正常方向正文内容"),
        orientation_status=OrientationStatus.OCR_ORIENTATION_SUSPECTED,
        context_pages=[page],
    )
    assert result.rotation_attempted is False
    assert source.rendered_pages == []
    assert backend.calls == 0


def test_empty_assembled_page_with_explicit_marker_and_nonempty_render_triggers():
    pdf = Path("fixture.pdf")
    page = PageOcrResult(
        document_id="doc",
        page_number=7,
        text="header",
        source_type="OCR",
        ocr_used=True,
        ocr_engine="fixture",
        ocr_status=OcrPageStatus.OCR_SUCCEEDED,
        file_sha256="a" * 64,
        ocr_config_sha256="b" * 64,
        meaningful_char_count=6,
        raw_blocks=[block("页眉")],
    )
    config = RotationRecoveryConfig()
    assert rotation_preconditions_met(
        page,
        assembled(page),
        OrientationStatus.OCR_ORIENTATION_SUSPECTED,
        config,
    )
    assert should_attempt_rotation(
        page,
        assembled(page),
        OrientationStatus.OCR_ORIENTATION_SUSPECTED,
        RenderedPageEvidence(has_content=True, grayscale_stddev=5, foreground_ratio=0.1),
        config,
    )


def test_rot90_candidate_can_be_selected(tmp_path):
    *_, result = recover(tmp_path, [GOOD_BLOCKS, BAD_BLOCKS])
    assert result.rotation_recovered is True
    assert result.selected_rotation_degrees == 90


def test_rot270_candidate_can_be_selected(tmp_path):
    *_, result = recover(tmp_path, [BAD_BLOCKS, GOOD_BLOCKS])
    assert result.rotation_recovered is True
    assert result.selected_rotation_degrees == 270


def test_rotation_selection_is_deterministic(tmp_path):
    *_, result = recover(tmp_path, [GOOD_BLOCKS, GOOD_BLOCKS])
    candidates = result.candidates
    config = RotationRecoveryConfig()
    first = select_rotation_candidate(
        candidates, normal_meaningful_char_count=0, config=config
    )
    second = select_rotation_candidate(
        list(reversed(candidates)), normal_meaningful_char_count=0, config=config
    )
    assert first == second


def test_rotation_score_tie_prefers_90(tmp_path):
    *_, result = recover(tmp_path, [GOOD_BLOCKS, GOOD_BLOCKS])
    assert result.candidates[0].quality_score == result.candidates[1].quality_score
    assert result.selected_rotation_degrees == 90


def test_second_rotation_run_hits_cache_without_easyocr(tmp_path):
    pdf, page, _, first_backend, processor, first = recover(
        tmp_path, [GOOD_BLOCKS, BAD_BLOCKS]
    )
    second_source = FakePageSource(rendered_image())
    forbidden_backend = FakeBackend([])
    second_processor = make_processor(tmp_path, second_source, forbidden_backend)
    second = second_processor.recover_page(
        pdf,
        normal_page=page,
        assembled_page=assembled(page),
        orientation_status=OrientationStatus.OCR_ORIENTATION_SUSPECTED,
        context_pages=[page],
    )
    assert first_backend.calls == 2
    assert first.ocr_invocation_count == 2
    assert second.ocr_invocation_count == 0
    assert all(candidate.cache_hit for candidate in second.candidates)
    assert forbidden_backend.calls == 0


def test_rotation_config_change_invalidates_cache(tmp_path):
    pdf, page, _, _, _, _ = recover(tmp_path, [GOOD_BLOCKS, BAD_BLOCKS])
    changed = RotationRecoveryConfig(minimum_recovered_chars=21)
    source = FakePageSource(rendered_image())
    backend = FakeBackend([GOOD_BLOCKS, BAD_BLOCKS])
    result = make_processor(
        tmp_path, source, backend, rotation_config=changed
    ).recover_page(
        pdf,
        normal_page=page,
        assembled_page=assembled(page),
        orientation_status=OrientationStatus.OCR_ORIENTATION_SUSPECTED,
        context_pages=[page],
    )
    assert result.ocr_invocation_count == 2
    assert backend.calls == 2
    assert not any(candidate.cache_hit for candidate in result.candidates)


def test_physical_page_number_is_preserved(tmp_path):
    *_, result = recover(tmp_path, [GOOD_BLOCKS, BAD_BLOCKS])
    assert result.page_number == 37
    assert all(candidate.page_number == 37 for candidate in result.candidates)


def test_rotation_candidate_reuses_hybrid_retention_for_low_confidence_chinese(tmp_path):
    pdf = make_pdf(tmp_path)
    page = normal_page(pdf)
    retention = HybridRetentionConfig(render_scale=1)
    candidate = build_rotation_candidate(
        document_id=page.document_id,
        page_number=37,
        rotation_degrees=90,
        file_sha256=page.file_sha256,
        ocr_config=OcrConfig(render_scale=1),
        rotation_config=RotationRecoveryConfig(),
        retention_config=retention,
        ocr_engine="fixture",
        raw_blocks=[block("这是一段完整的中文正文", 0.55)],
        page_width=200,
        page_height=100,
        total_pages=1,
        repeat_stats=build_repeat_stats([page], retention),
    )
    assert candidate.retained_blocks[0].text == "这是一段完整的中文正文"
    assert candidate.retention_decisions[0].reason == "CHINESE_BODY_TEXT"


def test_failed_rotation_recovery_is_explicit(tmp_path):
    *_, result = recover(tmp_path, [BAD_BLOCKS, BAD_BLOCKS])
    assert result.rotation_recovered is False
    assert result.orientation_status == OrientationStatus.OCR_ROTATION_FAILED
    assert result.selected_candidate is None
    assert result.error == "NO_ROTATION_CANDIDATE_PASSED_QUALITY"


def test_only_requested_physical_page_is_rendered_and_ocrd(tmp_path):
    _, _, source, backend, _, result = recover(tmp_path, [GOOD_BLOCKS, BAD_BLOCKS])
    assert source.rendered_pages == [37]
    assert backend.calls == 2
    assert result.other_page_ocr_invocation_count == 0


def test_offline_reassembly_uses_recovered_page_without_changing_other_pages(tmp_path):
    _, page, _, _, _, recovery = recover(tmp_path, [GOOD_BLOCKS, BAD_BLOCKS])
    other = assembled(page.model_copy(update={"page_number": 36}), "其他页正文")
    replaced = replace_reassembled_page(
        [other, assembled(page)], recovery.selected_candidate
    )
    assert replaced[0] == other
    assert replaced[1].page_number == 37
    assert replaced[1].text == recovery.selected_candidate.assembled_text


def test_corpus_build_remains_fail_closed_when_quality_is_false(tmp_path):
    report_root = tmp_path / "reports"
    report_root.mkdir()
    (report_root / "ocr_validation.json").write_text(
        '{"passed": false}', encoding="utf-8"
    )
    args = build_parser().parse_args([])
    args.report_v02 = report_root
    args.corpus_v02 = tmp_path / "corpus-v02"
    with pytest.raises(RuntimeError, match="did not pass"):
        build(args)
    assert not args.corpus_v02.exists()


def test_rotation_production_rule_contains_no_scenario_field_hardcode():
    source = Path("src/ocr_rotation.py").read_text(encoding="utf-8")
    for forbidden in (
        "压力管道基本信息汇总表",
        "使用单位",
        "管道名称",
        "使用登记证编号",
    ):
        assert forbidden not in source
