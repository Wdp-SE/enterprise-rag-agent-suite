"""Build the integrity-locked search sidecar from reviewed figure OCR only."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from scripts.figure_evidence import build_reviewed_figure_chunks


def build_reviewed_figure_sidecar(root: Path) -> dict:
    root = Path(root)
    manifest_bytes = (root / "corpus_manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    inventory = json.loads((root / "figure_evidence.json").read_text(encoding="utf-8"))
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    if inventory.get("schema_version") != 1 or inventory.get("corpus_manifest_sha256") != manifest_sha:
        raise ValueError("figure inventory does not match the pinned corpus manifest")
    chunks = build_reviewed_figure_chunks(inventory.get("figures", []), manifest)
    sidecar = {
        "schema_version": 1,
        "corpus_manifest_sha256": manifest_sha,
        "chunks": chunks,
    }
    sidecar_path = root / "figure_evidence_reviewed.json"
    sidecar_bytes = (json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    sidecar_path.write_bytes(sidecar_bytes)
    lock = {
        "schema_version": 1,
        "sidecar_sha256": hashlib.sha256(sidecar_bytes).hexdigest(),
        "corpus_manifest_sha256": manifest_sha,
    }
    (root / "figure_evidence_reviewed.lock.json").write_text(
        json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n",
    )
    return {"approved_figure_chunks": len(chunks), "sidecar_sha256": lock["sidecar_sha256"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(build_reviewed_figure_sidecar(args.root), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
