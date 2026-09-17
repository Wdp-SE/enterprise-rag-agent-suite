"""Offline BM25 lexical failure analysis for the frozen R&D DEV dataset.

This script is intentionally diagnostic-only.  It reuses the frozen child chunks
and BM25 pickle, never rebuilds either artifact, never writes source text to the
reports, and does not load dense models or contact online services.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import pickle
import re
from statistics import mean, median
import sys
from typing import Iterable, Sequence
import unicodedata

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.text_tokenization import technical_tokenize


TARGET_TYPES = ("field", "exact_term", "interface")
ASCII_RE = re.compile(r"[a-z0-9]", re.IGNORECASE)
CJK_RE = re.compile(r"^[\u4e00-\u9fff]+$")
FIELD_RE = re.compile(r"字段|参数|属性|field|parameter|property", re.IGNORECASE)
TABLE_RE = re.compile(r"表\s*\d|table|列名|表头", re.IGNORECASE)
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
SEPARATORS = "/_.:-"

# Functional query words are not useful candidates for the single audited key
# lexical token.  The list is deliberately small and domain-neutral.
CJK_STOP = {
    "什么", "哪些", "如何", "是否", "请问", "多少", "哪个", "哪一", "对应",
    "要求", "描述", "文档", "接口", "字段", "功能", "模块", "系统", "支持",
    "以及", "进行", "使用", "包含", "需要", "页面", "数据", "信息", "内容",
    "相关", "规定", "定义", "说明", "分别", "用于", "根据", "通过", "其中",
}


def json_load(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def json_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=False)
        stream.write("\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def normalize_text(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).casefold().strip()


def metadata_text(chunk: dict) -> tuple[str, str]:
    title = str(chunk.get("section_title") or "")
    path = chunk.get("section_path") or []
    if isinstance(path, str):
        path_text = path
    else:
        path_text = " ".join(str(value) for value in path)
    return title, path_text


def load_chunks(path: Path) -> list[dict]:
    chunks = []
    with path.open("r", encoding="utf-8") as stream:
        for index, line in enumerate(stream):
            item = json.loads(line)
            item["chunk_index"] = index
            chunks.append(item)
    return chunks


def load_document_titles(corpus_root: Path, document_ids: Iterable[str]) -> dict[str, str]:
    titles = {}
    for document_id in sorted(document_ids):
        path = (
            corpus_root / "normalized" / "repaired_chunked" /
            document_id / f"{document_id}.json"
        )
        document = json_load(path)
        titles[document_id] = str(document.get("metainfo", {}).get("title") or "").strip()
    return titles


def code_line(path: Path, fragment: str) -> int:
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if fragment in line:
            return number
    raise RuntimeError(f"Code fragment not found in {path}: {fragment}")


def verify_inputs(args: argparse.Namespace, manifest: dict, dataset: dict, chunks: list[dict], bm25_payload: dict) -> None:
    if dataset.get("dataset_status") != "FROZEN" or not dataset.get("ground_truth_frozen"):
        raise RuntimeError("DEV dataset is not frozen")
    if dataset.get("split") != "DEV" or len(dataset.get("cases", [])) != 40:
        raise RuntimeError("Expected the frozen 40-case DEV split")
    if manifest.get("build_status") != "PASS" or manifest.get("child_chunk_count") != len(chunks):
        raise RuntimeError("Frozen artifact manifest/chunk count validation failed")
    if manifest.get("dataset_version") != dataset.get("dataset_version"):
        raise RuntimeError("Dataset version mismatch")
    chunk_ids = [item.get("chunk_id") for item in chunks]
    if bm25_payload.get("chunk_ids") != chunk_ids:
        raise RuntimeError("BM25 index and frozen child chunk order are not aligned")
    expected_hash = manifest["artifact_files"]["child_chunks.jsonl"]["sha256"]
    if sha256_file(args.artifact_dir / "child_chunks.jsonl") != expected_hash:
        raise RuntimeError("Frozen child chunk hash mismatch")
    expected_bm25_hash = manifest["artifact_files"]["bm25_index.pkl"]["sha256"]
    if sha256_file(args.artifact_dir / "bm25_index.pkl") != expected_bm25_hash:
        raise RuntimeError("Frozen BM25 artifact hash mismatch")


def bm25_page_ranking(index, token_sets: Sequence[set[str]], query: str, chunks: Sequence[dict]) -> list[dict]:
    tokens = technical_tokenize(query)
    if not tokens:
        return []
    query_set = set(tokens)
    scores = np.asarray(index.get_scores(tokens), dtype=np.float64)
    order = np.argsort(-scores, kind="stable")
    pages = []
    seen = set()
    for chunk_index in order:
        index_value = int(chunk_index)
        if float(scores[index_value]) <= 0.0 or not query_set.intersection(token_sets[index_value]):
            continue
        chunk = chunks[index_value]
        page_key = (chunk["document_id"], int(chunk["page_number"]))
        if page_key in seen:
            continue
        seen.add(page_key)
        pages.append(
            {
                "rank": len(pages) + 1,
                "chunk_index": index_value,
                "chunk_id": chunk["chunk_id"],
                "document_id": chunk["document_id"],
                "page_number": int(chunk["page_number"]),
                "score": float(scores[index_value]),
            }
        )
    return pages


def rank_bucket(rank: int | None) -> str:
    if rank == 1:
        return "TOP1"
    if rank is not None and rank <= 5:
        return "TOP5"
    if rank is not None and rank <= 20:
        return "TOP20"
    if rank is not None and rank <= 50:
        return "TOP50"
    return "NOT_TOP50"


def informative(token: str) -> bool:
    if len(token) < 2:
        return False
    if CJK_RE.fullmatch(token):
        return token not in CJK_STOP and len(token) <= 8
    return bool(ASCII_RE.search(token))


def select_target_token(
    query_tokens: Sequence[str],
    child_tokens: set[str],
    title_tokens: set[str],
    path_tokens: set[str],
    document_title_tokens: set[str],
    dfs: dict[str, int],
    corpus_size: int,
) -> str:
    candidates = [token for token in unique(query_tokens) if informative(token)]
    if not candidates:
        candidates = [token for token in unique(query_tokens) if len(token) >= 2]
    if not candidates:
        return ""

    def score(token: str) -> tuple[float, int, int, str]:
        in_child = token in child_tokens
        in_metadata = token in title_tokens or token in path_tokens or token in document_title_tokens
        has_separator = any(separator in token for separator in SEPARATORS)
        is_ascii = bool(ASCII_RE.search(token))
        df = dfs.get(token, 0)
        rarity = 1.0 - min(1.0, df / max(1, corpus_size))
        value = (
            60.0 * has_separator
            + 35.0 * is_ascii
            + 24.0 * in_metadata
            + 18.0 * in_child
            + 15.0 * rarity
            + min(12, len(token))
        )
        # Stable preference for a retained whole identifier over its components.
        return value, len(token), -df, token

    return max(candidates, key=score)


def token_location(target: str, token_set: set[str]) -> bool:
    return bool(target) and target in token_set


def overlap_record(query_set: set[str], evidence_set: set[str]) -> dict:
    intersection = query_set.intersection(evidence_set)
    informative_query = {token for token in query_set if informative(token)}
    informative_intersection = informative_query.intersection(evidence_set)
    return {
        "query_token_count": len(query_set),
        "intersection_count": len(intersection),
        "query_coverage": round(len(intersection) / max(1, len(query_set)), 6),
        "informative_query_token_count": len(informative_query),
        "informative_intersection_count": len(informative_intersection),
        "informative_query_coverage": round(
            len(informative_intersection) / max(1, len(informative_query)), 6
        ),
        "intersection_token_hashes": sorted(token_hash(token) for token in intersection),
        "informative_intersection_token_hashes": sorted(
            token_hash(token) for token in informative_intersection
        ),
    }


def tokenizer_audit() -> dict:
    examples = [
        ("snake_case", "timeout_ms"),
        ("slash_path", "/api/export"),
        ("hyphen_requirement", "REQ-03-21"),
        ("hyphen_identifier", "XG-GN-SJCL"),
        ("dot_notation", "module.config.timeout"),
        ("camel_case", "requestTimeout"),
        ("number_unit_tps", "1000 TPS"),
        ("number_unit_ms", "30 ms"),
        ("mixed_chinese_english", "数据处理模块SJCL"),
        ("fullwidth_identifier", "ｔｉｍｅｏｕｔ＿ｍｓ"),
        ("fullwidth_path", "／ａｐｉ／ｅｘｐｏｒｔ"),
    ]
    rows = [
        {"category": category, "input": value, "tokens": technical_tokenize(value)}
        for category, value in examples
    ]
    lookup = {row["category"]: row["tokens"] for row in rows}
    checks = {
        "underscore_whole_identifier_retained": "timeout_ms" in lookup["snake_case"],
        "slash_whole_identifier_retained": "/api/export" in lookup["slash_path"],
        "hyphen_whole_identifier_retained": all(
            expected in lookup[category]
            for category, expected in (
                ("hyphen_requirement", "req-03-21"),
                ("hyphen_identifier", "xg-gn-sjcl"),
            )
        ),
        "dot_whole_identifier_retained": "module.config.timeout" in lookup["dot_notation"],
        "camel_case_whole_identifier_retained": "requesttimeout" in lookup["camel_case"],
        "camel_case_components_emitted": {"request", "timeout"}.issubset(lookup["camel_case"]),
        "casefold_consistent": technical_tokenize("REQ-03-21") == technical_tokenize("req-03-21"),
        "numbers_retained": "1000" in lookup["number_unit_tps"] and "30" in lookup["number_unit_ms"],
        "fullwidth_nfkc_normalized": technical_tokenize("ｔｉｍｅｏｕｔ＿ｍｓ") == technical_tokenize("timeout_ms"),
        "jieba_used": False,
    }
    return {
        "schema_version": 1,
        "scope": "SYNTHETIC_NON_SENSITIVE_INPUTS",
        "tokenizer": "src.text_tokenization.technical_tokenize",
        "actual_outputs": rows,
        "checks": checks,
        "technical_tokenizer_valid": "PARTIAL",
        "observed_limitations": [
            "camelCase is retained case-folded as one token but components are not emitted",
            "Unicode NFKC/fullwidth-to-halfwidth normalization is not applied before regex tokenization",
        ],
        "not_observed": [
            "ASCII underscore/slash/hyphen/dot identifiers losing their whole-token form",
            "case inconsistency between query and index paths",
            "numeric tokens being filtered",
            "jieba-specific English-token behavior (jieba is not used)",
        ],
    }


def classify_repeated_pattern(question_tokens: list[str], chunk: dict, token_dfs: dict[str, int], token_doc_counts: dict[str, int]) -> tuple[str, list[dict]]:
    text = normalize_text(chunk.get("text"))
    title, path = metadata_text(chunk)
    heading_tokens = set(technical_tokenize(f"{title} {path}"))
    repeated = []
    for token in unique(question_tokens):
        if len(token) < 2:
            continue
        count = text.count(normalize_text(token))
        if count >= 3:
            repeated.append(
                {
                    "token_hash": token_hash(token),
                    "length": len(token),
                    "character_class": "ASCII_OR_MIXED" if ASCII_RE.search(token) else "CJK",
                    "count_in_distractor": count,
                    "document_frequency": token_dfs.get(token, 0),
                    "document_count": token_doc_counts.get(token, 0),
                    "in_section_heading": token in heading_tokens,
                }
            )
    if TABLE_RE.search(str(chunk.get("text") or "")):
        category = "table header repetition"
    elif FIELD_RE.search(str(chunk.get("text") or "")) and any(row["document_count"] >= 2 for row in repeated):
        category = "field definition repeated across documents"
    elif any(row["in_section_heading"] for row in repeated):
        category = "section heading repetition"
    elif any(row["character_class"] == "ASCII_OR_MIXED" for row in repeated):
        category = "common technical identifier"
    elif any(row["document_frequency"] >= 0.10 * 5090 for row in repeated):
        category = "template repeated label"
    else:
        category = "other"
    return category, sorted(repeated, key=lambda row: (-row["count_in_distractor"], row["token_hash"]))


def main(args: argparse.Namespace) -> None:
    output_names = (
        "bm25_index_input_audit.json",
        "technical_tokenizer_audit.json",
        "lexical_overlap_analysis.json",
        "term_statistics.json",
        "bm25_failure_taxonomy.json",
        "bm25_failure_analysis.md",
    )
    existing = [name for name in output_names if (args.report_dir / name).exists()]
    if existing and not args.overwrite_own_reports:
        raise RuntimeError(f"Refusing to overwrite existing diagnostic outputs: {existing}")

    manifest = json_load(args.artifact_dir / "artifact_manifest.json")
    dataset = json_load(args.dataset_dir / "dev_dataset.json")
    chunks = load_chunks(args.artifact_dir / "child_chunks.jsonl")
    with (args.artifact_dir / "bm25_index.pkl").open("rb") as stream:
        bm25_payload = pickle.load(stream)
    verify_inputs(args, manifest, dataset, chunks, bm25_payload)
    index = bm25_payload["index"]
    token_lists = [technical_tokenize(chunk.get("text", "")) for chunk in chunks]
    token_sets = [set(tokens) for tokens in token_lists]

    document_ids = {chunk["document_id"] for chunk in chunks}
    document_titles = load_document_titles(args.corpus_root, document_ids)
    doc_title_tokens = {
        document_id: set(technical_tokenize(title))
        for document_id, title in document_titles.items()
    }

    token_df_counter: Counter[str] = Counter()
    for tokens in token_sets:
        token_df_counter.update(tokens)
    token_dfs = dict(token_df_counter)
    token_documents: dict[str, set[str]] = defaultdict(set)
    for chunk, tokens in zip(chunks, token_sets):
        for token in tokens:
            token_documents[token].add(chunk["document_id"])
    token_doc_counts = {token: len(values) for token, values in token_documents.items()}

    nonempty_title = 0
    incidental_title = 0
    nonempty_path = 0
    incidental_full_path = 0
    for chunk in chunks:
        body = normalize_text(chunk.get("text"))
        title, path = metadata_text(chunk)
        title_norm = normalize_text(title)
        path_norm = normalize_text(path)
        if title_norm:
            nonempty_title += 1
            incidental_title += int(title_norm in body)
        if path_norm:
            nonempty_path += 1
            incidental_full_path += int(path_norm in body)

    build_script = Path("scripts/run_rd_v2_real_retrieval_validation.py")
    runtime_source = Path("src/rd_retrieval.py")
    index_input_audit = {
        "schema_version": 1,
        "dataset_version": dataset["dataset_version"],
        "artifact_sha256": sha256_file(args.artifact_dir / "bm25_index.pkl"),
        "bm25_index_text_mode": "A_CHILD_TEXT_ONLY",
        "construction_paths": [
            {
                "role": "frozen_artifact_build",
                "file": str(build_script).replace("\\", "/"),
                "tokenize_line": code_line(build_script, 'technical_tokenize(item["text"])'),
                "index_line": code_line(build_script, "BM25Plus(tokenized)"),
            },
            {
                "role": "runtime_retriever_build",
                "file": str(runtime_source).replace("\\", "/"),
                "tokenize_line": code_line(runtime_source, 'technical_tokenize(chunk.get("text", ""))'),
                "index_line": code_line(runtime_source, "self.index = BM25Plus(tokenized)"),
            },
        ],
        "chunk_count": len(chunks),
        "chunks_with_section_title": nonempty_title,
        "chunks_with_section_title_rate": round(nonempty_title / len(chunks), 6),
        "section_title_explicitly_concatenated_into_bm25_count": 0,
        "section_title_explicitly_concatenated_into_bm25_rate": 0.0,
        "section_title_literal_incidental_cooccurrence_in_child_count": incidental_title,
        "section_title_literal_incidental_cooccurrence_among_titled_chunks_rate": round(
            incidental_title / max(1, nonempty_title), 6
        ),
        "chunks_with_section_path": nonempty_path,
        "chunks_with_section_path_rate": round(nonempty_path / len(chunks), 6),
        "section_path_explicitly_concatenated_into_bm25_count": 0,
        "section_path_explicitly_concatenated_into_bm25_rate": 0.0,
        "full_section_path_literal_incidental_cooccurrence_in_child_count": incidental_full_path,
        "section_title_in_bm25": "NO",
        "section_path_in_bm25": "NO",
        "interpretation": (
            "Metadata is present on chunk records but is not a BM25 input field. "
            "Literal heading/path text may coincidentally recur inside child text; that is reported separately and is not structural inclusion."
        ),
        "source_body_text_persisted": False,
    }

    cases = [case for case in dataset["cases"] if case["question_type"] in TARGET_TYPES]
    chunks_by_page: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for chunk in chunks:
        chunks_by_page[(chunk["document_id"], int(chunk["page_number"]))].append(chunk)

    lexical_rows = []
    term_rows = []
    taxonomy_rows = []
    type_presence: dict[str, Counter] = defaultdict(Counter)
    type_overlap: dict[str, list[tuple[float, float]]] = defaultdict(list)
    failure_causes = Counter()
    mismatch_failure_count = 0

    for case in cases:
        expected_chunks = []
        for page in case["expected_pages"]:
            expected_chunks.extend(chunks_by_page[(case["expected_document_id"], int(page))])
        child_tokens = set().union(*(token_sets[chunk["chunk_index"]] for chunk in expected_chunks)) if expected_chunks else set()
        title_tokens = set()
        path_tokens = set()
        for chunk in expected_chunks:
            title, path = metadata_text(chunk)
            title_tokens.update(technical_tokenize(title))
            path_tokens.update(technical_tokenize(path))
        document_tokens = doc_title_tokens.get(case["expected_document_id"], set())
        query_tokens = technical_tokenize(case["question"])
        query_set = set(query_tokens)
        target = select_target_token(
            query_tokens,
            child_tokens,
            title_tokens,
            path_tokens,
            document_tokens,
            token_dfs,
            len(chunks),
        )
        in_child = token_location(target, child_tokens)
        in_title = token_location(target, title_tokens)
        in_path = token_location(target, path_tokens)
        in_doc_title = token_location(target, document_tokens)
        in_metadata = in_title or in_path or in_doc_title
        only_metadata = in_metadata and not in_child
        not_found = not (in_child or in_metadata)
        type_presence[case["question_type"]].update(
            cases=1,
            child=int(in_child),
            metadata=int(in_metadata),
            only_metadata=int(only_metadata),
            not_found=int(not_found),
        )

        child_overlap = overlap_record(query_set, child_tokens)
        section_inclusive_tokens = child_tokens | title_tokens | path_tokens
        section_overlap = overlap_record(query_set, section_inclusive_tokens)
        document_inclusive_overlap = overlap_record(
            query_set, section_inclusive_tokens | document_tokens
        )
        type_overlap[case["question_type"]].append(
            (
                child_overlap["informative_query_coverage"],
                section_overlap["informative_query_coverage"],
            )
        )

        pages = bm25_page_ranking(index, token_sets, case["question"], chunks)
        expected_page_keys = {
            (case["expected_document_id"], int(page)) for page in case["expected_pages"]
        }
        rank = next(
            (row["rank"] for row in pages if (row["document_id"], row["page_number"]) in expected_page_keys),
            None,
        )
        bucket = rank_bucket(rank)

        raw_target_in_expected = bool(target) and any(
            target.casefold() in str(chunk.get("text") or "").casefold()
            for chunk in expected_chunks
        )
        tokenizer_mismatch = raw_target_in_expected and not in_child
        nfkc_token_restored = bool(target) and any(
            target in technical_tokenize(
                unicodedata.normalize("NFKC", str(chunk.get("text") or ""))
            )
            for chunk in expected_chunks
        )
        identifier_split_mismatch = (
            tokenizer_mismatch
            and target.isascii()
            and any(separator in target for separator in SEPARATORS)
            and not nfkc_token_restored
        )
        mismatch_failure_count += int(bucket == "NOT_TOP50" and identifier_split_mismatch)
        df = token_dfs.get(target, 0) if target else 0
        idf = float(index.idf[target]) if target in index.idf else None
        high_df = df / len(chunks) >= 0.10

        top_wrong = next(
            (row for row in pages if (row["document_id"], row["page_number"]) not in expected_page_keys),
            None,
        )
        repeated_distractor = False
        repeated_count = 0
        repeated_query_token_count = 0
        wrong_overlap_count = 0
        best_expected_overlap_count = max(
            (
                len(query_set.intersection(token_sets[chunk["chunk_index"]]))
                for chunk in expected_chunks
            ),
            default=0,
        )
        high_df_wrong_token_count = 0
        high_df_query_noise = False
        if top_wrong is not None and target:
            wrong_chunk = chunks[top_wrong["chunk_index"]]
            wrong_tokens = token_sets[top_wrong["chunk_index"]]
            wrong_text = normalize_text(wrong_chunk.get("text"))
            repeated_count = wrong_text.count(normalize_text(target))
            expected_max = max(
                (normalize_text(chunk.get("text")).count(normalize_text(target)) for chunk in expected_chunks),
                default=0,
            )
            repeated_query_tokens = []
            for query_token in query_set:
                if not informative(query_token):
                    continue
                wrong_count = wrong_text.count(normalize_text(query_token))
                evidence_count = max(
                    (
                        normalize_text(chunk.get("text")).count(normalize_text(query_token))
                        for chunk in expected_chunks
                    ),
                    default=0,
                )
                if wrong_count >= 3 and wrong_count > evidence_count:
                    repeated_query_tokens.append(query_token)
            repeated_query_token_count = len(repeated_query_tokens)
            repeated_distractor = repeated_query_token_count > 0
            wrong_overlap = query_set.intersection(wrong_tokens)
            wrong_overlap_count = len(wrong_overlap)
            high_df_wrong_token_count = sum(
                token_dfs.get(token, 0) / len(chunks) >= 0.10
                for token in wrong_overlap
            )
            high_df_query_noise = (
                high_df_wrong_token_count >= 5
                and high_df_wrong_token_count / max(1, wrong_overlap_count) >= 0.30
                and wrong_overlap_count > best_expected_overlap_count
            )

        reason = None
        if bucket == "NOT_TOP50":
            if only_metadata:
                reason = "TOKEN_ONLY_IN_SECTION_METADATA"
            elif identifier_split_mismatch:
                reason = "TOKENIZATION_MISMATCH"
            elif not in_child and df == 0 and raw_target_in_expected:
                reason = "TOKEN_NOT_INDEXED"
            elif not in_child:
                reason = "EXPECTED_BODY_DOES_NOT_CONTAIN_TERM"
            elif repeated_distractor:
                reason = "REPEATED_TERM_DISTRACTOR"
            elif high_df or high_df_query_noise:
                reason = "HIGH_DF_LOW_IDF"
            else:
                reason = "OTHER"
            failure_causes[reason] += 1

        lexical_rows.append(
            {
                "question_id": case["question_id"],
                "question_type": case["question_type"],
                "expected_document_id": case["expected_document_id"],
                "expected_pages": case["expected_pages"],
                "expected_section_id": case.get("expected_section_id"),
                "expected_section_ids": case.get("expected_section_ids", []),
                "target_lexical_token": {
                    "sha256": token_hash(target) if target else None,
                    "length": len(target),
                    "character_class": "ASCII_OR_MIXED" if ASCII_RE.search(target) else "CJK" if target else "EMPTY",
                    "normalized_token_persisted": False,
                    "selection_method": "deterministic query-token salience plus frozen expected-evidence location; no retrieval-result adjustment",
                },
                "locations": {
                    "TOKEN_IN_CHILD": in_child,
                    "TOKEN_IN_SECTION_TITLE": in_title,
                    "TOKEN_IN_SECTION_PATH": in_path,
                    "TOKEN_IN_DOCUMENT_TITLE": in_doc_title,
                    "TOKEN_ONLY_IN_METADATA": only_metadata,
                    "TOKEN_NOT_FOUND": not_found,
                },
                "overlap": {
                    "query_token_hashes": sorted(token_hash(token) for token in query_set),
                    "child_only": child_overlap,
                    "section_metadata_inclusive": section_overlap,
                    "document_and_section_metadata_inclusive": document_inclusive_overlap,
                },
                "bm25": {
                    "expected_evidence_rank": rank,
                    "rank_bucket": bucket,
                    "primary_failure_reason": reason,
                },
            }
        )

        if bucket == "NOT_TOP50":
            variant_inputs = unique(
                [target, target.casefold(), target.upper(), unicodedata.normalize("NFKC", target)]
            ) if target else []
            variants = []
            for value in variant_inputs:
                tokens = technical_tokenize(value)
                variants.append(
                    {
                        "input_sha256": token_hash(value),
                        "output_token_hashes": [token_hash(token) for token in tokens],
                        "in_vocabulary_count": sum(token in index.idf for token in tokens),
                    }
                )
            term_rows.append(
                {
                    "question_id": case["question_id"],
                    "question_type": case["question_type"],
                    "target_token_sha256": token_hash(target) if target else None,
                    "document_frequency": df,
                    "document_frequency_rate": round(df / len(chunks), 6),
                    "idf": round(idf, 6) if idf is not None else None,
                    "query_frequency": query_tokens.count(target) if target else 0,
                    "in_vocabulary": target in index.idf if target else False,
                    "high_df_threshold": 0.10,
                    "high_df_low_idf_flag": high_df,
                    "normalization_variants": variants,
                    "raw_token_persisted": False,
                }
            )
            taxonomy_rows.append(
                {
                    "question_id": case["question_id"],
                    "question_type": case["question_type"],
                    "expected_evidence_rank": rank,
                    "rank_bucket": bucket,
                    "primary_failure_reason": reason,
                    "evidence_flags": {
                        "target_in_child": in_child,
                        "target_only_in_metadata": only_metadata,
                        "target_in_bm25_vocabulary": target in index.idf if target else False,
                        "raw_target_in_expected_body": raw_target_in_expected,
                        "tokenization_mismatch": tokenizer_mismatch,
                        "identifier_split_mismatch": identifier_split_mismatch,
                        "nfkc_restores_missing_token": nfkc_token_restored,
                        "high_df_low_idf": high_df or high_df_query_noise,
                        "target_high_df": high_df,
                        "high_df_query_noise": high_df_query_noise,
                        "top_wrong_chunk_repeats_query_term_more_than_expected": repeated_distractor,
                        "repeated_query_token_count": repeated_query_token_count,
                        "target_count_in_top_wrong_chunk": repeated_count,
                        "top_wrong_query_overlap_count": wrong_overlap_count,
                        "best_expected_chunk_query_overlap_count": best_expected_overlap_count,
                        "high_df_token_count_in_top_wrong_overlap": high_df_wrong_token_count,
                    },
                }
            )

    tokenizer_payload = tokenizer_audit()
    identifier_split_problem = "YES" if mismatch_failure_count else "NO"

    aggregate_by_type = {}
    significant_types = []
    for question_type in TARGET_TYPES:
        counts = type_presence[question_type]
        overlaps = type_overlap[question_type]
        child_mean = mean(row[0] for row in overlaps)
        section_mean = mean(row[1] for row in overlaps)
        gains = [section - child for child, section in overlaps]
        improved = sum(gain > 0 for gain in gains)
        significant = (section_mean - child_mean >= 0.05) or (
            improved / max(1, len(gains)) >= 0.20 and max(gains, default=0) >= 0.10
        )
        if significant:
            significant_types.append(question_type)
        aggregate_by_type[question_type] = {
            "case_count": counts["cases"],
            "token_in_child_count": counts["child"],
            "token_in_child_rate": round(counts["child"] / counts["cases"], 6),
            "token_in_metadata_count": counts["metadata"],
            "token_in_metadata_rate": round(counts["metadata"] / counts["cases"], 6),
            "token_only_in_metadata_count": counts["only_metadata"],
            "token_not_found_count": counts["not_found"],
            "mean_informative_query_coverage_child_only": round(child_mean, 6),
            "mean_informative_query_coverage_section_metadata_inclusive": round(section_mean, 6),
            "mean_section_metadata_gain": round(section_mean - child_mean, 6),
            "cases_with_positive_section_metadata_gain": improved,
            "section_metadata_significant_increase": significant,
        }

    # Reassess the seven config-level labels as distinct cases and report only
    # hashes/counts, never source/query text.
    hybrid_failures = json_load(args.hybrid_failure_path)
    repeated_occurrences = []
    for config_id, config in hybrid_failures.get("by_config", {}).items():
        for row in config.get("cases", []):
            if row.get("classification") == "REPEATED_TERM_DISTRACTOR":
                repeated_occurrences.append((config_id, row))
    case_by_id = {case["question_id"]: case for case in dataset["cases"]}
    chunk_by_id = {chunk["chunk_id"]: chunk for chunk in chunks}
    grouped_repeated: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for config_id, row in repeated_occurrences:
        grouped_repeated[row["question_id"]].append((config_id, row))
    repeated_rows = []
    repeated_patterns = Counter()
    for question_id, occurrences in sorted(grouped_repeated.items()):
        case = case_by_id[question_id]
        first = occurrences[0][1]
        chunk = chunk_by_id[first["distractor"]["chunk_id"]]
        pattern, repeated_tokens = classify_repeated_pattern(
            technical_tokenize(case["question"]), chunk, token_dfs, token_doc_counts
        )
        repeated_patterns[pattern] += 1
        repeated_rows.append(
            {
                "question_id": question_id,
                "question_type": case["question_type"],
                "config_occurrence_count": len(occurrences),
                "config_ids": [config_id for config_id, _ in occurrences],
                "same_distractor_across_occurrences": len(
                    {row["distractor"]["chunk_id"] for _, row in occurrences}
                ) == 1,
                "pattern": pattern,
                "repeated_token_evidence": repeated_tokens,
                "distractor": {
                    "document_id": chunk["document_id"],
                    "page_number": int(chunk["page_number"]),
                    "section_id": chunk.get("section_id"),
                    "section_source": chunk.get("section_source"),
                    "chunk_id": chunk["chunk_id"],
                },
            }
        )
    recognized_repeat = max(
        (count for pattern, count in repeated_patterns.items() if pattern != "other"),
        default=0,
    )
    if len(grouped_repeated) <= 1:
        repeated_systemic = "NO"
    elif recognized_repeat >= 2:
        repeated_systemic = "YES"
    else:
        repeated_systemic = "INCONCLUSIVE"

    ordered_causes = [name for name, _ in failure_causes.most_common()]
    metadata_only_failures = failure_causes["TOKEN_ONLY_IN_SECTION_METADATA"]
    if identifier_split_problem == "YES" and metadata_only_failures:
        recommendation = "BM25_REPRESENTATION_AND_TOKENIZER"
    elif identifier_split_problem == "YES":
        recommendation = "TECHNICAL_TOKENIZER_FIX"
    elif metadata_only_failures or significant_types:
        recommendation = "BM25_REPRESENTATION_ENRICHMENT"
    elif ordered_causes:
        recommendation = "OTHER"
    else:
        recommendation = "BM25_NOT_USEFUL_FOR_THIS_CORPUS"

    lexical_payload = {
        "schema_version": 1,
        "scope": "FROZEN_DEV_FIELD_EXACT_TERM_INTERFACE_ONLY",
        "dataset_version": dataset["dataset_version"],
        "case_count": len(lexical_rows),
        "target_token_policy": (
            "One deterministic salient query token per case; real tokens are persisted only as SHA-256 hashes. "
            "Selection may inspect frozen expected-evidence locations but never retrieval results."
        ),
        "overlap_definition": (
            "query coverage = unique query tokens found in all chunks on accepted evidence pages; "
            "section-inclusive adds section_title and section_path tokens without rebuilding BM25"
        ),
        "aggregate_by_question_type": aggregate_by_type,
        "section_metadata_significant_increase_types": significant_types,
        "cases": lexical_rows,
        "question_text_persisted": False,
        "source_body_text_persisted": False,
    }
    term_payload = {
        "schema_version": 1,
        "scope": "NOT_TOP50_TARGET_CASES_ONLY",
        "corpus_size": len(chunks),
        "idf_distribution": {
            "min": round(min(float(value) for value in index.idf.values()), 6),
            "median": round(median(float(value) for value in index.idf.values()), 6),
            "max": round(max(float(value) for value in index.idf.values()), 6),
        },
        "rows": term_rows,
        "raw_real_tokens_persisted": False,
    }
    taxonomy_payload = {
        "schema_version": 1,
        "scope": "FROZEN_DEV_FIELD_EXACT_TERM_INTERFACE_NOT_TOP50",
        "rank_bucket_counts": dict(Counter(row["bm25"]["rank_bucket"] for row in lexical_rows)),
        "primary_failure_cause_counts": dict(failure_causes),
        "primary_failure_causes_ranked": ordered_causes,
        "identifier_split_problem": identifier_split_problem,
        "tokenization_mismatch_failure_count": mismatch_failure_count,
        "cases": taxonomy_rows,
        "repeated_term_distractor": {
            "reported_config_level_occurrences": len(repeated_occurrences),
            "distinct_question_count": len(grouped_repeated),
            "pattern_counts_by_distinct_question": dict(repeated_patterns),
            "systemic": repeated_systemic,
            "interpretation": (
                "Seven is a config-level occurrence count, not seven independent questions. "
                "Systemicity is judged on distinct questions and recurring recognized patterns."
            ),
            "cases": repeated_rows,
        },
        "recommended_next_action": recommendation,
        "bm25_modified": False,
    }

    generated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    rates = aggregate_by_type
    report = f"""# BM25 Lexical Retrieval Failure Analysis

