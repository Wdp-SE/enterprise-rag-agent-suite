from __future__ import annotations


NO_EVIDENCE_MESSAGE = "当前选择的资料范围内未找到足够依据，暂不生成该内容。"
STALE_EVIDENCE_MESSAGE = "引用资料已更新，该章节需要重新检索后才能继续。"
INVALID_EVIDENCE_MESSAGE = "当前草稿引用的资料不满足校验要求，请重新获取证据后继续。"
INVALID_STRUCTURE_MESSAGE = "模型返回内容未满足当前结构要求，本次结果已停止进入正式流程。"


def business_failure_message(value: object, *, pending_review_count: int | None = None) -> str | None:
    text = str(value or "").upper()
    if any(code in text for code in ("NO_EVIDENCE", "EVIDENCE_TOO_SHORT", "INSUFFICIENT_EVIDENCE", "NO_DRAFTABLE_EVIDENCE")):
        return NO_EVIDENCE_MESSAGE
    if any(code in text for code in ("STALE_EVIDENCE", "EVIDENCE_FRESHNESS_INVALID", "FRESHNESS_UNKNOWN")):
        return STALE_EVIDENCE_MESSAGE
    if any(code in text for code in ("INVALID_EVIDENCE_REFERENCE", "EVIDENCE_MEMBERSHIP_INVALID", "DRAFT_WITHOUT_EVIDENCE", "APPROVED_CONTENT_HASH_INVALID", "EMPTY_VALID_CITATIONS", "INVALID_CITATIONS_FILTERED", "CITATION_MEMBERSHIP_FAILED")):
        return INVALID_EVIDENCE_MESSAGE
    if any(code in text for code in ("STRUCTURED_OUTPUT_INVALID", "GENERATION_OR_SCHEMA_ERROR")):
        return INVALID_STRUCTURE_MESSAGE
    if any(code in text for code in ("ALL_REQUIRED_SECTIONS_MUST_BE_APPROVED", "REVIEW_REQUIRED")):
        count = max(0, int(pending_review_count or 0))
        return f"还有 {count} 个必要章节尚未审核通过，暂不能生成正式文档。"
    return None
