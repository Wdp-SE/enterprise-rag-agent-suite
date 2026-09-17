# 验证证据与 Claim Matrix

## 1. 验证环境

| 项目 | 最终审计值 |
|---|---|
| Python | 3.12.13，独立 `.venv` |
| pip | 25.0.1 |
| Docker | daemon 正常，container smoke 通过 |
| Docker SDK | 7.1.0 |
| OpenManus | 0.1 editable install |
| 依赖一致性 | `python -m pip check` 通过 |

最终收尾回归的实时结果记录在 `FINALIZATION_REPORT.md`。

## 2. 测试证据

| 测试组 | 数量 | 代码位置 | 证明范围 |
|---|---:|---|---|
| Minimal Core | 41 | `tests/research/` | Profile、Evidence、双 hash、Store、Archive、stable ID、Candidate 构建/验证、offline E2E |
| Live Workflow | 78 | `tests/research_live/` | Search/selection/acquisition/extraction/result/adapters、LLM budget、RAG adapter、Reliability 集成 |
| Reliability | 214 | `tests/reliability/` | Error/Retry/Timeout/Result/Trace、Executor、Budget、Progress、TaskPolicy/Controller |
| Sandbox | 28 | `tests/sandbox/` | Docker session、terminal、files、container lifecycle 与 Windows socket 兼容 |
| Full project | 361 | `tests/` | 上述全部回归组合 |

测试数不是覆盖率；仓库没有声称特定代码覆盖率百分比。

## 3. 真实运行证据

真实 run：`kr_20260828T082105547457Z_b40bc521`。

| 工件 | 相对路径 | 可验证内容 |
|---|---|---|
| Run manifest | `../workspace/research_runs/kr_20260828T082105547457Z_b40bc521/outputs/run_manifest.json` | Search、selection、download、Evidence、状态与错误 |
| EvidenceStore | `../workspace/research_runs/kr_20260828T082105547457Z_b40bc521/evidence/evidence.json` | 22 条 Evidence、locator、content/raw hash |
| Raw sources | `../workspace/research_runs/kr_20260828T082105547457Z_b40bc521/raw_sources/` | 两份成功归档的原始 HTML |
| Deterministic Markdown | `../workspace/research_runs/kr_20260828T082105547457Z_b40bc521/outputs/research_report.md` | Evidence-only 确定性报告 |
| Deterministic JSON | `../workspace/research_runs/kr_20260828T082105547457Z_b40bc521/outputs/structured_result.json` | 通用 ResearchResult |
| Selection report | `../workspace/research_runs/kr_20260828T082105547457Z_b40bc521/outputs/evidence_selection_report.json` | 22 → 6、token estimate、来源分布与选择原因 |
| LLM Markdown | `../workspace/research_runs/kr_20260828T082105547457Z_b40bc521/outputs/research_report_llm.md` | 单次真实 LLM synthesis 结果 |
| LLM JSON | `../workspace/research_runs/kr_20260828T082105547457Z_b40bc521/outputs/structured_result_llm.json` | LLM ResearchResult 与 evidence IDs |
| LLM metrics | `../workspace/research_runs/kr_20260828T082105547457Z_b40bc521/outputs/llm_synthesis_metrics.json` | model、真实 tokens、latency、grounding result |
| Candidate fixture | `../tests/fixtures/candidate/valid_candidate/` | 可离线审阅的合法 Candidate Package 契约 |

历史实施与回归报告：

- `../docs/knowledge_research_minimal_core_implementation_report.md`
- `../docs/knowledge_research_live_workflow_report.md`
- `../docs/full_regression_gate_report.md`
- `../docs/sandbox_compatibility_patch_report.md`

Phase 1A–1D 没有分别保存独立 Markdown 报告，因此其事实证据以 `app/reliability/`、`app/research/reliability.py`、对应测试和最终 361 项回归为准，不虚构不存在的报告文件。

## 4. Claim Matrix

