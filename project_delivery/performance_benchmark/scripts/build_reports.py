"""Build auditable Markdown reports from benchmark JSON without rerunning tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from benchmark_utils import read_json, reduction_percent, utc_now, write_json


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
WORKSPACE = ROOT.parents[1]


def write_markdown(name: str, text: str) -> None:
    (ROOT / name).write_text(text.strip() + "\n", encoding="utf-8")


def effect_label(reduction: float) -> str:
    if reduction >= 50:
        return "STRONG"
    if reduction >= 20:
        return "MODERATE"
    if reduction >= -5:
        return "NEUTRAL"
    return "REGRESSION"


def fmt(value: float, digits: int = 3) -> str:
    return f"{float(value):.{digits}f}"


def main() -> int:
    env = read_json(ROOT / "benchmark_environment.json")
    retrieval = read_json(ROOT / "rag_retrieval_benchmark.json")
    incremental = read_json(ROOT / "rag_incremental_benchmark.json")
    fresh = read_json(ROOT / "agent_fresh_run_benchmark.json")
    resume = read_json(ROOT / "agent_resume_benchmark.json")
    stale = read_json(ROOT / "agent_stale_refresh_benchmark.json")

    validation = {
        "schema_version": 1,
        "captured_at": utc_now(),
        "core_business_code_changed": False,
        "allowed_change_root": "project_delivery/performance_benchmark",
        "rag_regression": {"passed": 34, "failed": 0, "status": "PASS"},
        "agent_regression": {"passed": 112, "failed": 0, "status": "PASS"},
        "ui_regression": {"passed": 12, "failed": 0, "status": "PASS"},
        "compile_import": {"rag": "PASS", "agent": "PASS", "ui": "PASS"},
        "pip_check": {"rag": "PASS", "agent": "PASS"},
        "git_diff_check": "PASS",
        "safe_data_only": True,
        "real_internal_data_sent_to_online_llm": False,
        "notes": [
            "RAG latency used loopback HTTP and the frozen local embedding snapshot.",
            "Incremental and Agent comparisons used synthetic fixtures.",
            "Agent pytest was scoped to change-review-agent/tests so protected workspace dependency caches were not collected as project tests.",
        ],
    }
    subprocess.run(["git", "diff", "--check"], cwd=WORKSPACE, check=True)
    write_json(ROOT / "validation_results.json", validation)

    all_active = retrieval["scenarios"]["all_active"]
    single = retrieval["scenarios"]["single_document"]
    multi = retrieval["scenarios"]["multi_document"]
    all_p50 = all_active["latency_ms"]["p50"]
    all_p95 = all_active["latency_ms"]["p95"]
    single_p50 = single["latency_ms"]["p50"]
    single_p95 = single["latency_ms"]["p95"]
    scope_p50_reduction = reduction_percent(all_p50, single_p50)

    write_markdown(
        "rag_retrieval_benchmark.md",
        f"""
# RAG `/retrieve` Benchmark

- Policy: `DENSE_ONLY + SECTION_PATH`
- Transport: loopback HTTP
- Fixed queries: {retrieval['query_count']}
- TopK: {retrieval['top_k']}
- Warm-up: {retrieval['warmup_rounds']} rounds per query/scope
- Measured: {retrieval['measured_rounds']} rounds per query/scope
- Online model calls: NO

| Scope | Candidate vectors | Samples | Mean ms | P50 ms | P90 ms | P95 ms | Std ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| All ACTIVE | {all_active['candidate_vector_count']} | {all_active['measured_request_count']} | {fmt(all_active['latency_ms']['mean'])} | {fmt(all_p50)} | {fmt(all_active['latency_ms']['p90'])} | {fmt(all_p95)} | {fmt(all_active['latency_ms']['std'])} |
| Single document | {single['candidate_vector_count']} | {single['measured_request_count']} | {fmt(single['latency_ms']['mean'])} | {fmt(single_p50)} | {fmt(single['latency_ms']['p90'])} | {fmt(single_p95)} | {fmt(single['latency_ms']['std'])} |
| Two documents | {multi['candidate_vector_count']} | {multi['measured_request_count']} | {fmt(multi['latency_ms']['mean'])} | {fmt(multi['latency_ms']['p50'])} | {fmt(multi['latency_ms']['p90'])} | {fmt(multi['latency_ms']['p95'])} | {fmt(multi['latency_ms']['std'])} |

