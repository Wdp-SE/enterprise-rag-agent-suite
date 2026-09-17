"""Select a bounded representative corpus using inventory metadata only."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


TARGET_TYPES = ("requirements", "detailed_design", "test_or_acceptance")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    selected = []
    for document_type in TARGET_TYPES:
        candidates = [
            item for item in inventory["files"] if item["document_type"] == document_type
        ]
        if not candidates:
            continue
        item = sorted(candidates, key=lambda row: (row["size"], row["relative_path"]))[0]
        document_id = f"rdv2-{item['sha256'][:16]}"
        selected.append(
            {
                "document_id": document_id,
                "source_file_name": item["file_name"],
                "source_relative_path": item["relative_path"],
                "source_extension": item["extension"],
                "source_size": item["size"],
                "source_sha256": item["sha256"],
                "document_type": item["document_type"],
                "selection_basis": "filename_only_representative_category",
                "staged_relative_path": f"raw/{document_id}{item['extension']}",
                "normalized_relative_path": f"normalized/pdfs/{document_id}.pdf",
            }
        )

    if not selected:
        raise SystemExit("No representative document could be selected from filename metadata")
    if len(selected) > 3:
        raise SystemExit("Representative selection exceeds the maximum of three documents")

    payload = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "selection_uses_document_body": False,
        "maximum_documents": 3,
        "selected_count": len(selected),
        "documents": selected,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            [
                {"document_id": item["document_id"], "document_type": item["document_type"]}
                for item in selected
            ],
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