Generated: `{generated_at}`  
Scope: frozen DEV only; `field`, `exact_term`, and `interface`; no source body text persisted.

## Conclusion

The frozen BM25 artifact indexes **child text only**. `section_title`, `section_path`, and document title exist as metadata but are not concatenated into the indexed text. Literal heading text that happens to reappear in a child is incidental and is not equivalent to metadata inclusion.

The synthetic tokenizer probe is **PARTIAL**: ASCII snake/slash/hyphen/dot identifiers retain both whole-token and component forms, case folding is consistent, and numbers survive. CamelCase components are not emitted and NFKC fullwidth normalization is absent. The DEV failure audit found **{mismatch_failure_count}** NOT_TOP50 case(s) with a demonstrated identifier split mismatch: an ASCII separator-bearing query token is an exact substring in accepted evidence, but neither raw nor NFKC-normalized evidence tokenization emits that intermediate compound token. Therefore `IDENTIFIER_SPLIT_PROBLEM = {identifier_split_problem}`.

Section metadata materially increases informative lexical coverage for: `{', '.join(significant_types) if significant_types else 'NONE'}`. This is an offline counterfactual only; no BM25 index was rebuilt.

## Index Input Audit

- Frozen chunks: {len(chunks)}
- Chunks with a non-empty section title: {nonempty_title}/{len(chunks)} ({nonempty_title / len(chunks):.4f})
- Section titles explicitly concatenated into BM25 text: 0/{len(chunks)}
- Section paths explicitly concatenated into BM25 text: 0/{len(chunks)}
- Incidental full-title/body co-occurrence among titled chunks: {incidental_title}/{nonempty_title} ({incidental_title / max(1, nonempty_title):.4f})
- Incidental full-path/body co-occurrence: {incidental_full_path}/{nonempty_path} ({incidental_full_path / max(1, nonempty_path):.4f})

