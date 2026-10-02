from services.public_workspace_profile import public_workspace_mismatch, workspace_snapshot


def test_public_profile_flags_a_dolphinscheduler_api_mixed_with_autoware_versions():
    warning = public_workspace_mismatch({
        "workspace": "Apache DolphinScheduler",
        "repository": "apache/dolphinscheduler",
        "baseline_version": "0.51.0", "current_version": "0.52.0",
        "languages": ["zh-CN", "en-US"],
    }, public_demo=True)

    assert warning is not None
    assert "Autoware 工作台不匹配" in warning
    assert "请联系维护者" in warning
    assert "Apache DolphinScheduler" not in warning
    assert "RAG_API_BASE_URL" not in warning
    assert "RAG_PUBLIC_CORPUS_ROOT" not in warning


def test_public_profile_accepts_the_pinned_chinese_autoware_community_corpus():
    assert public_workspace_mismatch({
        "workspace": "Autoware",
        "repository": "tomato-ros/autoware-documentation-cn",
        "repositories": ["tomato-ros/autoware-documentation-cn"],
        "languages": ["zh-CN"],
    }, public_demo=True) is None


def test_public_profile_rejects_a_bilingual_workspace_for_chinese_only_demo():
    warning = public_workspace_mismatch({
        "workspace": "Autoware",
        "repository": "tomato-ros/autoware-documentation-cn",
        "repositories": ["tomato-ros/autoware-documentation-cn"],
        "languages": ["en-US", "zh-CN"],
    }, public_demo=True)

    assert warning is not None


def test_workspace_snapshot_distinguishes_documents_from_versioned_sources():
    snapshot = workspace_snapshot({
        "unique_document_count": 13, "source_count": 26, "chunk_count": 562,
    })

    assert "13 个主题" in snapshot
    assert "562 个检索片段" in snapshot
    assert "检索策略以真实评测结果为准" not in snapshot
