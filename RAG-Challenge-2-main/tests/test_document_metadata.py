import json

import pytest

from src.document_metadata import normalize_document_metadata, stable_document_id
from src.pdf_parsing import PDFParser
from src.text_splitter import TextSplitter


def test_legacy_sha1_is_reused_as_stable_document_id():
    metadata = normalize_document_metadata(
        {"sha1_name": "abc123", "company_name": "Example Corp"}
    )

    assert metadata["document_id"] == "abc123"
    assert metadata["title"] == "Example Corp"
    assert metadata["legacy_company_name"] == "Example Corp"
    assert metadata["company_name"] == "Example Corp"


def test_document_id_is_repeatable_and_not_based_on_title():
    first = stable_document_id(source_identifier="documents/policy.pdf")
    second = stable_document_id(source_identifier="other/path/policy.pdf")

    assert first == second
    assert first != "Policy title"
    assert len(first) == 40


def test_invalid_explicit_document_id_is_rejected():
    with pytest.raises(ValueError, match="document_id"):
        normalize_document_metadata(
            {"document_id": "unsafe/path", "title": "Policy", "source": "policy.pdf"}
        )


def test_splitter_propagates_document_id_to_pages_and_chunks(monkeypatch):
    splitter = TextSplitter()
    monkeypatch.setattr(
        splitter,
        "_split_page",
        lambda page: [{"page": page["page"], "length_tokens": 1, "text": page["text"]}],
    )
    report = {
        "metainfo": {
            "document_id": "policy-2026",
            "title": "Policy",
            "source": "policy.pdf",
        },
        "content": {"pages": [{"page": 3, "text": "Requirement"}]},
    }

    result = splitter._split_report(json.loads(json.dumps(report)))

    assert result["content"]["pages"][0]["document_id"] == "policy-2026"
    assert result["content"]["chunks"][0]["document_id"] == "policy-2026"
    assert result["content"]["chunks"][0]["chunk_id"] == "policy-2026:0"


def test_generic_metadata_csv_can_be_keyed_by_document_id(tmp_path):
    metadata_csv = tmp_path / "metadata.csv"
    metadata_csv.write_text(
        "document_id,title,document_type,source,source_url,category,tags\n"
        "policy-2026,Safety Policy,policy,regulator,https://example.test/policy,safety,inspection\n",
        encoding="utf-8",
    )

    lookup = PDFParser._parse_csv_metadata(metadata_csv)

    assert lookup["policy-2026"]["title"] == "Safety Policy"
    assert lookup["policy-2026"]["document_type"] == "policy"
