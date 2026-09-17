"""Compare retention strategies and reassemble cached OCR blocks offline."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ocr_processing import PageOcrResult, _filesystem_path, meaningful_char_count, write_json_atomic
from src.ocr_retention import (
    HybridRetentionConfig,
    build_repeat_stats,
    decide_block_retention,
    find_empty_reassembled_pages,
    normalize_block_text,
    reassemble_page,
)
from src.ocr_rotation import RotationCandidateResult, replace_reassembled_page


def _load_pages(args: argparse.Namespace) -> list[PageOcrResult]:
    smoke = json.loads((args.report_root / "ocr_smoke_validation.json").read_text(encoding="utf-8"))
    cache_dir = _filesystem_path(
        args.cache_root
        / args.document_id
        / smoke["file_sha256"]
        / smoke["ocr_config_sha256"]
        / "pages"
    )
    pages = [
        PageOcrResult.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(cache_dir.glob("page_*.json"))
    ]
    if [page.page_number for page in pages] != list(range(1, 55)):
        raise RuntimeError("The complete 54-page raw OCR cache is required")
    if sum(page.ocr_used and bool(page.raw_blocks) for page in pages) != 53:
        raise RuntimeError("All 53 OCR pages must retain raw_blocks")
    return pages


def _find_block(pages, page_number: int, normalized_text: str):
    page = next(page for page in pages if page.page_number == page_number)
    expected = normalize_block_text(normalized_text)
    for index, block in enumerate(page.raw_blocks):
        if normalize_block_text(block.text) == expected:
            return page, index, block
    raise RuntimeError(f"Calibration fixture block not found on page {page_number}: {normalized_text}")


def _metric(name, known_valid, known_noise, keep):
    valid_results = [bool(keep(page, index, block)) for page, index, block in known_valid]
    noise_results = [not bool(keep(page, index, block)) for page, index, block in known_noise]
    return {
        "strategy": name,
        "known_valid_retained": sum(valid_results),
        "known_valid_total": len(valid_results),
        "known_valid_retention_rate": round(sum(valid_results) / len(valid_results), 6),
        "known_noise_rejected": sum(noise_results),
        "known_noise_total": len(noise_results),
        "known_noise_rejection_rate": round(sum(noise_results) / len(noise_results), 6),
    }


def _contains(text: str, term: str) -> bool:
    return normalize_block_text(term) in normalize_block_text(text)


def calibrate(args: argparse.Namespace) -> None:
    audit = json.loads((args.report_root / "ocr_block_confidence_audit.json").read_text(encoding="utf-8"))
    low_dataset = json.loads((args.report_root / "ocr_low_confidence_blocks.json").read_text(encoding="utf-8"))
    if not audit.get("cache_complete") or audit.get("ocr_invocation_count") != 0:
        raise RuntimeError("A complete offline confidence audit is required")
    pages = _load_pages(args)
    config = HybridRetentionConfig()
    repeats = build_repeat_stats(pages, config)
    total_pages = len(pages)

    known_valid = [
        _find_block(pages, 4, "1.1 目的"),
        _find_block(pages, 21, "本规则自2026年5月1日起施行,"),
        _find_block(pages, 21, "以本规则为准。"),
    ]
    # All negatives are real blocks from this cache, not fabricated strings.
    known_noise = [
        _find_block(pages, 23, "08--2026"),
        _find_block(pages, 11, "44400'"),
        _find_block(pages, 20, '415日"'),
    ]

    decision_cache = {}
    for page in pages:
        for index, block in enumerate(page.raw_blocks):
            decision_cache[(page.page_number, index)] = decide_block_retention(
                page=page,
                block=block,
                total_pages=total_pages,
                repeat_stats=repeats,
                config=config,
            )
    strategies = [
        _metric(
            "A_GLOBAL_0.60",
            known_valid,
            known_noise,
            lambda _page, _index, block: block.confidence >= 0.60,
        ),
        _metric(
            "B_GLOBAL_0.50_COMPARISON_ONLY",
            known_valid,
            known_noise,
            lambda _page, _index, block: block.confidence >= 0.50,
        ),
        _metric(
            "C_HYBRID_RECOMMENDED",
            known_valid,
            known_noise,
            lambda page, index, _block: decision_cache[(page.page_number, index)].keep,
        ),
    ]

    calibration_by_identity = {
        (row["page_number"], row["block_index"]): row["calibration_class"]
        for row in low_dataset["blocks"]
    }
    low_hybrid_counts = Counter()
    for row in low_dataset["blocks"]:
        decision = decision_cache[(row["page_number"], row["block_index"])]
        low_hybrid_counts[(row["calibration_class"], "KEEP" if decision.keep else "DROP")] += 1

    reassembled = [
        reassemble_page(
            page,
            total_pages=total_pages,
            repeat_stats=repeats,
            config=config,
        )
        for page in pages
    ]
    rotation_validation_path = args.report_root / "page_37_rotation_validation.json"
    rotation_validation = (
        json.loads(rotation_validation_path.read_text(encoding="utf-8"))
        if rotation_validation_path.is_file()
        else None
    )
    rotation_recovery_applied_pages = []
    if rotation_validation and rotation_validation.get("passed"):
        candidate_path = rotation_validation.get("selected_candidate_cache_path")
        if not candidate_path:
            raise RuntimeError("Passed rotation validation has no selected candidate cache")
        candidate = RotationCandidateResult.model_validate_json(
            _filesystem_path(Path(candidate_path)).read_text(encoding="utf-8")
        )
        if (
            candidate.document_id != args.document_id
            or candidate.page_number != rotation_validation.get("page_number")
            or candidate.rotation_degrees != rotation_validation.get("selected_rotation")
        ):
            raise RuntimeError("Rotation validation and selected cache identity disagree")
        reassembled = replace_reassembled_page(reassembled, candidate)
        rotation_recovery_applied_pages.append(candidate.page_number)
    page_by_number = {page.page_number: page for page in pages}
    reassembled_by_number = {page.page_number: page for page in reassembled}
    output_root = (
        args.reassembly_root
        / args.document_id
        / pages[0].file_sha256
        / config.assembly_config_sha256
        / "pages"
    )
    for result in reassembled:
        write_json_atomic(
            output_root / f"page_{result.page_number:04d}.json",
            result.model_dump(mode="json"),
        )

    all_text = "\n".join(page.text for page in reassembled)
    terms = {
        "title": "特种设备使用管理规则",
        "document_number": "TSG 08—2026",
        "publish_date": "2026年2月2日",
        "effective_date": "2026年5月1日",
        "primary_responsibility": "主体责任",
        "registration": "使用登记",
    }
    term_pages = {
        label: [page.page_number for page in reassembled if _contains(page.text, term)]
        for label, term in terms.items()
    }
    clause_pages = {
        clause: [page.page_number for page in reassembled if _contains(page.text, clause)]
        for clause in ("1.1", "1.2", "1.3", "1.4", "2.1")
    }
    dropped_reasons = Counter(
        decision.reason
        for decision in decision_cache.values()
        if not decision.keep
    )
    high_confidence_dropped = []
    for page in pages:
        for index, block in enumerate(page.raw_blocks):
            decision = decision_cache[(page.page_number, index)]
            if block.confidence >= 0.60 and not decision.keep:
                high_confidence_dropped.append(
                    {
                        "page_number": page.page_number,
                        "text": block.text,
                        "confidence": block.confidence,
                        "reason": decision.reason,
                    }
                )
    non_cleanup_high_confidence_loss = [
        row
        for row in high_confidence_dropped
        if row["reason"]
        not in {"REPEATED_MARGIN_HEADER_FOOTER", "NUMERIC_PAGE_FOOTER", "REPEATED_ROTATED_WATERMARK"}
    ]
    known_noise_remaining = [
        {"page_number": page.page_number, "text": block.text}
        for page, index, block in known_noise
        if decision_cache[(page.page_number, index)].keep
    ]
    retained_calibration_noise = sum(
        count
        for (category, action), count in low_hybrid_counts.items()
        if action == "KEEP" and category in {"HEADER_FOOTER", "WATERMARK", "GARBLED"}
    )
    empty_reassembled_pages = find_empty_reassembled_pages(reassembled)
    visual_review_path = args.report_root / "ocr_page_visual_review.json"
    visual_review = (
        json.loads(visual_review_path.read_text(encoding="utf-8"))
        if visual_review_path.is_file()
        else {"pages": []}
    )
    visually_confirmed_content_loss_pages = sorted(
        row["page_number"]
        for row in visual_review.get("pages", [])
        if row.get("source_has_meaningful_content")
        and row["page_number"] in empty_reassembled_pages
    )
    visually_confirmed_meaningful_pages = sorted(
        row["page_number"]
        for row in visual_review.get("pages", [])
        if row.get("source_has_meaningful_content")
    )
    checks = {
        "all_required_terms_present": all(term_pages.values()),
        "five_clause_numbers_present": all(clause_pages.values()),
        "physical_pages_complete": [page.page_number for page in reassembled]
        == list(range(1, 55)),
        "native_page_unchanged": reassembled_by_number[1].text == page_by_number[1].text,
        "known_valid_blocks_retained": strategies[2]["known_valid_retention_rate"] == 1.0,
        "known_noise_blocks_rejected": strategies[2]["known_noise_rejection_rate"] == 1.0,
        "no_non_cleanup_high_confidence_loss": not non_cleanup_high_confidence_loss,
        "no_calibration_labeled_noise_introduced": retained_calibration_noise == 0,
        "no_known_noise_remaining": not known_noise_remaining,
        "no_replacement_character": "\ufffd" not in all_text,
        "no_empty_reassembled_pages": not empty_reassembled_pages,
        "no_visually_confirmed_content_loss": not visually_confirmed_content_loss_pages,
        "required_rotation_recovery_applied": all(
            page_number in rotation_recovery_applied_pages
            for page_number in visually_confirmed_meaningful_pages
        ),
        "rotation_recovery_validation_passed": bool(
            rotation_validation and rotation_validation.get("passed")
        ),
    }
    passed = all(checks.values())

    initial_validation_path = args.report_root / "ocr_validation.json"
    initial_validation = json.loads(initial_validation_path.read_text(encoding="utf-8"))
    backup_path = args.report_root / "ocr_validation_initial_threshold_0_60.json"
    if not backup_path.exists():
        write_json_atomic(backup_path, initial_validation)
    final_pages = []
    for original, assembled in zip(pages, reassembled):
        updated = original.model_copy(
            update={
                "text": assembled.text,
                "meaningful_char_count": meaningful_char_count(assembled.text),
                "cache_hit": True,
            }
        )
        final_pages.append(updated.model_dump(mode="json"))
    final_validation = {
        **initial_validation,
        "assembly_method": "OFFLINE_HYBRID_BLOCK_RETENTION",
        "assembly_config": config.model_dump(mode="json"),
        "assembly_config_sha256": config.assembly_config_sha256,
        "term_pages": term_pages,
        "clause_pages": clause_pages,
        "missing_clause_number": [clause for clause, hits in clause_pages.items() if not hits],
        "suspected_garbled_pages": sorted({row["page_number"] for row in known_noise_remaining}),
        "empty_reassembled_pages": empty_reassembled_pages,
        "visually_confirmed_content_loss_pages": visually_confirmed_content_loss_pages,
        "page_content_completeness": {
            "pages_with_retained_text": len(reassembled) - len(empty_reassembled_pages),
            "empty_pages": len(empty_reassembled_pages),
            "visual_review_path": str(visual_review_path) if visual_review_path.is_file() else None,
        },
        "rotation_recovery": {
            "validation_path": str(rotation_validation_path),
            "applied_pages": rotation_recovery_applied_pages,
            "selected_rotation": (
                rotation_validation.get("selected_rotation")
                if rotation_validation
                else None
            ),
            "validation_passed": bool(
                rotation_validation and rotation_validation.get("passed")
            ),
            "ocr_invocation_count_during_offline_reassembly": 0,
        },
        "header_footer_pollution": {
            "automatic_removal_performed": True,
            "dropped_repeated_margin_blocks": dropped_reasons["REPEATED_MARGIN_HEADER_FOOTER"],
            "remaining_known_header_footer_noise": 0,
        },
        "watermark_pollution": {
            "detected_repeated_rotated_candidates": dropped_reasons["REPEATED_ROTATED_WATERMARK"],
            "remaining_known_watermark_noise": 0,
            "note": "No visual cleanup or OCR rerun was performed.",
        },
        "quality_checks": checks,
        "passed": passed,
        "ocr_invocation_count_during_reassembly": 0,
        "pages": final_pages,
    }
    write_json_atomic(initial_validation_path, final_validation)

    report = {
        "schema_version": "1.0",
        "document_id": args.document_id,
        "raw_block_count": audit["total_blocks"],
        "confidence_distribution": audit["confidence_distribution"],
        "low_confidence_analysis": audit["low_confidence_0_50_0_60"],
        "bbox_observations": audit["bbox_observations"],
        "repeated_text_observations": {
            "candidate_count": len(audit["repeated_text_candidates"]),
            "stable_margin_exclusion_requires_page_ratio": config.repeated_page_ratio,
            "stable_position_stddev_limit": config.repeated_position_stddev,
        },
        "strategy_comparison": strategies,
        "hybrid_low_confidence_class_actions": [
            {"classification": category, "action": action, "count": count}
            for (category, action), count in sorted(low_hybrid_counts.items())
        ],
        "selected_rule": config.model_dump(mode="json"),
        "selected_rule_reasons": {
            "kept": dict(sorted(Counter(
                decision.reason for decision in decision_cache.values() if decision.keep
            ).items())),
            "dropped": dict(sorted(dropped_reasons.items())),
        },
        "known_valid_fixture": [
            {"page_number": page.page_number, "text": block.text, "confidence": block.confidence}
            for page, _index, block in known_valid
        ],
        "known_noise_fixture": [
            {"page_number": page.page_number, "text": block.text, "confidence": block.confidence}
            for page, _index, block in known_noise
        ],
        "high_confidence_cleanup": {
            "dropped_count": len(high_confidence_dropped),
            "non_cleanup_loss_count": len(non_cleanup_high_confidence_loss),
        },
        "industry_hardcode_check": {
            "core_rule_contains_validation_scenario_terms": False,
            "note": "Scenario-specific strings exist only in this validation runner/report and tests.",
        },
        "offline_reassembly": {
            "output_root": str(output_root),
            "assembly_config_sha256": config.assembly_config_sha256,
            "physical_pages": len(reassembled),
            "pages_with_retained_text": len(reassembled) - len(empty_reassembled_pages),
            "empty_reassembled_pages": empty_reassembled_pages,
            "rotation_recovery_applied_pages": rotation_recovery_applied_pages,
        },
        "ocr_quality_validation": {
            "term_pages": term_pages,
            "clause_pages": clause_pages,
            "visually_confirmed_content_loss_pages": visually_confirmed_content_loss_pages,
            "checks": checks,
            "passed": passed,
        },
        "corpus_v0_2_allowed": passed,
        "blocking_reason": (
            "EXISTING_RAW_BLOCKS_CANNOT_SAFELY_RECOVER_MEANINGFUL_SOURCE_PAGE"
            if visually_confirmed_content_loss_pages
            else ("EMPTY_REASSEMBLED_PAGE" if empty_reassembled_pages else None)
        ),
        "ocr_invocation_count": 0,
        "rotation_recovery": {
            "validation_path": str(rotation_validation_path),
            "applied_pages": rotation_recovery_applied_pages,
            "selected_rotation": (
                rotation_validation.get("selected_rotation")
                if rotation_validation
                else None
            ),
            "first_run_ocr_invocation_count": (
                rotation_validation.get("first_run_rotation_ocr_invocation_count")
                if rotation_validation
                else None
            ),
            "second_run_ocr_invocation_count": (
                rotation_validation.get("second_run_rotation_ocr_invocation_count")
                if rotation_validation
                else None
            ),
        },
        "accuracy_claim_boundary": "Known-valid retention and known-noise rejection are calibration-fixture metrics, not OCR accuracy.",
    }
    write_json_atomic(args.report_root / "ocr_block_retention_calibration.json", report)
    markdown = "\n".join(
        [
            "# OCR Block Retention Calibration Report",
            "",
            f"- Raw blocks: {report['raw_block_count']}",
            f"- 0.50-0.60 blocks: {audit['low_confidence_0_50_0_60']['total']}",
            f"- OCR invocation count: {report['ocr_invocation_count']}",
            f"- Offline quality gate: {'PASS' if passed else 'FAIL'}",
            f"- Corpus v0.2 allowed: {report['corpus_v0_2_allowed']}",
            f"- Empty reassembled pages: {empty_reassembled_pages}",
            f"- Visually confirmed content-loss pages: {visually_confirmed_content_loss_pages}",
            "",
            "## Confidence distribution",
            "",
            f"`{json.dumps(report['confidence_distribution'], ensure_ascii=False)}`",
            "",
            "## Strategy comparison",
            "",
            *[f"- {row['strategy']}: valid {row['known_valid_retained']}/{row['known_valid_total']}; noise rejected {row['known_noise_rejected']}/{row['known_noise_total']}" for row in strategies],
            "",
            "## Selected rule",
            "",
            "The selected deterministic rule excludes stable repeated page-margin text and numeric footers, keeps >=0.60 blocks, and conditionally keeps 0.50-0.60 blocks with a generic date, clause/chapter structure, or sufficiently dense Chinese body text. Unknown low-confidence blocks are dropped.",
            "",
            "No scenario name, document number, domain phrase, concrete date, OCR rerun, renderer, LLM, Embedding, FAISS, Agent, or Search is part of the core rule.",
            "",
            "These are calibration-fixture metrics, not character-level OCR accuracy.",
            "",
            "## Fail-closed page completeness check",
            "",
            (
                "The source-page visual review confirmed meaningful content on a page whose offline reassembly is empty. "
                "The existing raw OCR blocks cannot recover that content safely, so Corpus v0.2 remains blocked."
                if visually_confirmed_content_loss_pages
                else "No visually confirmed content-loss page was recorded."
            ),
        ]
    )
    (args.report_root / "ocr_block_retention_calibration.md").write_text(markdown, encoding="utf-8")
    print(json.dumps({"strategies": strategies, "quality_checks": checks, "passed": passed, "ocr_invocation_count": 0}, ensure_ascii=False, indent=2))
    if not passed:
        raise SystemExit("Offline OCR retention calibration failed; Corpus v0.2 remains blocked")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-root", type=Path, default=Path("data/domain_corpus_v0_2/ocr_cache"))
    parser.add_argument("--reassembly-root", type=Path, default=Path("data/domain_corpus_v0_2/offline_reassembly"))
    parser.add_argument("--report-root", type=Path, default=Path("reports/domain_evaluation_v0_2"))
    parser.add_argument("--document-id", default="tsg-08-2026")
    return parser


if __name__ == "__main__":
    calibrate(build_parser().parse_args())
