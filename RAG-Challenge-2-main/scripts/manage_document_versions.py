"""Local CLI for the V3 version lifecycle service.

The CLI accepts section snapshots produced by the existing parser and a local
precomputed embedding map.  It never uploads source text or introduces a new
embedding model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from dataclasses import asdict
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.document_lifecycle import SectionSnapshot, VersionLifecycleService


def content_hash(value: str) -> str:
    normalized = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class PrecomputedEmbedder:
    def __init__(self, path: Path):
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.vectors = payload.get("vectors", payload)
        if not isinstance(self.vectors, dict):
            raise ValueError("embedding map must contain an object of content_hash -> vector")

    def encode(self, texts):
        missing = [content_hash(text) for text in texts if content_hash(text) not in self.vectors]
        if missing:
            raise ValueError(f"precomputed embeddings missing for {len(missing)} content hashes")
        return np.asarray([self.vectors[content_hash(text)] for text in texts], dtype=np.float32)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="RAG V3 local document version management")
    commands = root.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest-version")
    ingest.add_argument("--store-root", type=Path, required=True)
    ingest.add_argument("--document-id", required=True)
    ingest.add_argument("--project-id", required=True)
    ingest.add_argument("--document-type", required=True)
    ingest.add_argument("--title", required=True)
    ingest.add_argument("--version-id", required=True)
    ingest.add_argument("--version-label", required=True)
    ingest.add_argument("--source-file", type=Path, required=True)
    ingest.add_argument("--sections-json", type=Path, required=True)
    ingest.add_argument("--embedding-map", type=Path, required=True)
    ingest.add_argument("--no-activate", action="store_true")
    activate = commands.add_parser("activate-version")
    activate.add_argument("--store-root", type=Path, required=True)
    activate.add_argument("--version-id", required=True)
    diff = commands.add_parser("diff")
    diff.add_argument("--store-root", type=Path, required=True)
    diff.add_argument("--document-id", required=True)
    diff.add_argument("--from-version-id", required=True)
    diff.add_argument("--to-version-id", required=True)
    catalog = commands.add_parser("catalog")
    catalog.add_argument("--store-root", type=Path, required=True)
    return root


def main() -> int:
    args = parser().parse_args()
    service = VersionLifecycleService(args.store_root)
    if args.command == "ingest-version":
        rows = json.loads(args.sections_json.read_text(encoding="utf-8"))
        sections = [SectionSnapshot.model_validate(item) for item in rows]
        report = service.ingest_version(
            document_id=args.document_id,
            project_id=args.project_id,
            document_type=args.document_type,
            title=args.title,
            version_id=args.version_id,
            version_label=args.version_label,
            source_bytes=args.source_file.read_bytes(),
            source_name=args.source_file.name,
            sections=sections,
            embedder=PrecomputedEmbedder(args.embedding_map),
            activate=not args.no_activate,
        )
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    elif args.command == "activate-version":
        service.activate_version(args.version_id)
        print(json.dumps({"activated": args.version_id}, ensure_ascii=False))
    elif args.command == "diff":
        result = service.diff(args.document_id, args.from_version_id, args.to_version_id)
        print(result.model_dump_json(indent=2))
    else:
        print(json.dumps({"documents": service.catalog.document_rows()}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