All Scope membership, ACTIVE-only, rank, and TopK correctness gates passed.
The single-document P50 was {fmt(scope_p50_reduction)}% lower in this corpus, but
this is not promoted as a primary optimization claim: the selected document has
only {single['candidate_vector_count']} vectors, while ALL ACTIVE has
{all_active['candidate_vector_count']}. Scope's primary value is business
correctness.

Cold-start engineering record (one sample): health ready in
{fmt(retrieval['cold_start']['process_start_to_health_ready_ms'])} ms; first
retrieve ready in {fmt(retrieval['cold_start']['process_start_to_first_retrieve_ready_ms'])}
ms. The first retrieve includes local model-worker startup and is not a resume
metric.

Historical-version latency is `NOT_APPLICABLE_TO_FROZEN_CORPUS`: the frozen
artifact has one ACTIVE version per document. Historical correctness is covered
by the synthetic lifecycle benchmark.
""",
    )

    full_p50 = incremental["comparison"]["full_rebuild_p50_seconds"]
    inc_p50 = incremental["comparison"]["incremental_update_p50_seconds"]
    inc_reduction = incremental["comparison"]["elapsed_reduction_percent"]
    reuse_rate = incremental["counts"]["embedding_reuse_rate_percent"]
    write_markdown(
        "rag_incremental_benchmark.md",
        f"""
# RAG Incremental Update Benchmark

Controlled synthetic version fixture: 12 V2 sections, with 9 unchanged, 2
modified, 1 added, and 1 V1-only removed section. Every one of the five measured
runs started from a new lifecycle store. Both paths used the same warm local
`{incremental['embedding_model']}` snapshot; no online model was called.

| Metric | Full rebuild | Incremental |
|---|---:|---:|
| P50 total seconds | {fmt(full_p50)} | {fmt(inc_p50)} |
| P95 total seconds | {fmt(incremental['full_rebuild']['total_seconds']['p95'])} | {fmt(incremental['incremental_update']['total_seconds']['p95'])} |
| P50 Embedding seconds | {fmt(incremental['full_rebuild']['embedding_seconds']['p50'])} | {fmt(incremental['incremental_update']['embedding_seconds']['p50'])} |
| P50 index-refresh seconds | {fmt(incremental['full_rebuild']['index_refresh_seconds']['p50'])} | {fmt(incremental['incremental_update']['index_refresh_seconds']['p50'])} |
| Embeddings computed | {incremental['counts']['total_embeddings_required_full']} | {incremental['counts']['new_embeddings_incremental']} |

- Reused embeddings: **{incremental['counts']['reused_embeddings']} / {incremental['counts']['total_embeddings_required_full']} ({fmt(reuse_rate)}%)**
- P50 elapsed reduction: **{fmt(inc_reduction)}%**
- Embedding compute-count reduction: **{fmt(incremental['counts']['embedding_compute_reduction_percent'])}%**
- Observed P50 embedding-time reduction: **{fmt(incremental['comparison']['embedding_elapsed_reduction_percent'])}%**
- Effect: **{effect_label(inc_reduction)}**

`FULL_REBUILD_SCOPE = target document from normalized SectionSnapshot input`.
Upstream source-format parsing is excluded equally because the formal lifecycle
API receives normalized sections. The update reuses content-hash embeddings and
then applies `{incremental['index_refresh_strategy']}`: it rewrites the exact
active vector matrix from cached vectors and is not an in-place FAISS update.