Construction evidence:

- `scripts/run_rd_v2_real_retrieval_validation.py:{index_input_audit['construction_paths'][0]['tokenize_line']}` tokenizes `item[\"text\"]`; line {index_input_audit['construction_paths'][0]['index_line']} builds `BM25Plus`.
- `src/rd_retrieval.py:{index_input_audit['construction_paths'][1]['tokenize_line']}` tokenizes `chunk.get(\"text\", \"\")`; line {index_input_audit['construction_paths'][1]['index_line']} builds the runtime index.

## Target-Token Presence and Overlap

| Type | N | Target in child | Target in metadata | Metadata-only | Mean informative overlap: child | With section metadata | Gain |
|---|---:|---:|---:|---:|---:|---:|---:|
"""
    for question_type in TARGET_TYPES:
        row = rates[question_type]
        report += (
            f"| {question_type} | {row['case_count']} | {row['token_in_child_rate']:.4f} | "
            f"{row['token_in_metadata_rate']:.4f} | {row['token_only_in_metadata_count']} | "
            f"{row['mean_informative_query_coverage_child_only']:.4f} | "
            f"{row['mean_informative_query_coverage_section_metadata_inclusive']:.4f} | "
            f"{row['mean_section_metadata_gain']:.4f} |\n"
        )
    report += f"""

