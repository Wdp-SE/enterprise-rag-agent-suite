from services.public_workspace_profile import (
    public_workspace_mismatch,
    workspace_readiness_message,
    workspace_snapshot,
    workspace_identity_changed,
    clear_workspace_bound_results,
    workspace_page_readiness_notice,
)


def _project_workspace(**overrides):
    return {
        "workspace_id": "industrial-inspection",
        "domain_profile": {"id": "industrial_inspection"},
        "workspace": "工业视觉安全监控应用研发",
        "repository": "xbs0325/industrial-inspection",
        "repositories": ["xbs0325/industrial-inspection"],
        "languages": [],
        **overrides,
    }


def test_public_demo_accepts_the_single_industrial_inspection_project():
    assert public_workspace_mismatch(_project_workspace(), public_demo=True) is None


def test_public_demo_rejects_old_or_unrelated_workspace_ids():
    warning = public_workspace_mismatch(_project_workspace(workspace_id="unrelated_workspace"), public_demo=True)

    assert warning is not None
    assert "知识空间" in warning
    assert "请联系维护者" in warning
    assert "RAG_API_BASE_URL" not in warning


def test_public_demo_rejects_wrong_repository_domain_profile_or_language():
    for patch in (
        {"repository": "other/project"},
        {"domain_profile": {"id": "other"}},
        {"repositories": ["xbs0325/industrial-inspection", "other/project"]},
        {"languages": ["zh", "fr"]},
    ):
        assert public_workspace_mismatch(_project_workspace(**patch), public_demo=True)


def test_workspace_snapshot_reports_the_current_corpus_size():
    snapshot = workspace_snapshot({
        "unique_document_count": 18, "source_count": 18, "chunk_count": 394,
    })

    assert "18 个主题" in snapshot
    assert "394 个检索片段" in snapshot


def _industrial_inspection_workspace(**overrides):
    return {
        "workspace_id": "industrial-inspection",
        "domain_profile": {"id": "industrial_inspection"},
        "workspace": "工业视觉安全监控应用研发",
        "repository": "xbs0325/industrial-inspection",
        "repositories": ["xbs0325/industrial-inspection"],
        "languages": [],
        "source_status": "pending_redistribution_license",
        "activation_block_reason": "pending_redistribution_license",
        "rag_ready": False,
        "source_count": 0,
        "chunk_count": 0,
        **overrides,
    }


def test_public_demo_accepts_the_single_project_even_while_license_is_pending():
    workspace = _industrial_inspection_workspace()

    assert public_workspace_mismatch(workspace, public_demo=True) is None
    assert "未声明内容再分发许可" in workspace_readiness_message(workspace)
    assert "暂不可用" in workspace_readiness_message(workspace)
    assert "0 份来源" in workspace_snapshot(workspace)


def test_page_readiness_notice_does_not_repeat_global_license_blocker():
    workspace = _industrial_inspection_workspace()

    assert workspace_page_readiness_notice(
        workspace, "知识服务可能正在冷启动；连接恢复后可继续检索。",
    ) is None


def test_page_readiness_notice_keeps_generic_fallback_without_global_reason():
    fallback = "知识服务暂不可用，连接恢复后可查看资料。"

    assert workspace_page_readiness_notice(None, fallback) == fallback


def test_public_demo_rejects_a_mixed_project_or_unknown_language():
    assert public_workspace_mismatch(
        _industrial_inspection_workspace(repositories=[
            "xbs0325/industrial-inspection", "other/device-wiki",
        ]),
        public_demo=True,
    )
    assert public_workspace_mismatch(
        _industrial_inspection_workspace(languages=["zh", "fr"]),
        public_demo=True,
    )


def test_workspace_identity_change_invalidates_cached_results_across_project_or_commit():
    previous = _project_workspace(current_version="old-commit")
    current = _project_workspace(current_version="new-commit")

    assert workspace_identity_changed(previous, current)
    assert not workspace_identity_changed(current, dict(current))


def test_changing_project_workspace_clears_old_project_evidence_and_decisions():
    previous = {
        "workspace_id": "edge_ai_device",
        "repository": "Seeed-Studio/wiki-documents",
        "current_version": "old-snapshot",
    }
    state = {
        "official_workspace": previous,
        "official_result": ("query", "old question", "old-snapshot", "zh", {}, {}),
        "official_review": {"answer": "old project answer"},
        "official_review_decision": "approved",
        "official_question": "keep user draft",
    }

    changed = clear_workspace_bound_results(state, _project_workspace())

    assert changed is True
    assert "official_result" not in state
    assert "official_review" not in state
    assert "official_review_decision" not in state
    assert state["official_question"] == "keep user draft"
    assert state["official_workspace"]["workspace_id"] == "industrial-inspection"