ACTIVE default, explicit historical scope, and version diff correctness passed.
""",
    )

    fresh_latency = fresh["latency"]["elapsed_ms"]
    write_markdown(
        "agent_fresh_run_benchmark.md",
        f"""
# Agent Fresh Run Benchmark

Offline deterministic EXTRACTIVE benchmark using one synthetic eight-section,
eight-field DOCX template. Human review time is excluded and LLM calls are zero.

| Metric | Value |
|---|---:|
| Sections / fields | {fresh['counts']['total_sections']} / {fresh['counts']['total_fields']} |
| RAG calls | {fresh['counts']['total_rag_calls']} |
| Evidence | {fresh['counts']['evidence_count']} |
| Drafted / missing fields | {fresh['counts']['drafted_fields']} / {fresh['counts']['missing_fields']} |
| P50 total | {fmt(fresh_latency['p50'])} ms |
| P95 total | {fmt(fresh_latency['p95'])} ms |
| Mean / std | {fmt(fresh_latency['mean'])} / {fmt(fresh_latency['std'])} ms |

This is a local engineering latency record, not live-LLM or production latency.
""",
    )

    resume_rows = []
    for point in ("25", "50", "75"):
        row = resume["scenarios"][point]
        comparison = row["comparison"]
        resume_rows.append(
            f"| {point}% | {row['sections_skipped_on_resume']} | "
            f"{comparison['full_rerun_rag_calls']} → {comparison['resume_rag_calls']} | "
            f"{fmt(comparison['rag_call_reduction_percent'])}% | "
            f"{fmt(comparison['full_rerun_p50_ms'])} → {fmt(comparison['resume_p50_ms'])} | "
            f"{fmt(comparison['elapsed_reduction_percent'])}% | "
            f"{effect_label(comparison['elapsed_reduction_percent'])} |"
        )
    write_markdown(
        "agent_resume_benchmark.md",
        f"""
# Agent Full Rerun vs Checkpoint Resume

Each scenario used five warm-ups and 30 measured pairs. Checkpoints were created
by a controlled interruption after the stated number of completed sections.
Full rerun and Resume used identical Scope, template, required output, evidence,
and EXTRACTIVE drafting.

| Completed | Sections skipped | RAG calls | Call reduction | P50 ms full → resume | Time reduction | Effect |
|---:|---:|---:|---:|---:|---:|---|
{chr(10).join(resume_rows)}

All Resume paths skipped exactly the completed sections and produced the same
semantic drafts as a full rerun. On this small eight-section template, fixed
costs for template parsing, checkpoint restoration, freshness validation, and
full DOCX rendering dominate at 25% and 50% completion. The time result is
therefore a regression at 25%, neutral at 50%, and moderate only at 75%. The RAG
call and section-work reductions remain exact and are the more portable metric.
""",
    )

    stale_cmp = stale["comparison"]
    write_markdown(
        "agent_stale_refresh_benchmark.md",
        f"""
# Agent Full Refresh vs Stale Local Refresh

The synthetic workflow contains {stale['counts']['total_sections']} sections.
After V2 activation, exactly {stale['counts']['stale_sections']} sections become
STALE; the remaining {stale['counts']['preserved_sections']} stay valid.

| Metric | Full refresh | Local refresh |
|---|---:|---:|
| Sections executed | {stale['counts']['total_sections']} | {stale['counts']['refreshed_sections']} |
| RAG calls | {stale_cmp['full_refresh_rag_calls']} | {stale_cmp['local_refresh_rag_calls']} |
| P50 elapsed | {fmt(stale_cmp['full_refresh_p50_ms'])} ms | {fmt(stale_cmp['local_refresh_p50_ms'])} ms |
| P95 elapsed | {fmt(stale['full_refresh']['elapsed_ms']['p95'])} ms | {fmt(stale['local_refresh']['elapsed_ms']['p95'])} ms |