| 对外 Claim | 证据 | 验证方式 | 边界 |
|---|---|---|---|
| 未修改 Agent Core 核心语义 | 独立 `app/agent/knowledge_research.py`、`app/research/`、原 Agent 回归 | 代码审计 + Full/Sandbox tests | Sandbox 有独立基础设施兼容补丁 |
| Research Workflow 可脱离 RAG 完成 | Markdown/JSON adapters、workflow tests、真实两类报告 | Fake E2E + 真实 run 工件 | Candidate 只是第三种输出 |
| 核心代码不绑定特种设备行业 | ResearchProfile 配置、通用 model/ports | 搜索核心模块中的领域规则 + 多 Fake profile tests | 当前只完成一个真实行业样本 |
| Search 结果结构化保留 | `app/research/search_adapter.py`、search tests | 对 title/url/snippet/engine 断言 | 仍依赖原 WebSearch provider 输出 |
| 原始资料与 Evidence 分离 | Raw source 目录、EvidenceStore、extractor tests | 文件与 Evidence locator/hash 对照 | 只支持 HTML/text PDF |
| content_hash/raw_file_hash 不混用 | Evidence/schema/validator tests | 分别篡改文本与文件字节验证拒绝 | hash 证明身份，不证明内容正确 |
| Stable ID 与顺序稳定 | stable ID tests、重复 build tests | 打乱 Evidence 顺序并比较 IDs/Sxx | 内容或 canonical identity 改变会产生新 ID |
| Candidate 原子发布且可 REUSED | builder/offline E2E tests | 同输入连续构建 CREATED → REUSED | 不覆盖已存在的不同包 |
| Agent 不能设置 APPROVED | metadata model/validator tests | APPROVED fixture 被拒绝 | 审批必须由外部流程负责 |
| 真实 Candidate 通过 RAG v2 | Live workflow report 中的 import 结果 | 外部 `import_candidate()` 返回 accepted | `ingestion_performed=false`，未正式入库 |
| EvidenceBudgetPlanner 确定且不改 Store | selection report + budget tests | 打乱输入、检查 token 上限与 Store 快照 | 词法相关性不是语义 reranker |
| 真实 LLM synthesis 成功 | LLM JSON/Markdown/metrics | usage、latency、finding IDs 对照 | 仅一次真实模型/一个主题 |
| 8/8 findings grounded | `llm_synthesis_metrics.json` | GroundingValidator 检查 ID 存在与集合归属 | 不证明语义蕴含 |
| 403 与 TLS EOF 分类不同 | Phase 1B integration tests | 403 不重试；瞬时 TLS EOF 有限重试后成功 | 第三方 SDK 内部重试未被全局统一 |
| Budget 是权威、Trace 是投影 | budget/executor/trace tests | reserve/commit 与 trace failure 隔离 | 尚无分布式账本 |
| NoProgress 基于状态变化 | progress tests | 重复/新 progress signal 序列 | 仅接入已定义信号的 Workflow |
| TaskPolicy 支持四种 action | policy/workflow_control tests | CONTINUE/STOP/FALLBACK/REPLAN fixture | Research 当前 observer，不全量 enforce |
| Windows Docker socket 兼容 | sandbox patch report、socket tests | Npipe-like/Unix-like 行为 + container smoke | 未声称覆盖所有 Docker SDK 版本 |
| 全项目 361 passed | pytest 最终输出 | `python -m pytest tests -q` | 测试通过不等于生产 SLA |

## 5. 真实指标明细

| 指标 | 数值 | 来源 |
|---|---:|---|
| search_count | 7 | run manifest |
| selected_source_count | 3 | run manifest |
| download_success | 2 | run manifest |
| download_failure | 1 | run manifest |
| evidence_count | 22 | EvidenceStore / manifest |
| selected_evidence_count | 6 | selection report |
| original_estimated_tokens | 35,313 | selection report |
| selected_estimated_tokens | 9,640 | selection report |
| selected_prompt_estimated_tokens | 9,795 | selection report |
| max_context_budget | 20,000 | selection report |
| max_evidence_budget | 14,345 | selection report |
| model | qwen-max | LLM metrics |
| prompt_tokens | 5,479 | API usage metrics |
| completion_tokens | 495 | API usage metrics |
| total_tokens | 5,974 | API usage metrics |
| latency_ms | 11,500 | LLM metrics |
| finding_count | 8 | LLM metrics |
| grounded_finding_count | 8 | LLM metrics |
| rejected_finding_count | 0 | LLM metrics |
| semantic_entailment_verified | false | LLM metrics |

## 6. 安全证据

- `config/config.toml` 已加入 `.gitignore`；
- 收尾审计发现本地 Daytona 配置疑似凭据后已替换为 `YOUR_DAYTONA_API_KEY` 占位符；
- README/交付材料不记录 API Key、Authorization Header 或敏感环境变量；
- Candidate 权限测试拒绝 `APPROVED`；
- RawSourceArchive 测试拒绝路径逃逸和 symlink；
- 本次收尾未删除真实 run、Fixture、历史报告或大型 workspace 资产。

## 7. 证据解释边界

1. 历史真实 run 早于 Reliability Phase 1D 完整落地，因此不能声称该 run 已保存全链结构化 Trace；
2. 本机真实 Candidate 目录存在局部 Windows ACL 访问限制，RAG accepted 记录和合法 Fixture 仍可验证契约；
3. Search/Browser/LLM 的在线可用性取决于第三方服务，演示默认采用已保存工件；
4. 361 项测试证明当前已编码契约的回归状态，不代表并发性能、长期稳定性或未知场景正确性。
