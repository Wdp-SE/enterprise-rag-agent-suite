"""Build a human-review candidate retrieval dataset from frozen local artifacts.

No retrieval system is executed.  The generated questions and proposed ground
truth remain CANDIDATE data until a human explicitly freezes them.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.sectioning import SECTIONING_VERSION


DATASET_VERSION = "rd-v2-real-retrieval-candidate/0.1"
CORPUS_VERSION_PREFIX = "rd-v2-real-corpus/1.0"
QUERY_TYPES = (
    "semantic",
    "exact_term",
    "interface",
    "field",
    "numeric",
    "dependency",
    "cross_section",
)
ALLOWED_SOURCES = {"WORD_OUTLINE", "PDF_HEURISTIC", "FALLBACK"}

ENDPOINT_RE = re.compile(
    r"\b(?:GET|POST|PUT|DELETE|PATCH)\s+/[A-Za-z0-9_./{}:-]{2,80}", re.I
)
FIELD_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9]{1,20}_[A-Za-z0-9_]{1,30}\b")
IDENTIFIER_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9_.-]{2,35}\b")
NUMERIC_RE = re.compile(
    r"(?P<label>[\u4e00-\u9fffA-Za-z_]{2,16})[^\n。；;]{0,18}?"
    r"\d+(?:\.\d+)?\s*(?:ms|s|秒|分钟|小时|天|%|MB|GB|KB|次|条|个|位|字符)",
    re.I,
)
DEPENDENCY_RE = re.compile(r"依赖|前置|先决|调用顺序|requires?|depends?|dependency", re.I)
INTERFACE_RE = re.compile(r"接口|API|请求|响应|request|response", re.I)
FIELD_CONTEXT_RE = re.compile(r"字段|参数|属性|取值|field|parameter", re.I)
GENERIC_TITLES = {"Document preamble", "Unresolved structure region"}
STOP_TERMS = {
    "the", "and", "for", "with", "this", "that", "from", "into", "body",
    "http", "https", "www", "com", "page", "table", "string", "true", "false",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_hash(value: str, length: int = 16) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def write_text_atomic(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    if temporary.exists() or path.exists():
        raise RuntimeError("Refusing to overwrite an existing candidate dataset artifact")
    temporary.write_text(value.rstrip() + "\n", encoding="utf-8")
    temporary.replace(path)


def write_json_atomic(path: Path, payload: object) -> None:
    write_text_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2))


def compact(value: str, limit: int = 72) -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip().strip("#").strip()
    value = value.replace("|", " ")
    return value[:limit].rstrip()


def section_cluster(section: dict, by_id: dict[str, dict]) -> str:
    current = section
    seen = set()
    while current.get("parent_section_id") and current["parent_section_id"] not in seen:
        seen.add(current["section_id"])
        parent = by_id.get(current["parent_section_id"])
        if parent is None:
            break
        current = parent
    return stable_hash(f"cluster|{current['document_id']}|{current['section_id']}", 20)


def chunk_texts(section_id: str, chunks_by_section: dict[str, list[dict]]) -> Iterable[tuple[int, str]]:
    for chunk in chunks_by_section.get(section_id, []):
        yield int(chunk.get("page_number", chunk.get("page", 0))), str(chunk.get("text", ""))


def first_match(
    section_id: str,
    chunks_by_section: dict[str, list[dict]],
    pattern: re.Pattern,
) -> tuple[int, re.Match] | None:
    for page, text in chunk_texts(section_id, chunks_by_section):
        match = pattern.search(text)
        if match:
            return page, match
    return None


def best_identifier(section_id: str, chunks_by_section: dict[str, list[dict]]) -> tuple[int, str] | None:
    for pattern in (FIELD_RE, IDENTIFIER_RE):
        for page, text in chunk_texts(section_id, chunks_by_section):
            for match in pattern.finditer(text):
                term = match.group(0).strip("._-")
                if term.casefold() not in STOP_TERMS and 3 <= len(term) <= 36:
                    return page, term
    return None


def make_case(
    *,
    question: str,
    question_type: str,
    document_id: str,
    pages: list[int],
    sections: list[dict],
    cluster_id: str,
) -> dict:
    page_values = sorted({int(page) for page in pages if int(page) > 0})
    sources = list(dict.fromkeys(item["heading_source"] for item in sections))
    if not page_values or not sections or any(source not in ALLOWED_SOURCES for source in sources):
        raise ValueError("Candidate ground truth is incomplete")
    question = compact(question, 180)
    identity = "|".join(
        [question_type, document_id, cluster_id, question]
        + [item["section_id"] for item in sections]
        + [str(page) for page in page_values]
    )
    return {
        "question_id": f"rdq-{stable_hash(identity, 20)}",
        "question": question,
        "question_type": question_type,
        "expected_document_id": document_id,
        "expected_pages": page_values,
        "expected_section_id": sections[0]["section_id"],
        "expected_section_ids": [item["section_id"] for item in sections],
        "expected_section_source": sources[0],
        "expected_section_sources": sources,
        "topic_cluster_id": cluster_id,
        "split": None,
        "needs_human_review": True,
        "review_status": "PENDING",
        "human_review": {
            "question_answerable": None,
            "expected_document_correct": None,
            "expected_pages_correct": None,
            "expected_sections_correct": None,
            "approve": None,
        },
    }


def candidates_for_document(document_id: str, repaired: dict) -> list[dict]:
    sections = repaired["content"].get("sections", [])
    by_id = {item["section_id"]: item for item in sections}
    chunks_by_section: dict[str, list[dict]] = defaultdict(list)
    for chunk in repaired["content"].get("chunks", []):
        if chunk.get("section_id"):
            chunks_by_section[chunk["section_id"]].append(chunk)
    for chunks in chunks_by_section.values():
        chunks.sort(key=lambda item: (int(item.get("page", 0)), int(item.get("id", 0))))

    candidates: list[dict] = []
    sections_by_cluster: dict[str, list[dict]] = defaultdict(list)
    for section in sections:
        cluster_id = section_cluster(section, by_id)
        sections_by_cluster[cluster_id].append(section)
        title = compact(section.get("title", ""), 64)
        identifier = best_identifier(section["section_id"], chunks_by_section)
        label = title if title and title not in GENERIC_TITLES else (identifier[1] if identifier else "该内容区段")
        base_page = int(section.get("start_page", 0))

        candidates.append(
            make_case(
                question=f"“{label}”部分主要说明了什么业务目标、处理规则或约束？",
                question_type="semantic",
                document_id=document_id,
                pages=[base_page],
                sections=[section],
                cluster_id=cluster_id,
            )
        )
        if identifier:
            page, term = identifier
            candidates.append(
                make_case(
                    question=f"文档中“{term}”这一术语或标识的具体含义和用途是什么？",
                    question_type="exact_term",
                    document_id=document_id,
                    pages=[page],
                    sections=[section],
                    cluster_id=cluster_id,
                )
            )
        endpoint = first_match(section["section_id"], chunks_by_section, ENDPOINT_RE)
        interface = first_match(section["section_id"], chunks_by_section, INTERFACE_RE)
        if endpoint or interface:
            page = (endpoint or interface)[0]
            subject = endpoint[1].group(0) if endpoint else label
            candidates.append(
                make_case(
                    question=f"“{compact(subject, 64)}”所描述接口的用途、输入输出或调用约束是什么？",
                    question_type="interface",
                    document_id=document_id,
                    pages=[page],
                    sections=[section],
                    cluster_id=cluster_id,
                )
            )
        field_context = first_match(section["section_id"], chunks_by_section, FIELD_CONTEXT_RE)
        if identifier and field_context:
            candidates.append(
                make_case(
                    question=f"字段或参数“{identifier[1]}”的含义、取值或使用要求是什么？",
                    question_type="field",
                    document_id=document_id,
                    pages=[identifier[0]],
                    sections=[section],
                    cluster_id=cluster_id,
                )
            )
        numeric = first_match(section["section_id"], chunks_by_section, NUMERIC_RE)
        if numeric:
            numeric_label = compact(numeric[1].group("label"), 24)
            candidates.append(
                make_case(
                    question=f"“{numeric_label}”相关的数值限制、阈值或时限是多少？",
                    question_type="numeric",
                    document_id=document_id,
                    pages=[numeric[0]],
                    sections=[section],
                    cluster_id=cluster_id,
                )
            )
        dependency = first_match(section["section_id"], chunks_by_section, DEPENDENCY_RE)
        if dependency:
            candidates.append(
                make_case(
                    question=f"“{label}”涉及哪些依赖、前置条件或调用顺序？",
                    question_type="dependency",
                    document_id=document_id,
                    pages=[dependency[0]],
                    sections=[section],
                    cluster_id=cluster_id,
                )
            )

    for cluster_id, cluster_sections in sections_by_cluster.items():
        ordered = sorted(cluster_sections, key=lambda item: (int(item["start_page"]), item["section_id"]))
        if len(ordered) < 2:
            continue
        first = ordered[0]
        second = next(
            (item for item in ordered[1:] if int(item["start_page"]) != int(first["start_page"])),
            ordered[1],
        )
        first_label = compact(first.get("title", ""), 48)
        second_label = compact(second.get("title", ""), 48)
        if first_label in GENERIC_TITLES or second_label in GENERIC_TITLES:
            continue
        candidates.append(
            make_case(
                question=f"“{first_label}”与“{second_label}”分别说明什么，它们在流程或设计上如何衔接？",
                question_type="cross_section",
                document_id=document_id,
                pages=[int(first["start_page"]), int(second["start_page"])],
                sections=[first, second],
                cluster_id=cluster_id,
            )
        )

    unique = {}
    for item in candidates:
        key = (item["question_type"], item["question"], item["topic_cluster_id"])
        unique.setdefault(key, item)
    return list(unique.values())


def allocate_cluster_splits(cases: list[dict], holdout_target: int) -> tuple[list[dict], list[dict]]:
    by_cluster: dict[str, list[dict]] = defaultdict(list)
    for item in cases:
        by_cluster[item["topic_cluster_id"]].append(item)
    ordered_clusters = sorted(
        by_cluster,
        key=lambda value: stable_hash(f"holdout|{value}", 64),
    )
    holdout_clusters = set()
    holdout_capacity = 0
    for cluster in ordered_clusters:
        if holdout_capacity >= max(holdout_target * 2, holdout_target + 4) and len(holdout_clusters) >= 2:
            break
        holdout_clusters.add(cluster)
        holdout_capacity += len(by_cluster[cluster])
    holdout = [item for item in cases if item["topic_cluster_id"] in holdout_clusters]
    dev = [item for item in cases if item["topic_cluster_id"] not in holdout_clusters]
    if len(holdout) < holdout_target or not dev:
        raise RuntimeError("Topic-cluster split cannot satisfy the requested allocation")
    return dev, holdout


def normalized_question(value: str) -> str:
    return " ".join(value.casefold().split())


def select_cases(
    pool: list[dict],
    quota: int,
    desired_types: list[str],
    reserved_questions: set[str],
) -> list[dict]:
    ordered = sorted(pool, key=lambda item: stable_hash(f"select|{item['question_id']}", 64))
    selected: list[dict] = []
    used_ids = set()
    for question_type in desired_types:
        candidate = next(
            (
                item
                for item in ordered
                if item["question_type"] == question_type
                and item["question_id"] not in used_ids
                and normalized_question(item["question"]) not in reserved_questions
            ),
            None,
        )
        if candidate:
            selected.append(candidate)
            used_ids.add(candidate["question_id"])
            reserved_questions.add(normalized_question(candidate["question"]))
        if len(selected) == quota:
            return selected
    for item in ordered:
        if (
            item["question_id"] in used_ids
            or normalized_question(item["question"]) in reserved_questions
        ):
            continue
        selected.append(item)
        used_ids.add(item["question_id"])
        reserved_questions.add(normalized_question(item["question"]))
        if len(selected) == quota:
            break
    if len(selected) != quota:
        raise RuntimeError("Candidate pool is too small for the requested split")
    return selected


def make_unanswerable_cases() -> list[dict]:
    questions = [
        ("negative-policy", "文档是否规定了代号 RDX-NOT-IN-CORPUS-001 的正式发布审批人？"),
        ("negative-credential", "三份文档中用于生产环境登录的真实账号和密码分别是什么？"),
        ("negative-vendor", "文档是否给出了未出现供应商 ZetaCloud 的合同金额和付款日期？"),
        ("negative-mobile", "资料是否定义了 RDX Mobile 4.0 的 iOS 最低系统版本？"),
        ("negative-sla", "文档是否承诺 2035 年生效的 99.9999% 外部客户 SLA？"),
        ("negative-endpoint", "不存在的接口 DELETE /api/rdx/v99/phantom 的返回字段是什么？"),
        ("negative-field", "未定义字段 phantom_release_token 的取值范围是什么？"),
        ("negative-database", "资料是否指定了数据库表 phantom_audit_2099 的分区键？"),
        ("negative-hardware", "文档是否要求部署在量子处理器 QPU-X999 上？"),
        ("negative-region", "资料是否说明虚构区域 mars-north-1 的容灾切换时间？"),
    ]
    return [
        {
            "question_id": question_id,
            "question": question,
            "question_type": "unanswerable",
            "answerability": "UNANSWERABLE",
            "expected_document_id": None,
            "expected_pages": [],
            "expected_section_id": None,
            "expected_section_ids": [],
            "split": "NEGATIVE",
            "excluded_from_answerable_metrics": True,
            "needs_human_review": True,
            "review_status": "PENDING",
        }
        for question_id, question in questions
    ]


def review_markdown(answerable: list[dict], negatives: list[dict], summary: dict) -> str:
    lines = [
        "# R&D V2 Candidate Ground Truth Review",
        "",
        "## Freeze gate",
        "",
        "DATASET_STATUS = CANDIDATE",
        "",
        "FORMAL_RETRIEVAL_EVALUATION_ALLOWED = NO",
        "",
        "Every case requires human confirmation. Do not set `dataset_status = FROZEN`, add `frozen_at`, or run formal retrieval until all approved cases have verified document, physical page, and section ground truth.",
        "",
        "## Review checklist",
        "",
        "For every answerable case verify:",
        "",
        "- [ ] The question is answerable from the frozen corpus.",
        "- [ ] The proposed document is correct.",
        "- [ ] Every expected physical page contains valid evidence.",
        "- [ ] Every expected section ID and source are correct.",
        "- [ ] No synonymous or near-duplicate fact crosses DEV and HOLDOUT clusters.",
        "- [ ] The query type is appropriate and not artificially lexical.",
        "",
        "For every negative case verify:",
        "",
        "- [ ] No positive evidence exists in any of the three documents.",
        "- [ ] The question is suitable for later Trusted QA / Answer Evaluation.",
        "",
        "## Candidate summary",
        "",
        f"- DEV answerable: {summary['dev_count']}",
        f"- HOLDOUT answerable: {summary['holdout_count']}",
        f"- Unanswerable: {summary['unanswerable_count']}",
        f"- DEV topic clusters: {summary['dev_topic_clusters']}",
        f"- HOLDOUT topic clusters: {summary['holdout_topic_clusters']}",
        "",
    ]
    for split in ("DEV", "HOLDOUT"):
        lines.extend(
            [
                f"## {split} candidates",
                "",
                "| approve | question_id | type | question | document_id | pages | section source | topic cluster |",
                "|---|---|---|---|---|---|---|---|",
            ]
        )
        for item in (case for case in answerable if case["split"] == split):
            question = item["question"].replace("|", " ")
            pages = ",".join(str(value) for value in item["expected_pages"])
            lines.append(
                f"| [ ] | {item['question_id']} | {item['question_type']} | {question} | "
                f"{item['expected_document_id']} | {pages} | {item['expected_section_source']} | "
                f"{item['topic_cluster_id']} |"
            )
        lines.append("")
    lines.extend(
        [
            "## Unanswerable candidates",
            "",
            "| approve | question_id | question |",
            "|---|---|---|",
        ]
    )
    for item in negatives:
        lines.append(f"| [ ] | {item['question_id']} | {item['question'].replace('|', ' ')} |")
    lines.extend(
        [
            "",
            "## Human freeze action",
            "",
            "After review, return the approved/rejected IDs and any corrected page or section ground truth. Only then create immutable `dev_dataset.json` and `holdout_dataset.json` with `dataset_status = FROZEN`, `frozen_at`, and a new dataset version.",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    corpus_root = args.corpus_root.resolve()
    manifest = load_json(args.manifest)
    all_cases_by_doc: dict[str, list[dict]] = {}
    snapshot_documents = []
    version_parts = [CORPUS_VERSION_PREFIX, SECTIONING_VERSION]
    metadata_by_type = {item["document_type"]: item for item in manifest["documents"]}

    for metadata in manifest["documents"]:
        document_id = metadata["document_id"]
        repaired_path = corpus_root / "normalized" / "repaired_chunked" / document_id / f"{document_id}.json"
        word_sidecar_path = corpus_root / "manifest" / "word_structure_sidecars" / f"{document_id}.json"
        resolved_sidecar_path = corpus_root / "manifest" / "resolved_structure_sidecars" / f"{document_id}.json"
        repaired = load_json(repaired_path)
        word_sidecar = load_json(word_sidecar_path)
        resolved_sidecar = load_json(resolved_sidecar_path)
        if sha256(corpus_root / metadata["staged_relative_path"]) != metadata["source_sha256"]:
            raise RuntimeError("Frozen source hash mismatch")
        if sha256(corpus_root / metadata["normalized_relative_path"]) != metadata["normalized_sha256"]:
            raise RuntimeError("Frozen canonical PDF hash mismatch")
        sections = repaired["content"].get("sections", [])
        chunks = repaired["content"].get("chunks", [])
        if len(sections) != len(resolved_sidecar["sections"]):
            raise RuntimeError("Resolved sidecar and repaired chunk artifact disagree")
        all_cases_by_doc[document_id] = candidates_for_document(document_id, repaired)
        sidecar_hash = sha256(resolved_sidecar_path)
        chunk_hash = sha256(repaired_path)
        version_parts.extend(
            [
                metadata["source_sha256"],
                metadata["normalized_sha256"],
                sidecar_hash,
                chunk_hash,
            ]
        )
        snapshot_documents.append(
            {
                "document_id": document_id,
                "document_type": metadata["document_type"],
                "source_hash": metadata["source_sha256"],
                "canonical_pdf_hash": metadata["normalized_sha256"],
                "word_structure_extractor_version": word_sidecar["extractor_version"],
                "structure_sidecar_hash": sidecar_hash,
                "chunker_version": SECTIONING_VERSION,
                "chunk_artifact_hash": chunk_hash,
                "section_count": len(sections),
                "chunk_count": len(chunks),
            }
        )

    doc_targets = {
        "requirements": {"DEV": 8, "HOLDOUT": 4},
        "detailed_design": {"DEV": 16, "HOLDOUT": 8},
        "test_or_acceptance": {"DEV": 16, "HOLDOUT": 8},
    }
    desired = {
        "requirements": [
            "semantic", "semantic", "semantic", "exact_term", "exact_term",
            "numeric", "dependency", "cross_section", "semantic", "semantic",
            "exact_term", "cross_section",
        ],
        "detailed_design": [
            "semantic", "semantic", "exact_term", "exact_term", "interface", "interface",
            "interface", "field", "field", "field", "numeric", "numeric", "dependency",
            "dependency", "cross_section", "cross_section", "semantic", "exact_term",
            "interface", "interface", "field", "numeric", "dependency", "cross_section",
        ],
        "test_or_acceptance": [
            "semantic", "semantic", "exact_term", "exact_term", "interface", "interface",
            "field", "field", "numeric", "numeric", "dependency", "dependency",
            "cross_section", "cross_section", "cross_section", "cross_section", "semantic",
            "exact_term", "interface", "field", "numeric", "dependency", "cross_section",
            "cross_section",
        ],
    }
    selected = []
    reserved_questions: set[str] = set()
    for document_type, targets in doc_targets.items():
        document_id = metadata_by_type[document_type]["document_id"]
        dev_pool, holdout_pool = allocate_cluster_splits(
            all_cases_by_doc[document_id], targets["HOLDOUT"]
        )
        type_plan = desired[document_type]
        dev_cases = select_cases(
            dev_pool,
            targets["DEV"],
            type_plan[: targets["DEV"]],
            reserved_questions,
        )
        holdout_cases = select_cases(
            holdout_pool,
            targets["HOLDOUT"],
            type_plan[targets["DEV"] :],
            reserved_questions,
        )
        for item in dev_cases:
            item["split"] = "DEV"
        for item in holdout_cases:
            item["split"] = "HOLDOUT"
        selected.extend(dev_cases + holdout_cases)

    selected.sort(key=lambda item: (item["split"], item["expected_document_id"], item["question_id"]))
    dev = [item for item in selected if item["split"] == "DEV"]
    holdout = [item for item in selected if item["split"] == "HOLDOUT"]
    negatives = make_unanswerable_cases()
    dev_clusters = {item["topic_cluster_id"] for item in dev}
    holdout_clusters = {item["topic_cluster_id"] for item in holdout}
    if dev_clusters & holdout_clusters:
        raise RuntimeError("Topic cluster leakage detected")
    if len(dev) != 40 or len(holdout) != 20 or len(negatives) != 10:
        raise RuntimeError("Candidate dataset count contract failed")
    if len({item["question_id"] for item in selected}) != len(selected):
        raise RuntimeError("Duplicate answerable question IDs detected")
    if len({normalized_question(item["question"]) for item in selected}) != len(selected):
        raise RuntimeError("Duplicate answerable question text detected")
    if any(
        item["answerability"] != "UNANSWERABLE"
        or item["excluded_from_answerable_metrics"] is not True
        for item in negatives
    ):
        raise RuntimeError("Unanswerable metric-exclusion contract failed")

    corpus_version = f"{CORPUS_VERSION_PREFIX}+{stable_hash('|'.join(version_parts), 20)}"
    snapshot = {
        "schema_version": 1,
        "corpus_version": corpus_version,
        "corpus_status": "FROZEN_FOR_CANDIDATE_REVIEW",
        "structure_status": "FROZEN",
        "citation_contract": ["document_id", "page_number"],
        "documents": snapshot_documents,
        "document_count": len(snapshot_documents),
        "online_models_called": False,
        "embedding_or_retrieval_run": False,
        "body_text_included": False,
    }
    summary = {
        "dev_count": len(dev),
        "holdout_count": len(holdout),
        "unanswerable_count": len(negatives),
        "dev_topic_clusters": len(dev_clusters),
        "holdout_topic_clusters": len(holdout_clusters),
        "dev_query_types": dict(sorted(Counter(item["question_type"] for item in dev).items())),
        "holdout_query_types": dict(sorted(Counter(item["question_type"] for item in holdout).items())),
        "dev_documents": dict(sorted(Counter(item["expected_document_id"] for item in dev).items())),
        "holdout_documents": dict(sorted(Counter(item["expected_document_id"] for item in holdout).items())),
        "dev_section_sources": dict(sorted(Counter(item["expected_section_source"] for item in dev).items())),
        "holdout_section_sources": dict(sorted(Counter(item["expected_section_source"] for item in holdout).items())),
    }
    candidate_dataset = {
        "schema_version": 1,
        "dataset_version": DATASET_VERSION,
        "dataset_status": "CANDIDATE",
        "frozen_at": None,
        "corpus_version": corpus_version,
        "split_method": "SECTION_TOPIC_CLUSTER",
        "ground_truth_policy": "HUMAN_REVIEW_REQUIRED_BEFORE_FREEZE",
        "summary": summary,
        "cases": selected,
        "formal_retrieval_evaluation_allowed": False,
        "needs_human_review": True,
    }
    unanswerable = {
        "schema_version": 1,
        "dataset_version": DATASET_VERSION + "/negative",
        "dataset_status": "CANDIDATE",
        "frozen_at": None,
        "count": len(negatives),
        "metric_policy": "EXCLUDED_FROM_HIT_RECALL_MRR",
        "intended_use": "TRUSTED_QA_AND_LATER_ANSWER_EVALUATION",
        "cases": negatives,
        "needs_human_review": True,
    }
    dataset_summary = "\n".join(
        [
            "# R&D V2 Candidate Dataset Summary",
            "",
            "DATASET_STATUS = CANDIDATE",
            "",
            "GROUND_TRUTH_FROZEN = NO",
            "",
            "FORMAL_RETRIEVAL_EVALUATION_ALLOWED = NO",
            "",
            f"DEV_ANSWERABLE_CANDIDATES = {len(dev)}",
            f"HOLDOUT_ANSWERABLE_CANDIDATES = {len(holdout)}",
            f"UNANSWERABLE_CANDIDATES = {len(negatives)}",
            "",
            "DEV and HOLDOUT are separated by deterministic Section/Topic Cluster. A cluster appears in exactly one split, so synonymous questions derived from the same section family cannot cross the formal split.",
            "",
            "All proposed documents, physical pages, section IDs, section sources, query types, and unanswerable labels require human review. No embedding, FAISS, BM25, dense retrieval, Hybrid ablation, reranking, or answer generation has run.",
            "",
            "The next action is human review only. Retrieval artifacts may be built after the approved cases are written as immutable FROZEN datasets with a new version and frozen_at timestamp.",
        ]
    )

    write_json_atomic(args.output_dir / "corpus_snapshot.json", snapshot)
    write_json_atomic(args.output_dir / "candidate_dataset.json", candidate_dataset)
    write_json_atomic(args.output_dir / "unanswerable_set.json", unanswerable)
    write_text_atomic(args.output_dir / "candidate_review.md", review_markdown(selected, negatives, summary))
    write_text_atomic(args.output_dir / "dataset_summary.md", dataset_summary)
    print(
        json.dumps(
            {
                "dataset_status": "CANDIDATE",
                "dev": len(dev),
                "holdout": len(holdout),
                "unanswerable": len(negatives),
                "dev_query_types": summary["dev_query_types"],
                "holdout_query_types": summary["holdout_query_types"],
                "formal_retrieval_evaluation_allowed": False,
                "body_text_logged": False,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
