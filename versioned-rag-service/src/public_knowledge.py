"""Pinned Apache DolphinScheduler public corpus search, separate from frozen V2."""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
import unicodedata
from collections import Counter
from pathlib import Path

import numpy as np

from src.document_relations import DocumentRelationIndex


ROOT = Path(__file__).resolve().parents[1] / "public_corpus"
TOKEN_RE = re.compile(r"[a-z][a-z0-9_.-]*|[0-9]+|[\u3400-\u9fff]+", re.I)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
BM25_DIVERSITY_PREFIX = {
    "bm25_source_diverse": 0,
    "bm25_top2_diverse": 2,
    "bm25_top3_diverse": 3,
}
SUPPORTED_POLICIES = ("dense", "bm25", "bm25_fields", *BM25_DIVERSITY_PREFIX, "hybrid")
BM25_FIELD_WEIGHTS = {"title": 3.0, "heading_path": 4.0, "body": 1.0}


def tokens(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    result = []
    for match in TOKEN_RE.finditer(normalized):
        word = match.group()
        if "\u3400" <= word[0] <= "\u9fff":
            result.extend(word[i:i + 2] for i in range(max(1, len(word) - 1)))
        else:
            result.append(word)
    return result


def dense_vector(text: str, dimension: int = 512) -> np.ndarray:
    """Deployment-sized dense hashing baseline; lexical, not a neural semantic model."""
    normalized = "".join(c.casefold() for c in unicodedata.normalize("NFKC", text) if not c.isspace())
    vector = np.zeros(dimension, dtype=np.float32)
    for width in (1, 2, 3):
        for i in range(max(0, len(normalized) - width + 1)):
            digest = hashlib.sha256(normalized[i:i + width].encode("utf-8")).digest()
            vector[int.from_bytes(digest[:4], "big") % dimension] += 1
    norm = np.linalg.norm(vector)
    if norm:
        vector /= norm
    return vector


def _parts(text: str, max_chars: int = 1250) -> list[tuple[str, list[str], str]]:
    heading_path: list[str] = []
    body: list[str] = []
    sections: list[tuple[str, list[str], str]] = []
    def flush() -> None:
        nonlocal body
        raw = "\n".join(body).strip()
        if raw:
            paragraphs = re.split(r"\n\s*\n", raw)
            piece = ""
            for paragraph in paragraphs:
                if len(piece) + len(paragraph) > max_chars and piece:
                    sections.append((heading_path[-1] if heading_path else "", list(heading_path), piece.strip()))
                    piece = ""
                if len(paragraph) > max_chars:
                    for offset in range(0, len(paragraph), max_chars):
                        segment = paragraph[offset:offset + max_chars]
                        if piece:
                            sections.append((heading_path[-1] if heading_path else "", list(heading_path), piece.strip()))
                        piece = segment
                else:
                    piece += ("\n\n" if piece else "") + paragraph
            if piece:
                sections.append((heading_path[-1] if heading_path else "", list(heading_path), piece.strip()))
        body = []
    for line in text.splitlines():
        found = HEADING_RE.match(line)
        if found:
            flush()
            level = len(found.group(1))
            heading_path = heading_path[:level - 1]
            heading_path.append(found.group(2).strip())
        else:
            body.append(line)
    flush()
    return sections


def _document_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        found = HEADING_RE.match(line)
        if found and len(found.group(1)) == 1:
            return found.group(2).strip()
    return fallback


def build_index(root: Path = ROOT) -> dict:
    manifest = json.loads((root / "corpus_manifest.json").read_text(encoding="utf-8"))
    chunks = []
    for source in manifest["sources"]:
        raw = (root / source["local_path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != source["sha256"]:
            raise ValueError(f"source changed: {source['local_path']}")
        body = raw.decode("utf-8")
        document_title = _document_title(body, source["document_key"])
        for number, (heading, heading_path, content) in enumerate(_parts(body), start=1):
            key = f"{source['version']}:{source['language']}:{source['document_key']}"
            chunks.append({
                "chunk_id": f"{key}:{number}", "document_id": key,
                "document_key": source["document_key"], "version": source["version"],
                "locale": source["locale"], "language": source["language"],
                "source_type": source["source_type"], "source_url": source["source_url"],
                "document_title": document_title, "heading": heading,
                "heading_path": heading_path, "content": content,
                "repository": source["repository"], "document_path": source["document_path"],
                **{
                    field: source[field]
                    for field in (
                        "canonical_url", "rendered_url", "english_source_url",
                        "translation_alignment_status", "release_alignment_status",
                    )
                    if source.get(field)
                },
            })
    vectors = np.stack([
        dense_vector(c["heading"] + " " + c["document_key"] + " " + c["content"])
        for c in chunks
    ])
    (root / "chunks.json").write_text(
        json.dumps(chunks, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    np.save(root / "dense_vectors.npy", vectors)
    policy_path = root / "retrieval_policy.json"
    if policy_path.exists():
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        policy["benchmark_corpus_sha256"] = hashlib.sha256(
            (root / "corpus_manifest.json").read_bytes()
        ).hexdigest()
        policy["index_artifacts_sha256"] = {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in ("chunks.json", "dense_vectors.npy")
        }
        policy_path.write_text(
            json.dumps(policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n",
        )
    return {"files": len(manifest["sources"]), "chunks": len(chunks), "dimension": vectors.shape[1]}


class PublicKnowledgeIndex:
    def __init__(self, root: Path = ROOT):
        self.root = root
        self.manifest = json.loads((root / "corpus_manifest.json").read_text(encoding="utf-8"))
        # Relationship integrity is independent from ordinary retrieval. An absent or
        # stale registry disables relationship claims, but leaves corpus search usable.
        self.document_relations = DocumentRelationIndex.from_corpus(root, self.manifest)
        self.chunks = json.loads((root / "chunks.json").read_text(encoding="utf-8"))
        self.matrix = np.load(root / "dense_vectors.npy", allow_pickle=False)
        if len(self.chunks) != len(self.matrix):
            raise ValueError("public corpus index size mismatch")
        self.term_freqs = [Counter(tokens(c["heading"] + " " + c["document_key"] + " " + c["content"])) for c in self.chunks]
        self.lengths = np.array([sum(row.values()) for row in self.term_freqs])
        self.avg_length = float(np.mean(self.lengths))
        self.doc_freq = Counter()
        for row in self.term_freqs:
            self.doc_freq.update(row.keys())
        self.field_term_freqs = {
            "title": [Counter(tokens(c.get("document_title", c["document_key"]) + " " + c["document_key"])) for c in self.chunks],
            "heading_path": [Counter(tokens(" ".join(c.get("heading_path", [c["heading"]])))) for c in self.chunks],
            "body": [Counter(tokens(c["content"])) for c in self.chunks],
        }
        self.field_lengths = {
            field: np.array([sum(row.values()) for row in rows])
            for field, rows in self.field_term_freqs.items()
        }
        self.field_avg_lengths = {
            field: max(float(np.mean(lengths)), 1.0)
            for field, lengths in self.field_lengths.items()
        }
        self.field_doc_freq = Counter()
        for chunk_fields in zip(*self.field_term_freqs.values()):
            self.field_doc_freq.update(set().union(*(row.keys() for row in chunk_fields)))
        policy_path = root / "retrieval_policy.json"
        self.policy = json.loads(policy_path.read_text(encoding="utf-8")) if policy_path.exists() else {}
        if self.policy and self.policy.get("default_policy") not in SUPPORTED_POLICIES:
            raise ValueError("unvalidated public retrieval policy")
        expected_manifest_hash = self.policy.get("benchmark_corpus_sha256")
        manifest_hash = hashlib.sha256((root / "corpus_manifest.json").read_bytes()).hexdigest()
        if expected_manifest_hash != manifest_hash:
            raise ValueError("public retrieval policy does not match pinned corpus")
        for source in self.manifest["sources"]:
            if hashlib.sha256((root / source["local_path"]).read_bytes()).hexdigest() != source["sha256"]:
                raise ValueError("public corpus source hash mismatch")
        artifact_hashes = self.policy.get("index_artifacts_sha256")
        if not isinstance(artifact_hashes, dict):
            raise ValueError("public corpus index artifact hash mismatch")
        for name in ("chunks.json", "dense_vectors.npy"):
            actual_hash = hashlib.sha256((root / name).read_bytes()).hexdigest()
            if actual_hash != artifact_hashes.get(name):
                raise ValueError(f"public corpus index artifact hash mismatch: {name}")

    def _bm25(self, query: str) -> np.ndarray:
        scores = np.zeros(len(self.chunks), dtype=np.float32)
        n = len(self.chunks)
        for term in set(tokens(query)):
            df = self.doc_freq.get(term, 0)
            if not df:
                continue
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            for i, row in enumerate(self.term_freqs):
                tf = row.get(term, 0)
                if tf:
                    scores[i] += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * self.lengths[i] / self.avg_length))
        return scores

    def _bm25_fields(self, query: str) -> np.ndarray:
        scores = np.zeros(len(self.chunks), dtype=np.float32)
        n = len(self.chunks)
        for term in set(tokens(query)):
            df = self.field_doc_freq.get(term, 0)
            if not df:
                continue
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            for field, rows in self.field_term_freqs.items():
                weight = BM25_FIELD_WEIGHTS[field]
                lengths = self.field_lengths[field]
                avg_length = self.field_avg_lengths[field]
                for i, row in enumerate(rows):
                    tf = row.get(term, 0)
                    if tf:
                        scores[i] += weight * idf * tf * 2.2 / (
                            tf + 1.2 * (0.25 + 0.75 * lengths[i] / avg_length)
                        )
        return scores

    def _version_members(self, version: str) -> set[str] | None:
        """Resolve an exact snapshot or a declared composite scope to source versions."""
        if version == "current":
            version = str(self.manifest.get("current_version", ""))
        if version == "all":
            return None
        source_versions = {str(source["version"]) for source in self.manifest.get("sources", [])}
        scopes = self.manifest.get("version_scopes", {})
        if isinstance(scopes, dict) and version in scopes:
            definition = scopes[version]
            members = definition.get("versions") if isinstance(definition, dict) else None
            if (
                not isinstance(members, list) or not members
                or any(not isinstance(member, str) or member not in source_versions for member in members)
            ):
                raise ValueError("invalid public corpus version scope")
            return set(members)
        if version in source_versions:
            return {version}
        raise ValueError("unsupported public corpus scope")

    def search(
        self, query: str, *, top_k: int = 5, version: str = "current",
        language: str = "zh_preferred", policy: str | None = None,
    ) -> list[dict]:
        if not query.strip() or len(query) > 4000 or not 1 <= top_k <= 20:
            raise ValueError("invalid search request")
        try:
            version_members = self._version_members(version)
        except ValueError:
            raise
        if language not in ("zh_preferred", "all", "zh", "en"):
            raise ValueError("unsupported public corpus scope")
        policy = policy or self.policy.get("default_policy")
        if policy not in SUPPORTED_POLICIES:
            raise ValueError("unsupported retrieval policy")
        dense = self.matrix @ dense_vector(query) if policy in ("dense", "hybrid") else None
        sparse = self._bm25(query) if policy in ("bm25", "hybrid") or policy in BM25_DIVERSITY_PREFIX else None
        fielded_sparse = self._bm25_fields(query) if policy == "bm25_fields" else None
        eligible = [
            i for i, chunk in enumerate(self.chunks)
            if (version_members is None or chunk["version"] in version_members)
            and (language not in ("zh", "en") or chunk["language"] == language)
        ]
        # Language preference is a candidate tie-break, not a hard filter.
        def ranked(scores: np.ndarray) -> list[int]:
            return sorted(eligible, key=lambda i: (scores[i], self.chunks[i]["language"] == "zh" if language == "zh_preferred" else False), reverse=True)
        if policy == "dense":
            order = ranked(dense)
            score = dense
        elif policy == "bm25":
            order = ranked(sparse)
            score = sparse
        elif policy in BM25_DIVERSITY_PREFIX:
            # Experimental discovery: retain the fixed BM25 prefix, then cover
            # distinct positive-score sources before filling in BM25 order.
            # The production default and original BM25 scores stay unchanged.
            bm25_order = ranked(sparse)
            prefix_count = min(BM25_DIVERSITY_PREFIX[policy], top_k)
            distinct = bm25_order[:prefix_count]
            seen_sources = {self.chunks[i]["document_id"] for i in distinct}
            for i in bm25_order[prefix_count:]:
                if sparse[i] <= 0:
                    continue
                document_id = self.chunks[i]["document_id"]
                if document_id not in seen_sources:
                    distinct.append(i)
                    seen_sources.add(document_id)
                    if len(distinct) == top_k:
                        break
            selected = set(distinct)
            order = distinct + [i for i in bm25_order if i not in selected]
            score = sparse
        elif policy == "bm25_fields":
            order = ranked(fielded_sparse)
            score = fielded_sparse
        else:
            a = ranked(dense)
            b = ranked(sparse)
            fused = np.zeros(len(self.chunks), dtype=np.float32)
            for rank, i in enumerate(a[:50], start=1):
                fused[i] += 1 / (60 + rank)
            for rank, i in enumerate(b[:50], start=1):
                fused[i] += 1 / (60 + rank)
            order = ranked(fused)
            score = fused
        result = []
        for rank, i in enumerate(order[:top_k], start=1):
            result.append({**self.chunks[i], "rank": rank, "retrieval_score": float(score[i]), "retrieval_policy": policy})
        return result


def verified_consistency_notes(hits: list[dict]) -> list[dict]:
    """Report exact text/version differences, never infer a semantic contradiction."""
    notes = []
    seen = set()
    for left_pos, left in enumerate(hits):
        for right in hits[left_pos + 1:]:
            if (
                left["document_key"] != right["document_key"]
                or left["version"] == right["version"]
                or left.get("language") != right.get("language")
                or left.get("repository") != right.get("repository")
            ):
                continue
            if left["heading"] != right["heading"] or left["content"] == right["content"]:
                continue
            key = (left["document_key"], left["heading"], *sorted((left["version"], right["version"])))
            if key in seen:
                continue
            seen.add(key)
            notes.append({
                "kind": "verified_version_text_difference",
                "document_key": left["document_key"], "heading": left["heading"],
                "sources": [
                    {"version": row["version"], "locale": row["locale"], "source_url": row["source_url"]}
                    for row in (left, right)
                ],
                "message": "同一官方文档章节在两个固定版本中的文字不同；这不等同于事实矛盾，请结合来源版本确认。",
            })
    assignments = {}
    assignment_re = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_.-]{2,})\s*[=:]\s*([A-Za-z0-9_.-]+)\s*$")
    for hit in hits:
        for line in hit["content"].splitlines():
            found = assignment_re.fullmatch(line)
            if not found:
                continue
            key = (hit["document_key"], hit["heading"], found.group(1).casefold())
            assignments.setdefault(key, []).append((found.group(2), hit))
    for (document_key, heading, parameter), values in assignments.items():
        unique = {}
        for value, hit in values:
            unique.setdefault(value, hit)
        if len(unique) < 2:
            continue
        notes.append({
            "kind": "verified_literal_value_difference",
            "document_key": document_key, "heading": heading,
            "parameter": parameter,
            "values": list(unique),
            "sources": [
                {"version": hit["version"], "locale": hit["locale"],
                 "source_url": hit["source_url"]} for hit in unique.values()
            ],
            "message": f"同一章节中的配置项 {parameter} 出现不同的明确字面值；请结合上下文、版本和来源确认。",
        })
    return notes


if __name__ == "__main__":
    started = time.perf_counter()
    print(build_index())
    print(f"build_seconds={time.perf_counter() - started:.3f}")