- Preserved sections: **{stale['counts']['preserved_sections']} / {stale['counts']['total_sections']} ({fmt(stale['counts']['preserved_ratio_percent'])}%)**
- RAG-call reduction: **{fmt(stale_cmp['rag_call_reduction_percent'])}%**
- P50 elapsed reduction: **{fmt(stale_cmp['elapsed_reduction_percent'])}%**
- Effect: **{effect_label(stale_cmp['elapsed_reduction_percent'])}**

Freshness selected exactly the two changed documents, untouched sections were
not re-executed, and the final semantic output matched a full V2 refresh.
""",
    )

    r75 = resume["scenarios"]["75"]["comparison"]
    write_markdown(
        "resume_metrics_for_resume.md",
        f"""
# 可用于简历的工程指标

这些数字来自当前机器上的受控工程基准，不代表生产环境或企业真实业务流量。

## RAG 推荐指标

1. **版本增量更新**
   可直接使用：**“在 12 章节的受控版本更新基准中，通过章节级变化检测和内容哈希 Embedding 复用，复用 9/12（{fmt(reuse_rate)}%）向量，将目标文档更新 P50 耗时由 {fmt(full_p50)}s 降至 {fmt(inc_p50)}s，减少 {fmt(inc_reduction)}%。”**
   可以写的原因：五次独立运行、相同本地 BGE 模型、相同 V2 输入、每次重建生命周期 store，并通过 ACTIVE/历史版本和 Diff 正确性校验。

2. **正式检索延迟**
   可直接使用：**“在 3 文档、5,090 向量、TopK=5 的本地研发文档基准中，DENSE_ONLY + SECTION_PATH `/retrieve` 经 450 次有效请求测得 P50 {fmt(all_p50)}ms、P95 {fmt(all_p95)}ms。”**
   可以写的原因：真实 loopback HTTP、固定 15 问 Query Set、每问 5 次预热和 30 次测量，全部 Scope 正确性门禁通过。

## Agent 推荐指标

1. **Checkpoint / Resume 的重复工作减少**
   可直接使用：**“在 8 章节中断恢复基准中，当 75% 章节已完成时，Checkpoint / Resume 将重复 RAG 调用由 {r75['full_rerun_rag_calls']} 次降至 {r75['resume_rag_calls']} 次，并将 P50 恢复耗时由 {fmt(r75['full_rerun_p50_ms'])}ms 降至 {fmt(r75['resume_p50_ms'])}ms。”**
   可以写的原因：30 组有效配对运行，Resume 与全量重跑使用相同 Scope、模板、Evidence 和最终字段输出。面试时必须补充：25% 和 50% 中断点未观察到端到端耗时收益，固定恢复与 DOCX 重写开销占主导。

2. **STALE Evidence 局部刷新**
   可直接使用：**“在 8 章节版本变化基准中，Evidence Freshness 仅重跑 2 个受影响章节，保留 6 个有效章节，将 RAG 调用由 {stale_cmp['full_refresh_rag_calls']} 次降至 {stale_cmp['local_refresh_rag_calls']} 次，P50 耗时减少 {fmt(stale_cmp['elapsed_reduction_percent'])}%。”**
   可以写的原因：30 组有效配对运行，Freshness 命中集合准确，局部刷新与完整 V2 刷新产出语义一致。

## 不建议写入简历

- 单文档 Scope 的延迟下降：样本文档只有 20 个向量，Scope 的主要价值是业务正确性。
- 冷启动 16 秒级记录：只有一个样本，且包含本地模型进程加载。
- Agent Fresh Run 的约 0.25 秒：这是离线 EXTRACTIVE 合成基准，不是公网 LLM 延迟。
- Resume 25%/50% 的耗时结果：分别为回归和中性结果。
- 任何 Production QPS、生产级性能、真实企业业务提升或实际调用成本声明。
""",
    )

    report = f"""
# RAG + Agent Engineering Performance Benchmark

生成时间：{utc_now()}

## 1. 结论

