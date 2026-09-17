from __future__ import annotations

import json

import config


def test_document_display_names_uses_original_filename_without_source_path(tmp_path, monkeypatch):
    manifest = tmp_path / "normalization_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "document_id": "rdv2-test",
                        "source_file_name": "研发资料/软件详细设计说明.doc",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "NORMALIZATION_MANIFEST", manifest)

    names = config.document_display_names()

    assert names["rdv2-test"] == "软件详细设计说明.doc"
    assert names["safe-demo-12p"] == "RAG-RD-V2 合成规格说明.pdf"


def test_internal_data_requires_explicit_rag_query_override():
    disabled = config.DemoConfig(demo_data_classification="Internal / Retrieval Only")
    enabled = config.DemoConfig(
        demo_data_classification="Internal / Retrieval Only",
        allow_rag_query=True,
    )

    assert disabled.online_generation_allowed is False
    assert enabled.online_generation_allowed is True
