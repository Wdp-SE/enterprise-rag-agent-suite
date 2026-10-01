"""Rebuild the frozen quality-v1 question set from pinned cases and reviewed seeds."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "versioned-rag-service"
CORPUS = SERVICE / "public_corpus_autoware"
HERE = Path(__file__).resolve().parent
V3_CASES = ROOT / "evaluation" / "autoware_retrieval_v3" / "cases.jsonl"
BILINGUAL_CASES = ROOT / "evaluation" / "autoware_bilingual_v1" / "cases.jsonl"

PARAMETERS = "autoware-documentation/contributing/coding-guidelines/ros-nodes/parameters"
LOGGING = "autoware-documentation/contributing/coding-guidelines/ros-nodes/console-logging"
UNIT_TESTING = "autoware-documentation/contributing/testing-guidelines/unit-testing"
CI_CHECKS = "autoware-documentation/contributing/pull-request-guidelines/ci-checks"
LAUNCH = "autoware-documentation/how-to-guides/integrating-autoware/launch-autoware"
DEBUG = "autoware-documentation/how-to-guides/others/debug-autoware"
PLANNING_DESIGN = "autoware-documentation/design/autoware-architecture/planning"

# Whole source families stay on one side of the evaluation boundary.
HOLDOUT_FAMILIES = {
    "planning:goal", "planning:freespace", "planning:cross-module",
    f"document:{UNIT_TESTING}", f"document:{LAUNCH}",
    "document:planning/overview", "document:planning/trajectory_checker/design",
    "negative:outside_corpus_sensor_calibration_31",
    "negative:outside_corpus_sensor_holdout_42",
    "negative:corporate_jira_policy",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _component_versions(version: str) -> dict[str, str]:
    if version == "latest":
        return {"documentation": "docs-main", "universe": "0.52.0"}
    if version in {"docs-main", "1.9.0"}:
        return {"documentation": version}
    if version in {"0.51.0", "0.52.0"}:
        return {"universe": version}
    raise ValueError(f"unsupported version scope: {version}")


def _legacy_family(case: dict) -> str:
    name = case["case_id"]
    if name.startswith("start"):
        return "planning:start"
    if name.startswith("goal"):
        return "planning:goal"
    if name.startswith("freespace"):
        return "planning:freespace"
    if name.startswith("intersection"):
        return "planning:intersection"
    if "cross_module" in name or name == "cross_module_review_14":
        return "planning:cross-module"
    if any(word in name for word in ("validator", "trajectory", "checks")):
        return "planning:validation"
    if not case.get("required_sources"):
        return f"negative:{name}"
    return "planning:version-baseline"


def _relation_state(document_ids: list[str], rows_by_id: dict[str, list[dict]], sources_by_id: dict[str, dict]) -> str:
    states = [
        row.get("verification_status")
        for document_id in document_ids for row in rows_by_id.get(document_id, [])
    ]
    if "verified" in states:
        return "verified"
    if "candidate" in states:
        return "candidate"
    if any(sources_by_id[document_id].get("source_type") == "community_translation" for document_id in document_ids):
        return "unknown"
    return "none"


def _seed(**values) -> dict:
    return values


def _authored_seeds() -> list[dict]:
    return [
        _seed(case_id="docs_parameters_en_fact", query="Where do Autoware ROS nodes receive declared parameter values when they start?", query_language="en", source_keys=[("docs-main", "en", PARAMETERS)], version="docs-main", language="en", category="single_fact", required_answer_points=["Declared parameters receive values from a parameter file during node startup."]),
        _seed(case_id="docs_parameters_zh_fact", query="Autoware ROS 节点启动时，声明参数的值从哪里提供？", query_language="zh", source_keys=[("docs-main", "zh", PARAMETERS)], version="docs-main", language="zh", category="single_fact", required_answer_points=["节点启动期间通过参数文件提供已声明参数的值。"]),
        _seed(case_id="docs_parameters_zh_to_en", query="节点启动时参数文件需要满足什么要求？", query_language="zh", source_keys=[("docs-main", "en", PARAMETERS)], version="latest", language="all", category="zh_query_en_evidence", required_answer_points=["参数文件应包含预期参数及其对应值。"]),
        _seed(case_id="docs_parameters_en_to_zh", query="How are parameter values supplied to an Autoware node at startup?", query_language="en", source_keys=[("docs-main", "zh", PARAMETERS)], version="latest", language="all", category="en_query_zh_evidence", required_answer_points=["节点启动期间通过参数文件提供参数值。"]),
        _seed(case_id="docs_parameters_translation_state", query="Is the Chinese ROS-node parameter guide verified as equivalent to the English page?", query_language="en", source_keys=[("docs-main", "en", PARAMETERS), ("docs-main", "zh", PARAMETERS)], version="latest", language="all", category="translation_relation_state", required_answer_points=["The current registry marks this path-aligned pair as a candidate, not a verified translation."]),
        _seed(case_id="docs_logging_en_fact", query="Which user groups are console logs intended to support in Autoware?", query_language="en", source_keys=[("docs-main", "en", LOGGING)], version="docs-main", language="en", category="single_fact", required_answer_points=["Developers debug code, vehicle operators take risk-avoiding actions, and analysts inspect rosbag logs."]),
        _seed(case_id="docs_logging_zh_fact", query="Autoware 控制台日志主要服务于哪些使用场景？", query_language="zh", source_keys=[("docs-main", "zh", LOGGING)], version="docs-main", language="zh", category="single_fact", required_answer_points=["开发者调试、车辆操作员规避风险、分析人员检查 rosbag 日志。"]),
        _seed(case_id="docs_logging_zh_to_en", query="车辆操作员为什么需要清晰可见的日志？", query_language="zh", source_keys=[("docs-main", "en", LOGGING)], version="latest", language="all", category="zh_query_en_evidence", required_answer_points=["Operators use console logs to choose appropriate risk-avoiding actions."]),
        _seed(case_id="docs_logging_en_to_zh", query="How do operators and analysts use Autoware console logs?", query_language="en", source_keys=[("docs-main", "zh", LOGGING)], version="latest", language="all", category="en_query_zh_evidence", required_answer_points=["操作员依据日志采取风险规避措施，分析人员查看 rosbag 记录。"]),
        _seed(case_id="docs_logging_translation_state", query="Does the Chinese console-logging page have a verified English counterpart?", query_language="en", source_keys=[("docs-main", "en", LOGGING), ("docs-main", "zh", LOGGING)], version="latest", language="all", category="translation_relation_state", required_answer_points=["The registry records a path candidate and does not confirm semantic equivalence."]),
        _seed(case_id="docs_unit_testing_en_fact", query="Which test frameworks does Autoware's ament_cmake workflow support?", query_language="en", source_keys=[("docs-main", "en", UNIT_TESTING)], version="docs-main", language="en", category="single_fact", required_answer_points=["The page names pytest, gtest, and gmock."]),
        _seed(case_id="docs_unit_testing_zh_fact", query="Autoware 的 ament_cmake 单元测试流程支持哪些测试框架？", query_language="zh", source_keys=[("docs-main", "zh", UNIT_TESTING)], version="docs-main", language="zh", category="single_fact", required_answer_points=["资料列出 pytest、gtest 和 gmock。"]),
        _seed(case_id="docs_unit_testing_en_to_zh", query="What frameworks can be used to test CMake-based Autoware packages?", query_language="en", source_keys=[("docs-main", "zh", UNIT_TESTING)], version="latest", language="all", category="en_query_zh_evidence", required_answer_points=["可使用 pytest、gtest 和 gmock。"]),
        _seed(case_id="docs_unit_testing_zh_to_en", query="如何避免 ROS 主题发布订阅测试之间相互干扰？", query_language="zh", source_keys=[("docs-main", "en", UNIT_TESTING)], version="latest", language="all", category="zh_query_en_evidence", required_answer_points=["文档建议使用 ament_cmake_ros 命令隔离运行测试。"]),
        _seed(case_id="docs_launch_zh_fact", query="启动 Autoware 的主流程涉及哪些系统模块？", query_language="zh", source_keys=[("docs-main", "zh", LAUNCH)], version="latest", language="zh", category="single_fact", required_answer_points=["页面列出 vehicle、system、map、sensing、localization、perception、planning 和 control。"]),
        _seed(case_id="docs_debug_zh_fact", query="调试 Autoware ROS 2 系统时，命令行工具的入口是什么？", query_language="zh", source_keys=[("docs-main", "zh", DEBUG)], version="latest", language="zh", category="single_fact", required_answer_points=["ROS 2 命令行工具通过 ros2 入口检查节点、主题和服务。"]),
        _seed(case_id="docs_planning_design_zh_fact", query="Autoware 规划组件负责生成什么输出？", query_language="zh", source_keys=[("docs-main", "zh", PLANNING_DESIGN)], version="latest", language="zh", category="single_fact", required_answer_points=["规划组件生成目标轨迹，包括路径和速度。"]),
        _seed(case_id="docs_planning_design_en_to_zh", query="What is the purpose of the Autoware planning component?", query_language="en", source_keys=[("docs-main", "zh", PLANNING_DESIGN)], version="latest", language="all", category="en_query_zh_evidence", required_answer_points=["规划组件生成目标路径和速度，并考虑安全与交通规则。"]),
        _seed(case_id="docs_ci_en_fact", query="What does a Required CI check mean for an Autoware pull request?", query_language="en", source_keys=[("docs-main", "en", CI_CHECKS)], version="docs-main", language="en", category="single_fact", required_answer_points=["A required check must be resolved before merging."]),
        _seed(case_id="docs_ci_zh_fact", query="Autoware PR 的 CI 检查标记为 Required 时意味着什么？", query_language="zh", source_keys=[("docs-main", "zh", CI_CHECKS)], version="docs-main", language="zh", category="single_fact", required_answer_points=["Required 检查未解决时不能合并 PR。"]),
        _seed(case_id="docs_ci_translation_state", query="Is the Chinese CI-checks page a verified translation of the English guide?", query_language="en", source_keys=[("docs-main", "en", CI_CHECKS), ("docs-main", "zh", CI_CHECKS)], version="latest", language="all", category="translation_relation_state", required_answer_points=["The path is only a candidate until translation content is reviewed."]),
        _seed(case_id="universe_overview_051", query="In version 0.51.0, which source documents describe the Planning architecture overview?", query_language="en", source_keys=[("0.51.0", "en", "planning/overview")], version="0.51.0", language="en", category="explicit_version", required_answer_points=["The required source is the 0.51.0 Planning overview."]),
        _seed(case_id="universe_overview_052", query="In version 0.52.0, which document describes the Planning architecture overview?", query_language="en", source_keys=[("0.52.0", "en", "planning/overview")], version="0.52.0", language="en", category="explicit_version", required_answer_points=["The required source is the 0.52.0 Planning overview."]),
        _seed(case_id="trajectory_checker_051", query="For Autoware Universe 0.51.0, what does the trajectory checker validate?", query_language="en", source_keys=[("0.51.0", "en", "planning/trajectory_checker/design")], version="0.51.0", language="en", category="explicit_version", required_answer_points=["Evidence must come from the 0.51.0 trajectory checker document."]),
        _seed(case_id="trajectory_checker_052", query="For Autoware Universe 0.52.0, what does the trajectory checker validate?", query_language="en", source_keys=[("0.52.0", "en", "planning/trajectory_checker/design")], version="0.52.0", language="en", category="explicit_version", required_answer_points=["Evidence must come from the 0.52.0 trajectory checker document."]),
        _seed(case_id="docs_parameters_190", query="In Autoware Documentation 1.9.0, how should ROS node parameter defaults be handled?", query_language="en", source_keys=[("1.9.0", "en", PARAMETERS)], version="1.9.0", language="en", category="explicit_version", required_answer_points=["The answer must cite the fixed 1.9.0 documentation snapshot."]),
        _seed(case_id="parameter_launch_cross_source", query="When checking how node parameters affect startup, which parameter and launch guides should be reviewed?", query_language="en", source_keys=[("docs-main", "en", PARAMETERS), ("docs-main", "zh", LAUNCH)], version="latest", language="all", category="cross_source", required_answer_points=["The relevant sources are the ROS-node parameter guide and the Autoware launch guide."]),
        _seed(case_id="out_of_scope_jira_access", query="Can this public corpus show our company's Jira access-approval audit trail?", query_language="en", source_keys=[], version="latest", language="all", category="unanswerable_scope", answerable=False, family_id="negative:corporate_jira_policy", required_answer_points=[]),
        _seed(case_id="docs_launch_relation_unknown", query="Has the Chinese Autoware launch guide been verified against an English counterpart?", query_language="en", source_keys=[("docs-main", "zh", LAUNCH)], version="latest", language="all", category="translation_relation_state", required_answer_points=["The community translation has no verified counterpart in the registry."]),
    ]


def build_cases() -> tuple[list[dict], dict]:
    manifest_path = CORPUS / "corpus_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sources_by_id = {
        f"{row['version']}:{row['language']}:{row['document_key']}": row
        for row in manifest["sources"]
    }
    by_key = {(row["version"], row["language"], row["document_key"]): row for row in manifest["sources"]}
    registry = json.loads((CORPUS / "document_relations.json").read_text(encoding="utf-8"))
    relations_by_id: dict[str, list[dict]] = {}
    for row in registry.get("relations", []):
        for key in (row["source_document_id"], row["target_document_id"]):
            relations_by_id.setdefault(key, []).append(row)

    drafts = []
    for old in _read_jsonl(V3_CASES):
        source_ids = [f"{old['version']}:en:{key}" for key in old["required_sources"]]
        missing = [key for key in source_ids if key not in sources_by_id]
        if missing:
            raise ValueError(f"V3 source is absent from current corpus: {missing}")
        if not old["answerable"]:
            category = "unanswerable_scope"
        elif old.get("expected_images"):
            category = "image_evidence"
        elif len(source_ids) > 1:
            category = "cross_source"
        elif old["version"] in {"0.51.0", "0.52.0"} and "version" in old["case_id"]:
            category = "explicit_version"
        else:
            category = "single_fact"
        drafts.append({
            "case_id": f"v3_{old['case_id']}", "family_id": _legacy_family(old),
            "category": category, "query": old["query"], "query_language": "en",
            "version": old["version"], "language": "en", "required_sources": source_ids,
            "required_answer_points": [], "expected_image_ids": old.get("expected_images", []),
            "answerable": old["answerable"], "expected_relation_state": _relation_state(source_ids, relations_by_id, sources_by_id),
            "expected_component_versions": _component_versions(old["version"]),
            "case_origin": "pinned_v3_retrieval_case",
        })

    for old in _read_jsonl(BILINGUAL_CASES):
        language = old["language"]
        source_ids = []
        for key in old["expected_document_keys"]:
            source = by_key.get((old["version"] if old["version"] != "latest" else "docs-main" if language == "zh" else "0.52.0", language, key))
            if source is None:
                source = next((row for row in manifest["sources"] if row["document_key"] == key and row["language"] == language and row["version"] in _component_versions(old["version"]).values()), None)
            if source is None:
                raise ValueError(f"bilingual smoke source is absent: {old['id']} {key}")
            source_ids.append(f"{source['version']}:{source['language']}:{source['document_key']}")
        language_mode = "all" if any(sources_by_id[key]["language"] != language for key in source_ids) else language
        drafts.append({
            "case_id": f"smoke_{old['id']}", "family_id": f"document:{old['expected_document_keys'][0]}",
            "category": "single_fact", "query": old["query"], "query_language": language,
            "version": old["version"], "language": language_mode, "required_sources": source_ids,
            "required_answer_points": [], "expected_image_ids": [], "answerable": True,
            "expected_relation_state": _relation_state(source_ids, relations_by_id, sources_by_id),
            "expected_component_versions": _component_versions(old["version"]),
            "case_origin": "pinned_bilingual_smoke_case",
        })

    for seed in _authored_seeds():
        source_ids = []
        for version, language, key in seed["source_keys"]:
            source = by_key.get((version, language, key))
            if source is None:
                raise ValueError(f"authored seed source is absent: {seed['case_id']} {version}:{language}:{key}")
            source_ids.append(f"{version}:{language}:{key}")
        family = seed.get("family_id") or (
            f"document:{seed['source_keys'][0][2]}" if seed["source_keys"] else f"negative:{seed['case_id']}"
        )
        drafts.append({
            "case_id": seed["case_id"], "family_id": family,
            "category": seed["category"], "query": seed["query"],
            "query_language": seed["query_language"], "version": seed["version"],
            "language": seed["language"], "required_sources": source_ids,
            "required_answer_points": seed["required_answer_points"],
            "expected_image_ids": [], "answerable": seed.get("answerable", True),
            "expected_relation_state": _relation_state(source_ids, relations_by_id, sources_by_id),
            "expected_component_versions": _component_versions(seed["version"]),
            "case_origin": "manually_curated_from_pinned_source",
        })

    case_ids = [row["case_id"] for row in drafts]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("duplicate quality-set case ID")
    families = {row["family_id"] for row in drafts}
    unknown_holdouts = HOLDOUT_FAMILIES - families
    if unknown_holdouts:
        raise ValueError(f"split lock names absent families: {sorted(unknown_holdouts)}")
    cases = []
    for row in sorted(drafts, key=lambda case: case["case_id"]):
        cases.append({
            **row,
            "split": "holdout" if row["family_id"] in HOLDOUT_FAMILIES else "dev",
        })
    counts = Counter(row["split"] for row in cases)
    if not 80 <= len(cases) <= 120:
        raise ValueError(f"expected 80-120 curated cases; got {len(cases)}")
    case_bytes = ("".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for row in cases)).encode("utf-8")
    lock = {
        "schema_version": 1,
        "case_count": len(cases),
        "case_ids": case_ids if case_ids == sorted(case_ids) else sorted(case_ids),
        "split_counts": dict(sorted(counts.items())),
        "family_splits": {family: "holdout" if family in HOLDOUT_FAMILIES else "dev" for family in sorted(families)},
        "cases_sha256": hashlib.sha256(case_bytes).hexdigest(),
        "corpus_manifest_sha256": _sha(manifest_path),
        "relation_registry_sha256": _sha(CORPUS / "document_relations.json"),
        "split_note": "Families are locked wholly to DEV or HOLDOUT; V3 questions are preserved as retrieval regression cases, and bilingual cases extend them without changing their source labels.",
    }
    return cases, lock


def write_cases() -> None:
    cases, lock = build_cases()
    cases_path = HERE / "cases.jsonl"
    cases_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for row in cases),
        encoding="utf-8", newline="\n",
    )
    (HERE / "split_lock.json").write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({
        "case_count": len(cases), "split_counts": lock["split_counts"],
        "categories": dict(sorted(Counter(row["category"] for row in cases).items())),
        "family_count": len(lock["family_splits"]), "cases_sha256": lock["cases_sha256"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    write_cases()