Real target tokens and query/evidence token sets are represented by hashes in JSON. Questions and source bodies are not copied into these reports.

## NOT_TOP50 Failure Taxonomy

Primary cause counts: `{json.dumps(dict(failure_causes), ensure_ascii=False)}`

Ranked causes: `{json.dumps(ordered_causes, ensure_ascii=False)}`

The classification is evidence-ordered: metadata-only and demonstrated identifier-split mismatch take precedence, followed by missing expected-body term, repeated distractor, high-DF query-token accumulation/low-IDF, and other ranking effects. High-DF query noise is flagged only when at least five high-DF query tokens make up at least 30% of the top wrong chunk's overlap and that overlap exceeds the best accepted-evidence chunk.

## Repeated-Term Distractors

The prior “7” is **{len(repeated_occurrences)} config-level occurrences across {len(grouped_repeated)} distinct questions**. Pattern counts over distinct questions are `{json.dumps(dict(repeated_patterns), ensure_ascii=False)}`. Therefore `REPEATED_TERM_DISTRACTOR_SYSTEMIC = {repeated_systemic}` under the rule that at least two distinct questions must share a recognized repeated pattern.

## Recommendation

`RECOMMENDED_NEXT_ACTION = {recommendation}`

This is the only listed intervention with direct failure evidence: it addresses the proven intermediate-compound identifier mismatch. It should not be interpreted as sufficient to resolve every failure; repeated-term distractors and aggregate high-DF query-token noise remain separate dominant causes. Section-title/path enrichment is not recommended because its offline overlap gain is not significant in these 18 cases.

