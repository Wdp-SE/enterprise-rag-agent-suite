"""Validated, corpus-bound relationships between exact public document snapshots."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


RELATION_TYPES = frozenset({
    "translation_of",
    "localized_variant_of",
    "references_or_depends_on",
    "supersedes",
    "none",
})
VERIFICATION_STATES = frozenset({"verified", "candidate", "unknown"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_FIELDS = frozenset({
    "relation_id", "relation_type", "verification_status",
    "source_document_id", "target_document_id", "verification_evidence",
})


def document_id(source: dict) -> str:
    """Return the stable ID used by chunks for one exact version/language source."""
    return f"{source['version']}:{source['language']}:{source['document_key']}"


class DocumentRelationIndex:
    """Immutable-by-convention relation lookup; invalid registries expose no claims."""

    def __init__(self, rows: list[dict] | None = None, *, status: str = "ready", issue: str | None = None):
        self.available = status == "ready"
        self.status = status
        self.issue = issue
        self._by_document: dict[str, list[dict]] = defaultdict(list)
        self._rows = [dict(row) for row in (rows or [])] if self.available else []
        for row in self._rows:
            self._by_document[row["source_document_id"]].append(dict(row))
            self._by_document[row["target_document_id"]].append(dict(row))

    @classmethod
    def from_corpus(cls, root: Path, manifest: dict) -> "DocumentRelationIndex":
        root = Path(root)
        registry_path = root / "document_relations.json"
        manifest_path = root / "corpus_manifest.json"
        if not registry_path.exists():
            return cls(status="missing", issue="relationship registry not present")
        try:
            manifest_bytes = manifest_path.read_bytes()
            actual_hash = hashlib.sha256(manifest_bytes).hexdigest()
            on_disk_manifest = json.loads(manifest_bytes.decode("utf-8"))
            raw = json.loads(registry_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return cls(status="invalid", issue="relationship registry or corpus manifest cannot be read")

        if on_disk_manifest != manifest:
            return cls(status="invalid", issue="loaded corpus manifest differs from pinned manifest")
        if not isinstance(raw, dict) or raw.get("schema_version") != 1:
            return cls(status="invalid", issue="unsupported relationship registry schema")
        bound_hash = raw.get("corpus_manifest_sha256")
        if not isinstance(bound_hash, str) or not _SHA256_RE.fullmatch(bound_hash) or bound_hash != actual_hash:
            return cls(status="invalid", issue="relationship registry does not match pinned corpus")
        rows = raw.get("relations")
        if not isinstance(rows, list):
            return cls(status="invalid", issue="relationship rows must be a list")

        known_documents = set()
        try:
            for source in manifest.get("sources", []):
                if not all(isinstance(source.get(key), (str, int)) for key in ("version", "language", "document_key")):
                    raise ValueError("invalid document identity")
                known_documents.add(document_id(source))
        except (AttributeError, KeyError, TypeError, ValueError):
            return cls(status="invalid", issue="corpus contains an invalid document identity")

        normalized = []
        relation_ids = set()
        for row in rows:
            if not isinstance(row, dict) or not _REQUIRED_FIELDS.issubset(row):
                return cls(status="invalid", issue="relationship row is incomplete")
            relation_id = row["relation_id"]
            relation_type = row["relation_type"]
            state = row["verification_status"]
            source_id = row["source_document_id"]
            target_id = row["target_document_id"]
            evidence = row["verification_evidence"]
            if (
                not isinstance(relation_id, str) or not relation_id.strip() or relation_id in relation_ids
                or relation_type not in RELATION_TYPES or state not in VERIFICATION_STATES
                or not isinstance(source_id, str) or source_id not in known_documents
                or not isinstance(target_id, str) or target_id not in known_documents or source_id == target_id
                or not isinstance(evidence, str) or not evidence.strip() or len(evidence) > 1000
            ):
                return cls(status="invalid", issue="relationship row failed validation")
            relation_ids.add(relation_id)
            normalized.append({key: row[key] for key in _REQUIRED_FIELDS})

        return cls(normalized)

    def for_document(self, document_id: str) -> list[dict]:
        return [dict(row) for row in self._by_document.get(document_id, ())]

    def summary(self) -> dict:
        types = Counter(row["relation_type"] for row in self._rows)
        states = Counter(row["verification_status"] for row in self._rows)
        return {
            "status": self.status,
            "available": self.available,
            "issue": self.issue,
            "relation_count": len(self._rows),
            "by_type": dict(sorted(types.items())),
            "by_verification_status": dict(sorted(states.items())),
            "verified_translation_pairs": sum(
                row["relation_type"] == "translation_of" and row["verification_status"] == "verified"
                for row in self._rows
            ),
        }
