"""Command-line entry point for enterprise R&D document knowledge service."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from dataclasses import asdict
from pathlib import Path

import numpy as np

from src.document_lifecycle import SectionSnapshot, VersionLifecycleService
from src.rd_v2_runtime import FrozenArtifactValidator, RDV2Settings


def content_hash(value: str) -> str:
    normalized = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class PrecomputedEmbedder:
    """Load an audited content-hash-to-vector map for version ingestion."""

    def __init__(self, path: Path):
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.vectors = payload.get("vectors", payload)
        if not isinstance(self.vectors, dict):
            raise ValueError(
                "embedding map must contain an object of content_hash -> vector"
            )

    def encode(self, texts):
        hashes = [content_hash(text) for text in texts]
        missing = [value for value in hashes if value not in self.vectors]
        if missing:
            raise ValueError(
                f"precomputed embeddings missing for {len(missing)} content hashes"
            )
        return np.asarray([self.vectors[value] for value in hashes], dtype=np.float32)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="企业研发文档知识服务：Dense-only 检索、版本治理与可信问答"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="启动 FastAPI 服务")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)

    commands.add_parser("validate-artifacts", help="校验冻结检索资产")

    ingest = commands.add_parser("ingest-version", help="增量写入规范化文档版本")
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

    activate = commands.add_parser("activate-version", help="切换活动文档版本")
    activate.add_argument("--store-root", type=Path, required=True)
    activate.add_argument("--version-id", required=True)

    diff = commands.add_parser("diff", help="比较两个文档版本")
    diff.add_argument("--store-root", type=Path, required=True)
    diff.add_argument("--document-id", required=True)
    diff.add_argument("--from-version-id", required=True)
    diff.add_argument("--to-version-id", required=True)

    catalog = commands.add_parser("catalog", help="查看文档与版本目录")
    catalog.add_argument("--store-root", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "serve":
        import uvicorn

        uvicorn.run("src.rd_v2_api:app", host=args.host, port=args.port)
        return 0
    if args.command == "validate-artifacts":
        settings = RDV2Settings.from_env(Path.cwd())
        bundle = FrozenArtifactValidator(settings).validate_and_load()
        print(
            json.dumps(
                {
                    "status": "COMPLETE",
                    "retrieval_policy": settings.retrieval_policy,
                    "dense_representation": settings.dense_representation,
                    "document_count": len(bundle.catalog.documents),
                    "chunk_count": len(bundle.chunks),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

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
        result = service.diff(
            args.document_id,
            args.from_version_id,
            args.to_version_id,
        )
        print(result.model_dump_json(indent=2))
    else:
        print(
            json.dumps(
                {"documents": service.catalog.document_rows()},
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
