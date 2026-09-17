"""Read-only cross-boundary provenance check for the safe synthetic demo."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--evidence-json", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads((args.artifact_root / "artifact_manifest.json").read_text(encoding="utf-8"))
    project_root = Path(__file__).resolve().parents[1]
    chunks_path = project_root / manifest["artifacts"]["chunk_artifact"]["path"]
    chunks = {
        item["chunk_id"]: item
        for item in (json.loads(line) for line in chunks_path.read_text(encoding="utf-8").splitlines())
    }
    payload = json.loads(args.evidence_json.read_text(encoding="utf-8"))
    assert payload["requires_human_review"] is True
    assert payload["evidence"]
    seen = set()
    for evidence in payload["evidence"]:
        chunk = chunks[evidence["chunk_id"]]
        assert evidence["evidence_id"] not in seen
        seen.add(evidence["evidence_id"])
        assert evidence["document_id"] == chunk["document_id"]
        assert evidence["section_id"] == chunk["section_id"]
        assert evidence["section_path"] == chunk["section_path"]
        assert evidence["page_number"] == chunk["page_number"]
        normalized = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", chunk["text"])).strip()
        assert evidence["content"] == normalized
        assert evidence["content_hash"] == hashlib.sha256(normalized.encode()).hexdigest()
        assert evidence["source_type"] == "RAG"
    print(f"EVIDENCE_METADATA_PRESERVED=PASS UNIQUE_IDS=PASS records={len(seen)}")


if __name__ == "__main__":
    main()