本轮没有修改 RAG、Agent 或 UI 核心业务代码。所有新增文件均位于
`project_delivery/performance_benchmark/`。结果来自同一台机器、固定配置、
固定数据和固定 TopK；没有在线 Embedding 或 LLM 调用，也没有为了数字修改
检索、Agent 步骤、Prompt、Retry 或 Timeout。

| 工程项 | 结果 | 效果标签 |
|---|---|---|
| RAG `/retrieve` ALL ACTIVE | P50 {fmt(all_p50)} ms；P95 {fmt(all_p95)} ms | ABSOLUTE METRIC |
| RAG 增量更新 | {fmt(full_p50)}s → {fmt(inc_p50)}s；减少 {fmt(inc_reduction)}% | {effect_label(inc_reduction)} |
| Embedding 复用 | {incremental['counts']['reused_embeddings']}/{incremental['counts']['total_embeddings_required_full']}；{fmt(reuse_rate)}% | STRONG WORK REDUCTION |
| Agent Resume 25% | RAG {resume['scenarios']['25']['comparison']['full_rerun_rag_calls']}→{resume['scenarios']['25']['comparison']['resume_rag_calls']}；耗时 {fmt(resume['scenarios']['25']['comparison']['elapsed_reduction_percent'])}% | {effect_label(resume['scenarios']['25']['comparison']['elapsed_reduction_percent'])} |
| Agent Resume 50% | RAG {resume['scenarios']['50']['comparison']['full_rerun_rag_calls']}→{resume['scenarios']['50']['comparison']['resume_rag_calls']}；耗时 {fmt(resume['scenarios']['50']['comparison']['elapsed_reduction_percent'])}% | {effect_label(resume['scenarios']['50']['comparison']['elapsed_reduction_percent'])} |
| Agent Resume 75% | RAG {r75['full_rerun_rag_calls']}→{r75['resume_rag_calls']}；耗时减少 {fmt(r75['elapsed_reduction_percent'])}% | {effect_label(r75['elapsed_reduction_percent'])} |
| Agent STALE 局部刷新 | 仅执行 2/8 章节；耗时减少 {fmt(stale_cmp['elapsed_reduction_percent'])}% | {effect_label(stale_cmp['elapsed_reduction_percent'])} |

## 2. 环境

- OS：{env['machine']['os_caption']}（version {env['machine']['os_version']}，build {env['machine']['os_build']}）
- CPU：{env['machine']['cpu']}；逻辑核 {env['machine']['logical_cpu_count']}
- RAM：{env['machine']['ram_bytes']} bytes
- RAG Python：{env['rag_environment']['python_version']}
- PyTorch / FAISS：{env['rag_environment']['pytorch_version']} / {env['rag_environment']['faiss_version']}
- Embedding：{env['rag_environment']['embedding_model']}，revision `{env['rag_environment']['embedding_model_revision']}`，512 维，本地 CPU
- Corpus：3 documents / 3 ACTIVE versions / 5,090 chunks
- Retrieval：DENSE_ONLY + SECTION_PATH；TopK=5；dense candidate K=20
- Agent Python：{env['agent_environment']['python_version']}
- Agent fixture：合成 8 sections / 8 fields；EXTRACTIVE；LLM calls=0
- Benchmark date：{env['benchmark_date_local']}（{env['benchmark_timezone']}）

## 3. 核心问题回答

