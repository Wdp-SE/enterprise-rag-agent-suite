from services.public_workspace_profile import public_workspace_mismatch, workspace_snapshot


def _edge_workspace(**overrides):
    return {
        "workspace_id": "edge_ai_device",
        "domain_profile": {"id": "edge_ai_device"},
        "workspace": "reComputer Industrial / Jetson 边缘 AI 工程知识",
        "repository": "Seeed-Studio/wiki-documents",
        "repositories": ["Seeed-Studio/wiki-documents"],
        "languages": ["zh"],
        **overrides,
    }


def test_public_demo_accepts_only_the_chinese_edge_ai_workspace():
    assert public_workspace_mismatch(_edge_workspace(), public_demo=True) is None


def test_public_demo_rejects_old_or_unrelated_workspace_ids():
    warning = public_workspace_mismatch(_edge_workspace(workspace_id="unrelated_workspace"), public_demo=True)

    assert warning is not None
    assert "知识空间不匹配" in warning
    assert "请联系维护者" in warning
    assert "RAG_API_BASE_URL" not in warning


def test_public_demo_rejects_wrong_repository_domain_profile_or_language():
    for patch in (
        {"repository": "other/project"},
        {"domain_profile": {"id": "other"}},
        {"languages": ["en"]},
    ):
        assert public_workspace_mismatch(_edge_workspace(**patch), public_demo=True)


def test_workspace_snapshot_reports_the_current_corpus_size():
    snapshot = workspace_snapshot({
        "unique_document_count": 18, "source_count": 18, "chunk_count": 394,
    })

    assert "18 个主题" in snapshot
    assert "394 个检索片段" in snapshot
