from pathlib import Path

from src.ocr_processing import OcrPageStatus, PageOcrResult, RawOcrBlock
from src.ocr_retention import (
    HybridRetentionConfig,
    build_repeat_stats,
    decide_block_retention,
    find_empty_reassembled_pages,
    reassemble_page,
)


def block(text, confidence, *, top=30, bottom=40):
    return RawOcrBlock(
        text=text,
        confidence=confidence,
        bbox=[[10, top], [90, top], [90, bottom], [10, bottom]],
    )


def page(number, blocks, *, native=False):
    return PageOcrResult(
        document_id="fixture-document",
        page_number=number,
        text="原生文本" if native else "cached text",
        source_type="NATIVE_TEXT" if native else "OCR",
        ocr_used=not native,
        ocr_engine=None if native else "fixture-ocr",
        ocr_status=OcrPageStatus.TEXT_NATIVE if native else OcrPageStatus.OCR_SUCCEEDED,
        file_sha256="a" * 64,
        ocr_config_sha256="b" * 64,
        meaningful_char_count=4,
        raw_blocks=[] if native else blocks,
        page_width=100,
        page_height=100,
    )


def decision(target_page, target_block, pages=None):
    config = HybridRetentionConfig(render_scale=1)
    pages = pages or [target_page]
    return decide_block_retention(
        page=target_page,
        block=target_block,
        total_pages=len(pages),
        repeat_stats=build_repeat_stats(pages, config),
        config=config,
    )


def test_high_confidence_boundary_remains_retained():
    target = block("1.1 目的", 0.621376)
    assert decision(page(1, [target]), target).keep is True


def test_generic_numeric_clause_is_positive_signal_below_point_six():
    target = block("3.10", 0.55)
    result = decision(page(1, [target]), target)
    assert result.keep is True
    assert result.reason == "STRUCTURED_CLAUSE"


def test_generic_chinese_clause_is_positive_signal():
    target = block("第二十五条", 0.55)
    result = decision(page(1, [target]), target)
    assert result.keep is True
    assert result.reason == "STRUCTURED_CLAUSE"


def test_generic_chapter_heading_is_positive_signal():
    target = block("第三章", 0.55)
    result = decision(page(1, [target]), target)
    assert result.keep is True
    assert result.reason == "STRUCTURED_CHAPTER"


def test_generic_date_is_positive_signal_without_specific_date_hardcode():
    target = block("本办法自2031年12月9日起施行", 0.545326)
    result = decision(page(1, [target]), target)
    assert result.keep is True
    assert result.reason == "STRUCTURED_DATE"


def test_long_coherent_chinese_body_is_retained():
    target = block("以本规则为准。", 0.504930)
    result = decision(page(1, [target]), target)
    assert result.keep is True
    assert result.reason == "CHINESE_BODY_TEXT"


def test_repeated_stable_margin_text_is_rejected():
    pages = [page(number, [block("文档编号", 0.55, top=3, bottom=7)]) for number in range(1, 12)]
    target = pages[0].raw_blocks[0]
    result = decision(pages[0], target, pages)
    assert result.keep is False
    assert result.reason == "REPEATED_MARGIN_HEADER_FOOTER"


def test_short_unstructured_noise_is_rejected():
    target = block("44400'", 0.527665)
    result = decision(page(1, [target]), target)
    assert result.keep is False
    assert result.reason == "NO_POSITIVE_SIGNAL"


def test_numeric_page_footer_is_rejected_even_at_high_confidence():
    target = block("26", 0.95, top=92, bottom=96)
    result = decision(page(1, [target]), target)
    assert result.keep is False
    assert result.reason == "NUMERIC_PAGE_FOOTER"


def test_decision_and_reassembly_are_deterministic():
    blocks = [
        block("后段正文内容完整", 0.55, top=60, bottom=70),
        block("前段正文内容完整", 0.55, top=20, bottom=30),
    ]
    target_page = page(1, blocks)
    config = HybridRetentionConfig(render_scale=1)
    repeats = build_repeat_stats([target_page], config)
    first = reassemble_page(
        target_page, total_pages=1, repeat_stats=repeats, config=config
    )
    second = reassemble_page(
        target_page, total_pages=1, repeat_stats=repeats, config=config
    )
    assert first == second
    assert first.text == "前段正文内容完整\n后段正文内容完整"


def test_native_page_offline_reassembly_never_invokes_ocr():
    invocations = 0
    target_page = page(1, [], native=True)
    config = HybridRetentionConfig(render_scale=1)
    result = reassemble_page(
        target_page,
        total_pages=1,
        repeat_stats=build_repeat_stats([target_page], config),
        config=config,
    )
    assert result.text == "原生文本"
    assert result.ocr_used is False
    assert invocations == 0


def test_empty_reassembled_page_is_reported_for_fail_closed_quality_gate():
    target_page = page(7, [block("x", 0.10)])
    config = HybridRetentionConfig(render_scale=1)
    result = reassemble_page(
        target_page,
        total_pages=1,
        repeat_stats=build_repeat_stats([target_page], config),
        config=config,
    )

    assert result.text == ""
    assert find_empty_reassembled_pages([result]) == [7]


def test_core_rule_contains_no_validation_scenario_hardcode():
    source = Path("src/ocr_retention.py").read_text(encoding="utf-8")
    for forbidden in ("特种设备", "TSG 08", "使用登记", "2026年5月1日"):
        assert forbidden not in source