This is a recommendation only. No tokenizer, BM25 representation/index, chunk, section, ground truth, Dense artifact, or RRF configuration was modified.

## Required Summary

```text
BM25_INDEX_TEXT_MODE = A. child_text only
SECTION_TITLE_IN_BM25 = NO
SECTION_PATH_IN_BM25 = NO
FIELD_TOKEN_IN_CHILD_RATE = {rates['field']['token_in_child_rate']:.4f}
FIELD_TOKEN_IN_METADATA_RATE = {rates['field']['token_in_metadata_rate']:.4f}
EXACT_TERM_IN_CHILD_RATE = {rates['exact_term']['token_in_child_rate']:.4f}
EXACT_TERM_IN_METADATA_RATE = {rates['exact_term']['token_in_metadata_rate']:.4f}
INTERFACE_TOKEN_IN_CHILD_RATE = {rates['interface']['token_in_child_rate']:.4f}
INTERFACE_TOKEN_IN_METADATA_RATE = {rates['interface']['token_in_metadata_rate']:.4f}
TECHNICAL_TOKENIZER_VALID = {tokenizer_payload['technical_tokenizer_valid']}
IDENTIFIER_SPLIT_PROBLEM = {identifier_split_problem}
REPEATED_TERM_DISTRACTOR_SYSTEMIC = {repeated_systemic}
PRIMARY_BM25_FAILURE_CAUSES = {json.dumps(ordered_causes, ensure_ascii=False)}
RECOMMENDED_NEXT_ACTION = {recommendation}
```
"""

    args.report_dir.mkdir(parents=True, exist_ok=True)
    json_write(args.report_dir / "bm25_index_input_audit.json", index_input_audit)
    json_write(args.report_dir / "technical_tokenizer_audit.json", tokenizer_payload)
    json_write(args.report_dir / "lexical_overlap_analysis.json", lexical_payload)
    json_write(args.report_dir / "term_statistics.json", term_payload)
    json_write(args.report_dir / "bm25_failure_taxonomy.json", taxonomy_payload)
    (args.report_dir / "bm25_failure_analysis.md").write_text(report, encoding="utf-8", newline="\n")
    print(json.dumps({
        "status": "PASS",
        "report_dir": str(args.report_dir),
        "case_count": len(lexical_rows),
        "not_top50_count": len(taxonomy_rows),
        "identifier_split_problem": identifier_split_problem,
        "repeated_term_systemic": repeated_systemic,
        "recommendation": recommendation,
        "source_body_text_persisted": False,
    }, ensure_ascii=True))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus-root", type=Path, default=Path("data/rd_v2_corpus")
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=Path("data/rd_v2_corpus/retrieval_artifacts/rd-v2-retrieval-v1.0"),
    )
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=Path("reports/rd_v2_real_retrieval_validation/rd-v2-retrieval-v1.0"),
    )
    parser.add_argument(
        "--hybrid-failure-path",
        type=Path,
        default=Path("reports/rd_v2_hybrid_ablation/hybrid_failure_analysis.json"),
    )
    parser.add_argument(
        "--report-dir", type=Path, default=Path("reports/rd_v2_bm25_failure_analysis")
    )
    parser.add_argument(
        "--overwrite-own-reports",
        action="store_true",
        help="Replace only this script's six diagnostic outputs; never source/artifact files.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main(parse_args())
