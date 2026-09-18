# RAG + Agent Engineering Performance Benchmark

生成时间：2026-09-18T16:23:56.550040+00:00

## 1. 结论

本轮没有修改 RAG、Agent 或 UI 核心业务代码。所有新增文件均位于
`project_delivery/performance_benchmark/`。结果来自同一台机器、固定配置、
固定数据和固定 TopK；没有在线 Embedding 或 LLM 调用，也没有为了数字修改
检索、Agent 步骤、Prompt、Retry 或 Timeout。

| 工程项 | 结果 | 效果标签 |
|---|---|---|
| RAG `/retrieve` ALL ACTIVE | P50 82.166 ms；P95 101.074 ms | ABSOLUTE METRIC |
| RAG 增量更新 | 0.555s → 0.381s；减少 31.351% | MODERATE |
| Embedding 复用 | 9/12；75.000% | STRONG WORK REDUCTION |
| Agent Resume 25% | RAG 8→6；耗时 -20.001% | REGRESSION |
| Agent Resume 50% | RAG 8→4；耗时 -1.679% | NEUTRAL |
| Agent Resume 75% | RAG 8→2；耗时减少 21.398% | MODERATE |
| Agent STALE 局部刷新 | 仅执行 2/8 章节；耗时减少 24.924% | MODERATE |

## 2. 环境

- OS：Microsoft Windows 11 家庭版 中文版（version 10.0.26200，build 26200）
- CPU：13th Gen Intel(R) Core(TM) i5-13500H；逻辑核 16
- RAM：16837021696 bytes
- RAG Python：3.11.3 | packaged by Anaconda, Inc. | (main, Apr 19 2023, 23:46:34) [MSC v.1916 64 bit (AMD64)]
- PyTorch / FAISS：2.4.0+cpu / 1.9.0.post1
- Embedding：BAAI/bge-small-zh-v1.5，revision `7999e1d3359715c523056ef9478215996d62a620`，512 维，本地 CPU
- Corpus：3 documents / 3 ACTIVE versions / 5,090 chunks
- Retrieval：DENSE_ONLY + SECTION_PATH；TopK=5；dense candidate K=20
- Agent Python：3.12.13 (main, Apr 14 2026, 14:31:26) [MSC v.1944 64 bit (AMD64)]
- Agent fixture：合成 8 sections / 8 fields；EXTRACTIVE；LLM calls=0
- Benchmark date：2026-09-19（中国标准时间）

## 3. 核心问题回答

1. 当前 ALL ACTIVE `/retrieve`：P50 **82.166 ms**，P95 **101.074 ms**，450 个有效样本。
2. 指定单文档 Scope：P50 **71.549 ms**，P95 **89.320 ms**，候选向量 20；全部结果均来自指定文档。
3. 新版本增量更新：目标文档 P50 从 **0.555s** 降至 **0.381s**，减少 **31.351%**。
4. 增量复用 **9/12 Embedding（75.000%）**，仅计算 3 个新向量。
5. Resume 跳过工作与完成点一致：25%/50%/75% 分别跳过 2/4/6 个章节。端到端耗时只在 75% 场景取得明显收益；低完成度受固定开销影响。
6. Resume RAG 调用分别从 8 降至 6/4/2，即减少 25%/50%/75%。
7. 文档版本变化后，局部刷新只执行 2/8 章节，保留 6/8，章节重执行减少 75%。
8. 局部刷新 RAG 调用从 8 降至 2，减少 75%；P50 耗时减少 24.924%。
9. 正确性保持：Scope、ACTIVE/历史版本、Diff、相同模板、相同必填输出、Resume 跳过和 STALE 精确命中均通过；回归 34+112+12 全通过。
10. 简历建议使用增量 Embedding 复用、增量更新时间、`/retrieve` P95、75% Resume 重复调用减少和 STALE 局部刷新。冷启动、Scope 小样本加速、Fresh 离线耗时与 25%/50% Resume 耗时只放工程报告。

## 4. 方法与边界

- Retrieval：15 个固定问题，3 个 Scope；每个 query/scope 5 次预热、30 次测量，所有有效样本进入统计。
- Incremental：1 组预热、5 组独立 store；V2 75% 章节不变；相同本地 BGE；模型已预热，生命周期 cache 每组冷启动。
- Agent：每场景 5 次预热、30 次测量；配对运行交替先后顺序；合成安全数据；无网络 LLM。
- Agent Fresh P50/P95 为 253.986/330.316 ms，只代表离线 EXTRACTIVE 工程开销。
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
RAG_RETRIEVE_ALL_ACTIVE_P50_MS = 82.166
RAG_RETRIEVE_ALL_ACTIVE_P95_MS = 101.074
RAG_RETRIEVE_SINGLE_DOC_P50_MS = 71.549
RAG_RETRIEVE_SINGLE_DOC_P95_MS = 89.320

RAG_INCREMENTAL_BENCHMARK = PASS
FULL_REBUILD_SCOPE = target document from normalized SectionSnapshot input
FULL_REBUILD_SECONDS = 0.555
INCREMENTAL_UPDATE_SECONDS = 0.381
INCREMENTAL_TIME_REDUCTION_PERCENT = 31.351
TOTAL_EMBEDDINGS_FULL = 12
NEW_EMBEDDINGS_INCREMENTAL = 3
REUSED_EMBEDDINGS = 9
EMBEDDING_REUSE_RATE_PERCENT = 75.000
INDEX_REFRESH_STRATEGY = CACHED_VECTOR_EXACT_MATRIX_REFRESH

AGENT_FRESH_RUN_BENCHMARK = PASS
AGENT_TOTAL_SECTIONS = 8
AGENT_TOTAL_FIELDS = 8
AGENT_TOTAL_RAG_CALLS = 8
AGENT_TOTAL_SECONDS = 0.253986

AGENT_RESUME_BENCHMARK = PASS
RESUME_COMPLETION_POINT = 75% (25% and 50% also reported)
FULL_RERUN_SECONDS = 0.239520
RESUME_SECONDS = 0.188267
RESUME_TIME_REDUCTION_PERCENT = 21.398
FULL_RERUN_RAG_CALLS = 8
RESUME_RAG_CALLS = 2
RESUME_RAG_CALL_REDUCTION_PERCENT = 75.000
SECTIONS_SKIPPED_ON_RESUME = 6

AGENT_STALE_REFRESH_BENCHMARK = PASS
TOTAL_SECTIONS = 8
STALE_SECTIONS = 2
PRESERVED_SECTIONS = 6
LOCAL_REFRESH_RATIO_PERCENT = 25.000
FULL_REFRESH_SECONDS = 0.262909
LOCAL_REFRESH_SECONDS = 0.197382
LOCAL_REFRESH_TIME_REDUCTION_PERCENT = 24.924
FULL_REFRESH_RAG_CALLS = 8
LOCAL_REFRESH_RAG_CALLS = 2
LOCAL_REFRESH_RAG_CALL_REDUCTION_PERCENT = 75.000

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