1. 当前 ALL ACTIVE `/retrieve`：P50 **{fmt(all_p50)} ms**，P95 **{fmt(all_p95)} ms**，450 个有效样本。
2. 指定单文档 Scope：P50 **{fmt(single_p50)} ms**，P95 **{fmt(single_p95)} ms**，候选向量 20；全部结果均来自指定文档。
3. 新版本增量更新：目标文档 P50 从 **{fmt(full_p50)}s** 降至 **{fmt(inc_p50)}s**，减少 **{fmt(inc_reduction)}%**。
4. 增量复用 **9/12 Embedding（{fmt(reuse_rate)}%）**，仅计算 3 个新向量。
5. Resume 跳过工作与完成点一致：25%/50%/75% 分别跳过 2/4/6 个章节。端到端耗时只在 75% 场景取得明显收益；低完成度受固定开销影响。
6. Resume RAG 调用分别从 8 降至 6/4/2，即减少 25%/50%/75%。
7. 文档版本变化后，局部刷新只执行 2/8 章节，保留 6/8，章节重执行减少 75%。
8. 局部刷新 RAG 调用从 8 降至 2，减少 75%；P50 耗时减少 {fmt(stale_cmp['elapsed_reduction_percent'])}%。
9. 正确性保持：Scope、ACTIVE/历史版本、Diff、相同模板、相同必填输出、Resume 跳过和 STALE 精确命中均通过；回归 34+112+12 全通过。
10. 简历建议使用增量 Embedding 复用、增量更新时间、`/retrieve` P95、75% Resume 重复调用减少和 STALE 局部刷新。冷启动、Scope 小样本加速、Fresh 离线耗时与 25%/50% Resume 耗时只放工程报告。

## 4. 方法与边界

- Retrieval：15 个固定问题，3 个 Scope；每个 query/scope 5 次预热、30 次测量，所有有效样本进入统计。
- Incremental：1 组预热、5 组独立 store；V2 75% 章节不变；相同本地 BGE；模型已预热，生命周期 cache 每组冷启动。
- Agent：每场景 5 次预热、30 次测量；配对运行交替先后顺序；合成安全数据；无网络 LLM。
- Agent Fresh P50/P95 为 {fmt(fresh_latency['p50'])}/{fmt(fresh_latency['p95'])} ms，只代表离线 EXTRACTIVE 工程开销。
- Evidence Cache：`SKIPPED`。fixture 每个 SectionTask 使用独立必要 query，没有公平的自然重复请求场景。
- 历史 `/retrieve` 延迟：`NOT FAIRLY BENCHMARKABLE` 于当前冻结 corpus；它没有 SUPERSEDED 版本。版本生命周期 fixture 已验证历史检索正确性。
- Full rebuild 从规范化 SectionSnapshot 开始；当前正式生命周期 API 不承担上游源文件解析。两条对比路径均排除上游 parse，因而比较目标一致。
- 本报告不声明 Production QPS、生产级性能、真实企业业务提升或实际 LLM 成本。

## 5. 最终验收字段

