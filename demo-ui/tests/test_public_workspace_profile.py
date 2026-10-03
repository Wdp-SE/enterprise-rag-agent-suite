from services.public_workspace_profile import (
    clear_workspace_bound_results,
    public_workspace_mismatch,
    workspace_identity_changed,
    workspace_page_readiness_notice,
    workspace_readiness_message,
    workspace_snapshot,
)


def _pphuman_workspace(**overrides):
    return {
        "workspace_id": "pphuman",
        "domain_profile": {"id": "pphuman"},
        "workspace": "PP-Human 行人分析工程知识",
        "repository": "PaddlePaddle/PaddleDetection",
        "repositories": ["PaddlePaddle/PaddleDetection"],
        "languages": ["zh"],
        **overrides,
    }


def test_public_demo_accepts_the_active_pphuman_workspace():
    assert public_workspace_mismatch(_pphuman_workspace(), public_demo=True) is None


def test_public_demo_rejects_old_or_unrelated_workspace_ids():
    warning = public_workspace_mismatch(
        _pphuman_workspace(workspace_id="unrelated_workspace"), public_demo=True,
    )

    assert warning is not None
    assert "PP-Human" in warning
    assert "RAG_API_BASE_URL" not in warning


def test_public_demo_rejects_wrong_repository_domain_profile_or_non_chinese_data():
    for patch in (
        {"repository": "other/project"},
        {"domain_profile": {"id": "other"}},
        {"repositories": ["PaddlePaddle/PaddleDetection", "other/project"]},
        {"languages": ["zh", "en"]},
        {"languages": []},
    ):
        assert public_workspace_mismatch(_pphuman_workspace(**patch), public_demo=True)


def test_workspace_snapshot_reports_the_current_corpus_size():
    snapshot = workspace_snapshot({
        "unique_document_count": 14, "source_count": 83, "chunk_count": 761,
    })

    assert "14 个主题" in snapshot
    assert "83 条版本/语言来源" in snapshot
    assert "761 个检索片段" in snapshot


def test_pending_domain_evaluation_is_explicit_without_reusing_old_scores():
    workspace = _pphuman_workspace(
        retrieval_evaluation_status="new_corpus_pending_rebenchmark",
        activation_block_reason="pending_project_evaluation",
        rag_ready=False,
        source_count=83,
        chunk_count=761,
    )

    assert public_workspace_mismatch(workspace, public_demo=True) is None
    assert "PP-Human 语料尚未完成评测" in workspace_readiness_message(workspace)
    assert "83 份来源" in workspace_snapshot(workspace)


def test_page_readiness_notice_does_not_repeat_global_blocker():
    workspace = _pphuman_workspace(
        activation_block_reason="pending_project_evaluation", rag_ready=False,
    )

    assert workspace_page_readiness_notice(
        workspace, "知识服务可能正在冷启动；连接恢复后可继续检索。",
    ) is None


def test_page_readiness_notice_keeps_generic_fallback_without_workspace():
    fallback = "知识服务暂不可用，连接恢复后可查看资料。"

    assert workspace_page_readiness_notice(None, fallback) == fallback


def test_workspace_identity_change_invalidates_cached_results_across_corpus_versions():
    previous = _pphuman_workspace(current_version="v2.8.1")
    current = _pphuman_workspace(current_version="v2.9.0")

    assert workspace_identity_changed(previous, current)
    assert not workspace_identity_changed(current, dict(current))


def test_switching_to_pphuman_clears_old_corpus_evidence_and_decisions():
    previous = {
        "workspace_id": "edge_ai_device",
        "repository": "Seeed-Studio/wiki-documents",
        "current_version": "old-snapshot",
    }
    state = {
        "official_workspace": previous,
        "official_result": ("query", "old question", "old-snapshot", "zh", {}, {}),
        "official_review": {"answer": "old corpus answer"},
        "official_review_decision": "approved",
        "official_question": "keep user draft",
    }

    changed = clear_workspace_bound_results(state, _pphuman_workspace())

    assert changed is True
    assert "official_result" not in state
    assert "official_review" not in state
    assert "official_review_decision" not in state
    assert state["official_question"] == "keep user draft"
    assert state["official_workspace"]["workspace_id"] == "pphuman"
