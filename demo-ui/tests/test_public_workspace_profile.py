from services.public_workspace_profile import public_workspace_mismatch, workspace_snapshot


def test_public_profile_flags_a_dolphinscheduler_api_mixed_with_autoware_versions():
    warning = public_workspace_mismatch({
        "workspace": "Apache DolphinScheduler",
        "repository": "apache/dolphinscheduler",
        "baseline_version": "0.51.0", "current_version": "0.52.0",
        "languages": ["zh-CN", "en-US"],
    }, public_demo=True)

    assert warning is not None
    assert "Apache DolphinScheduler" in warning
    assert "RAG_API_BASE_URL" in warning


def test_public_profile_accepts_the_pinned_autoware_english_corpus():
    assert public_workspace_mismatch({
        "workspace": "Autoware",
        "repository": "autowarefoundation/autoware_universe",
        "languages": ["en-US"],
    }, public_demo=True) is None


def test_workspace_snapshot_distinguishes_documents_from_versioned_sources():
    snapshot = workspace_snapshot({
        "unique_document_count": 13, "source_count": 26, "chunk_count": 562,
    })

    assert "13 份不同资料" in snapshot
    assert "26 条版本化来源" in snapshot
    assert "562 个检索片段" in snapshot