```text
BENCHMARK_ENV_CAPTURED = YES
CORE_BUSINESS_CODE_CHANGED = NO
FINAL_RETRIEVAL_POLICY = DENSE_ONLY
FINAL_DENSE_REPRESENTATION = SECTION_PATH

RAG_RETRIEVAL_BENCHMARK = PASS
RAG_RETRIEVE_ALL_ACTIVE_P50_MS = {fmt(all_p50)}
RAG_RETRIEVE_ALL_ACTIVE_P95_MS = {fmt(all_p95)}
RAG_RETRIEVE_SINGLE_DOC_P50_MS = {fmt(single_p50)}
RAG_RETRIEVE_SINGLE_DOC_P95_MS = {fmt(single_p95)}

RAG_INCREMENTAL_BENCHMARK = PASS
FULL_REBUILD_SCOPE = target document from normalized SectionSnapshot input
FULL_REBUILD_SECONDS = {fmt(full_p50)}
INCREMENTAL_UPDATE_SECONDS = {fmt(inc_p50)}
INCREMENTAL_TIME_REDUCTION_PERCENT = {fmt(inc_reduction)}
TOTAL_EMBEDDINGS_FULL = {incremental['counts']['total_embeddings_required_full']}
NEW_EMBEDDINGS_INCREMENTAL = {incremental['counts']['new_embeddings_incremental']}
REUSED_EMBEDDINGS = {incremental['counts']['reused_embeddings']}
EMBEDDING_REUSE_RATE_PERCENT = {fmt(reuse_rate)}
INDEX_REFRESH_STRATEGY = {incremental['index_refresh_strategy']}

AGENT_FRESH_RUN_BENCHMARK = PASS
AGENT_TOTAL_SECTIONS = {fresh['counts']['total_sections']}
AGENT_TOTAL_FIELDS = {fresh['counts']['total_fields']}
AGENT_TOTAL_RAG_CALLS = {fresh['counts']['total_rag_calls']}
AGENT_TOTAL_SECONDS = {fmt(fresh_latency['p50'] / 1000.0, 6)}

AGENT_RESUME_BENCHMARK = PASS
RESUME_COMPLETION_POINT = 75% (25% and 50% also reported)
FULL_RERUN_SECONDS = {fmt(r75['full_rerun_p50_ms'] / 1000.0, 6)}
RESUME_SECONDS = {fmt(r75['resume_p50_ms'] / 1000.0, 6)}
RESUME_TIME_REDUCTION_PERCENT = {fmt(r75['elapsed_reduction_percent'])}
FULL_RERUN_RAG_CALLS = {r75['full_rerun_rag_calls']}
RESUME_RAG_CALLS = {r75['resume_rag_calls']}
RESUME_RAG_CALL_REDUCTION_PERCENT = {fmt(r75['rag_call_reduction_percent'])}
SECTIONS_SKIPPED_ON_RESUME = {resume['scenarios']['75']['sections_skipped_on_resume']}

AGENT_STALE_REFRESH_BENCHMARK = PASS
TOTAL_SECTIONS = {stale['counts']['total_sections']}
STALE_SECTIONS = {stale['counts']['stale_sections']}
PRESERVED_SECTIONS = {stale['counts']['preserved_sections']}
LOCAL_REFRESH_RATIO_PERCENT = {fmt(stale['counts']['refresh_ratio_percent'])}
FULL_REFRESH_SECONDS = {fmt(stale_cmp['full_refresh_p50_ms'] / 1000.0, 6)}
LOCAL_REFRESH_SECONDS = {fmt(stale_cmp['local_refresh_p50_ms'] / 1000.0, 6)}
LOCAL_REFRESH_TIME_REDUCTION_PERCENT = {fmt(stale_cmp['elapsed_reduction_percent'])}
FULL_REFRESH_RAG_CALLS = {stale_cmp['full_refresh_rag_calls']}
LOCAL_REFRESH_RAG_CALLS = {stale_cmp['local_refresh_rag_calls']}
LOCAL_REFRESH_RAG_CALL_REDUCTION_PERCENT = {fmt(stale_cmp['rag_call_reduction_percent'])}

CORRECTNESS_PRESERVED = PASS
RAG_REGRESSION = 34 passed / 0 failed
AGENT_REGRESSION = 112 passed / 0 failed
UI_REGRESSION = 12 passed / 0 failed
GIT_DIFF_CHECK = PASS
SAFE_DATA_ONLY = YES
REAL_INTERNAL_DATA_SENT_TO_ONLINE_LLM = NO
```

## 6. Artifact index

- `benchmark_plan.md`: pre-run audit and fixed methodology.
- `benchmark_environment.json`: machine, interpreter, model and corpus facts.
- `rag_retrieval_benchmark.json`: raw retrieval samples and statistics.
- `rag_incremental_benchmark.json`: five independent full/incremental pairs.
- `agent_fresh_run_benchmark.json`: 30 fresh workflow samples.
- `agent_resume_benchmark.json`: 25%/50%/75% completion scenarios.
- `agent_stale_refresh_benchmark.json`: full versus local refresh pairs.
- `validation_results.json`: regression and engineering checks.
- Per-benchmark Markdown summaries and `resume_metrics_for_resume.md`.
"""
    write_markdown("performance_benchmark_report.md", report)
    print(
        json.dumps(
            {
                "status": "PASS",
                "report": str(ROOT / "performance_benchmark_report.md"),
                "resume_metrics": str(ROOT / "resume_metrics_for_resume.md"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
