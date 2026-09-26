# Final Legacy Residual & Dead Code Audit

审计日期：2026-09-19（Asia/Shanghai）
审计模式：READ-ONLY AUDIT
审计对象：`RAG-Challenge-2-main`、`OpenManus-rag`、`demo-ui`
基线提交：`c12dfa5f70fba5878626ec08d944390e5e6d8870`

## 1. 结论

正式代码的业务边界已经收敛，但当前本地工作区还没有达到“看不出原项目来源、没有任何残留”的程度。

- RAG 的 tracked Runtime 已经是单一的企业研发文档生命周期 RAG。15 个 `src` Python 模块都能从 API、CLI、生命周期、可信问答或资产校验路径解释用途，没有发现 BM25、Hybrid、RRF、Reranker、Candidate 或竞赛生产实现。
- Agent 的 tracked Document Workflow Runtime 已经是单一业务，CLI 和 UI 均通过 `DocumentWorkflowFacade` 进入；Agent 只通过 HTTP 调用 RAG。仍有 `retry.py`、`timeout.py` 两个“有实现、有单测、正式流程不调用”的 Reliability 模块。
- 第一次接手当前 **Git clone** 时，开发者仍能从 `OpenManus-rag` 目录名、嵌套 `.github` 元数据、项目演进说明和历史交付报告看出 OpenManus 来源；RAG 的历史清理报告会说明过去的竞赛/候选路径，但不会把它们描述成当前能力。
- 第一次接手当前 **本机工作区** 时，来源更明显：RAG ignored 区仍有旧年报基线、旧测试集与 BM25/Hybrid 等实验报告；Agent ignored `workspace/` 仍有 Knowledge Research、Candidate Knowledge 和通用 OpenManus 示例数据。
- 因此，“当前保留下来的每个 tracked Python 模块都有合理用途”这一问题，RAG 的答案是 **YES**；Agent 的答案是 **NO**，例外是两个 implemented-but-unused Reliability 模块及其自测。

## 2. 审计方法与边界

执行了以下只读检查：

1. `git status`、tracked/untracked/ignored、最近提交与恢复 tag。
2. tracked 文件和本地非 vendor 文件的扩展名、目录、数据/文档/脚本统计。
3. 指定的 RAG、Agent 遗留关键词扫描，并把当前 guard、历史说明、当前测试和无意义残留分开。
4. Python AST import graph、动态导入、`__main__`、FastAPI、CLI、Streamlit、PowerShell 和 benchmark 入口扫描。
5. runtime roots、tests、benchmark、配置、package metadata、docs 的交叉引用。
6. 依赖声明与第三方 import 映射。
7. 配置键、API、Facade、Agent→RAG 边界、重复实现和本地数据目录审计。

没有运行测试，因为 pytest 会写入 cache，与本轮只读审计目标冲突。测试状态引用提交 `c12dfa5` 中的最近一次完整验证：RAG `34 passed`、Agent `112 passed`、UI `12 passed`。没有把“测试通过”当成保留死代码的理由。

## 3. Git 状态

这是一个单体 Git 仓库，三个目录共享根仓库，不是三个独立 Git 仓库。

| 项目 | tracked | 当前未跟踪 | 主要 ignored | 最近影响该目录的提交 |
|---|---:|---:|---|---|
| RAG | 81 | 0 | 当前语料、旧语料/索引/报告、环境与 cache | `1ff9d5f` `refactor: finalize RAG business cleanup` |
| Agent | 78 | 2 | `workspace/`、logs、旧 config、runtime、环境与 cache | `6860b0d` `refactor: finalize document workflow agent cleanup` |
| UI | 22 | 0 | `runtime/`、cache | `ab984fb` `backup: before audited legacy removal` |
| Workspace benchmark/delivery | 27 tracked benchmark文件，另有交付报告 | 0 | 2 个 benchmark runtime 文件 | `c12dfa5` |

当前分支为 `main`，相对 `origin/main` ahead 4。唯一普通 untracked 内容是 Agent 当前集成运行目录中的 2 个 DOCX；另有同一次运行的 4 个 ignored JSON/JSONL。没有 tracked deletion、staged change 或业务源码修改。

恢复点：

- `backup/pre-rag-business-cleanup-20260918` → `6860b0d`
- `backup/pre-legacy-removal-20260918` → `ab984fb`

分类结论：

- `TRACKED_LEGACY`：Agent 嵌套 `.github` 中 6 个明确 OpenManus 品牌文件；2 个未接入 Reliability 模块与 2 个对应自测；1 个过期 UI sprint report。历史清理 manifest/report 属于历史证据，不算当前 Legacy。
- `UNTRACKED_LEGACY`：RAG 无普通 untracked；Agent 普通 untracked 的 2 个 DOCX 属于当前集成输出，不是 Legacy。
- `IGNORED_LEGACY`：存在。RAG 有旧年报/旧域数据、旧索引和实验报告；Agent 有 Research/Candidate 数据、旧 OpenManus config、通用示例、257 个日志和 Phase 1B 临时输出。

## 4. 文件树统计

### 4.1 Tracked 文件

| 项目 | 总文件 | Python | 测试文件 | scripts 下文件 | 文档/报告 | data/fixture | 启发式生成物 |
|---|---:|---:|---:|---:|---:|---:|---:|
| RAG | 81 | 26 | 4 | 5 | 46 | 4 | 17 |
| Agent | 78 | 41 | 8 | 4 | 19 | 0 | 4 |
| UI | 22 | 14 | 5 | 0 | 5 | 0 | 0 |
| Workspace benchmark | 27 | 6 | 0 | 6 | 27 | 3 | 1 |

Tracked 扩展名摘要：

- RAG：32 JSON、26 PY、13 MD、3 DOCX、1 PDF、1 JSONL、1 TXT 及 package/ignore 文件。
- Agent：41 PY、10 MD、11 YAML/YML、7 DOCX、2 JSON、1 PS1、1 TXT 及 repository metadata。
- UI：14 PY、5 MD、1 PS1、1 TXT、1 ignore 文件。

### 4.2 本地物理文件（排除 `.venv`、`workspace`、Git 和常规 cache）

| 项目 | 文件数 | 主要类型 |
|---|---:|---|
| RAG | 542 | 346 JSON、56 MD、41 PDF、26 PY、26 FAISS、14 PNG、8 NPY |
| Agent | 349 | 257 LOG、41 PY、10 MD、9 DOCX、9 JSON、9 YAML |
| UI | 39 | 14 PY、9 JSON、5 MD、4 DOCX、2 JSONL、1 PDF、1 PNG |

另外，`OpenManus-rag/workspace/` 有 58,581 个文件、约 1.91 GB：55,100 个位于 `uv-cache`，3,443 个位于本地 Python runtime，38 个属于旧 Research/Candidate/通用示例数据。前两类是受保护的本地依赖环境，本轮不列为删除目标。

## 5. 关键词审计

### 5.1 RAG

| 命中类型 | 分类 | 判断 |
|---|---|---|
| Runtime 对 `hybrid_enabled`、`reranker_enabled` 的检查 | A 当前必要代码 | 用于拒绝不符合 DENSE_ONLY 正式策略的旧资产，不是 Hybrid/Reranker 路径。 |
| `context_expansion.py` 删除 `rrf_score` 等旧 score 字段 | A 当前必要代码 | 防止旧资产元数据泄漏到正式输出；契约测试覆盖。 |
| 测试中的 `bm25_score`、`rrf_score`、Hybrid/Reranker false | C 当前测试 | 验证正式路径拒绝/剥离旧模式。 |
| README 中“不包含竞赛/候选”、历史 cleanup report/manifest | B Project Evolution | 明确说明旧业务已移除，不把它描述为当前能力。 |
| `.gitignore` 的 `erc2_set`、BM25、Hybrid 旧目录规则 | D 无意义残留片段 | 不影响 runtime，但使旧项目痕迹继续可见；需要未来编辑 `.gitignore`，不是整文件删除候选。 |
| ignored baseline/test_set 与旧实验报告 | D Legacy 本地数据 | 正式 runtime、tests、benchmark 和当前 docs 均无引用。 |

### 5.2 Agent

| 命中类型 | 分类 | 判断 |
|---|---|---|
| README 的 OpenManus/Knowledge Research 项目演进 | B Project Evolution | 历史说明可保留。 |
| `test_timeout.py` 的 `web_search`、`knowledge_research` | D Legacy test vocabulary | 测的是未接入的 TimeoutPolicy；测试文件本身为候选。 |
| `test_errors.py` 的 BrowserUseTool 文本 | C 当前 Reliability 测试但措辞过时 | ErrorClassifier 当前被预算/Trace 使用；只需未来替换 fixture 文本，不应删除整个模块/测试。 |
| 嵌套 issue template、workflow、CODE_OF_CONDUCT 的 OpenManus | D tracked Legacy metadata | 与当前产品无关；嵌套 workflow 在单体仓库中不执行。 |
| ignored `config.toml` 的 browser/search/mcp/daytona/runflow | D ignored Legacy config | 当前 Runtime 没有任何读取。 |
| ignored Research/Candidate workspace 与 Phase 1B 输出 | D ignored Legacy data | 当前 Runtime 没有引用。 |

Active Agent Python 源码中没有 `knowledge_research`、Browser、MCP、Sandbox、Candidate Package、General ReAct 的业务实现。

## 6. 正式入口审计

共识别 19 个可执行文件/应用入口，另有 1 个 console-script alias 和 pytest 的三个项目级测试入口。

| 项目 | PRODUCTION | DEVELOPMENT / VALIDATION | BENCHMARK | LEGACY | UNKNOWN |
|---|---|---|---|---:|---:|
| RAG | `main.py` CLI；`src.rd_v2_api:app` | artifact manifest、offline smoke、V3 E2E、retrieve validator | V3 scope benchmark | 0 | 0 |
| Agent | `run_document_workflow.py`；`document-workflow` alias | template builder、business E2E、Word render Python/PS1 | 0 | 0 | 0 |
| UI | Streamlit `app.py`；`start_demo.ps1` launcher | 0 | 0 | 0 | 0 |
| Workspace benchmark | 0 | report/environment builders | RAG retrieval、incremental、Agent workflow 三类 runner | 0 | 0 |

RAG CLI 只暴露 `serve`、`validate-artifacts`、`ingest-version`、`activate-version`、`diff`、`catalog`。Agent CLI 只暴露 `run`、`resume`、`list`、`show`、`review`、`finalize`。没有 Research/Browser/Candidate/Competition 入口。

## 7. Runtime Dependency Graph

```text
RAG CLI serve
  -> src.rd_v2_api
  -> src.rd_v2_runtime
     -> answer_generation (only /query when explicitly allowed)
     -> artifact_lifecycle
     -> document_lifecycle
     -> native_runtime -> local_embedding_worker process
     -> trusted_qa.*

RAG lifecycle CLI
  -> document_lifecycle.VersionLifecycleService

Agent CLI / UI AgentClient
  -> app.document_workflow.DocumentWorkflowFacade
     -> TemplateParser / Planner / Workflow / Repository / Review / Integrity
     -> HTTPRetrieveClient
        -> RAG HTTP /retrieve and /documents
     -> budget / progress / trace

UI RAG page
  -> services.RAGClient
  -> RAG public HTTP API
```

Runtime 源码没有 `importlib`、字符串类加载、插件 registry 或配置驱动 module import。唯一 `importlib.metadata` 位于 benchmark 环境采集脚本，不改变 runtime reachability 结论。

RAG 15 个 `src` 模块全部 runtime reachable，或由正式生命周期/资产构建入口直接使用。Agent 的全部 19 个 `document_workflow` 模块都从 Facade/Workflow 可达；Reliability 中 budget/errors/progress/trace 可达，retry/timeout 只有 package export 和自测引用。

## 8. Python 模块逐文件分类

分类采用任务定义的 A-J；下表使用完整类别名。

### 8.1 RAG（26）

| 文件 | 分类 | 用途证据 |
|---|---|---|
| `main.py` | PRODUCTION_RUNTIME | 正式 CLI 与服务启动。 |
| `setup.py` | SHARED_INFRASTRUCTURE | 干净 package 名 `enterprise-rd-document-rag`。 |
| `src/__init__.py` | SHARED_INFRASTRUCTURE | package boundary。 |
| `src/answer_generation.py` | PRODUCTION_RUNTIME | `/query` 的结构化生成；默认禁用但属于正式能力。 |
| `src/artifact_lifecycle.py` | PRODUCTION_RUNTIME | 冻结资产 build/checkpoint/validation。 |
| `src/context_expansion.py` | PRODUCTION_RUNTIME | SECTION_PATH 邻域上下文扩展。 |
| `src/document_lifecycle.py` | PRODUCTION_RUNTIME | Document/Version、scope、增量、active index、diff。 |
| `src/local_embedding_worker.py` | PRODUCTION_RUNTIME | 本地模型进程隔离。 |
| `src/native_runtime.py` | SHARED_INFRASTRUCTURE | Torch/向量批次运行约束。 |
| `src/rd_v2_api.py` | PRODUCTION_RUNTIME | 唯一 FastAPI。 |
| `src/rd_v2_runtime.py` | PRODUCTION_RUNTIME | 正式 DENSE_ONLY + SECTION_PATH runtime。 |
| `src/trusted_qa/__init__.py` | PRODUCTION_RUNTIME | Trusted QA public surface。 |
| `src/trusted_qa/audit.py` | PRODUCTION_RUNTIME | Citation/evidence 审计。 |
| `src/trusted_qa/enforcement.py` | PRODUCTION_RUNTIME | 失败关闭与输出门禁。 |
| `src/trusted_qa/models.py` | SHARED_INFRASTRUCTURE | Trusted QA model。 |
| `src/trusted_qa/policy.py` | PRODUCTION_RUNTIME | 当前可信问答策略。 |
| `src/trusted_qa/signals.py` | PRODUCTION_RUNTIME | 检索与引用信号。 |
| `scripts/build_rd_v2_final_artifact_manifest.py` | MIGRATION / CLI REQUIRED | 正式资产构建/验证工具。 |
| `scripts/run_rd_v2_offline_runtime_smoke.py` | CURRENT_TEST_SUPPORT | 当前离线 smoke。 |
| `scripts/run_v3_scope_benchmark.py` | CURRENT_BENCHMARK | 当前 scope benchmark。 |
| `scripts/run_v3_versioned_e2e.py` | CURRENT_TEST_SUPPORT | 当前版本生命周期 E2E。 |
| `scripts/validate_retrieve_api.py` | CURRENT_TEST_SUPPORT | 当前 `/retrieve` 契约验证。 |
| `tests/test_document_lifecycle_v3.py` | CURRENT_TEST_SUPPORT | 生命周期/增量/scope/diff。 |
| `tests/test_formal_runtime_contract.py` | CURRENT_TEST_SUPPORT | 正式策略与 CLI 负向契约。 |
| `tests/test_rd_v2_engineering_hardening.py` | CURRENT_TEST_SUPPORT | 资产、runtime、API、失败关闭。 |
| `tests/test_rd_v3_runtime_api.py` | CURRENT_TEST_SUPPORT | V3 catalog/version/diff API。 |

RAG：`UNKNOWN=0`，`DEAD_CODE=0`。

### 8.2 Agent（41）

| 文件 | 分类 | 用途证据 |
|---|---|---|
| `setup.py` | SHARED_INFRASTRUCTURE | 干净 package 名与 console script。 |
| `run_document_workflow.py` | PRODUCTION_RUNTIME | 正式 CLI，仅调用 Facade。 |
| `app/__init__.py` | SHARED_INFRASTRUCTURE | package boundary。 |
| `app/document_workflow/__init__.py` | PRODUCTION_RUNTIME | 只导出 Facade 与 WorkflowScope。 |
| `app/document_workflow/configuration.py` | PRODUCTION_RUNTIME | 当前环境配置。 |
| `app/document_workflow/drafting.py` | PRODUCTION_RUNTIME | 字段起草与数据分类门禁。 |
| `app/document_workflow/evidence.py` | PRODUCTION_RUNTIME | task/field/query 维度 Evidence Cache。 |
| `app/document_workflow/evidence_models.py` | SHARED_INFRASTRUCTURE | Evidence domain model。 |
| `app/document_workflow/evidence_store.py` | PRODUCTION_RUNTIME | Evidence 持久化底层。 |
| `app/document_workflow/facade.py` | PRODUCTION_RUNTIME | UI/CLI 稳定入口。 |
| `app/document_workflow/freshness.py` | PRODUCTION_RUNTIME | Resume freshness。 |
| `app/document_workflow/integrity.py` | PRODUCTION_RUNTIME | 输出完整性。 |
| `app/document_workflow/models.py` | SHARED_INFRASTRUCTURE | 模板/任务/草稿模型。 |
| `app/document_workflow/planning.py` | PRODUCTION_RUNTIME | Section/Query planning。 |
| `app/document_workflow/policy.py` | PRODUCTION_RUNTIME | 能力门禁。 |
| `app/document_workflow/rag.py` | PRODUCTION_RUNTIME | HTTP Retrieval、Demo client、RAGTool。 |
| `app/document_workflow/repository.py` | PRODUCTION_RUNTIME | Workflow 查询/列表 repository。 |
| `app/document_workflow/review.py` | PRODUCTION_RUNTIME | 人工审核状态机。 |
| `app/document_workflow/scope.py` | PRODUCTION_RUNTIME | Workflow Scope。 |
| `app/document_workflow/state.py` | PRODUCTION_RUNTIME | Checkpoint/Resume state。 |
| `app/document_workflow/sufficiency.py` | PRODUCTION_RUNTIME | Evidence sufficiency。 |
| `app/document_workflow/template.py` | PRODUCTION_RUNTIME | DOCX 解析和渲染。 |
| `app/document_workflow/workflow.py` | PRODUCTION_RUNTIME | 正式编排。 |
| `app/reliability/__init__.py` | SHARED_INFRASTRUCTURE | 仍导出当前模块，也错误导出两个 unused 模块。 |
| `app/reliability/budget.py` | PRODUCTION_RUNTIME | Workflow 实际创建并执行 BudgetLedger。 |
| `app/reliability/errors.py` | SHARED_INFRASTRUCTURE | budget/trace 的结构化错误模型。 |
| `app/reliability/progress.py` | PRODUCTION_RUNTIME | Workflow 实际执行 NoProgressDetector。 |
| `app/reliability/trace.py` | PRODUCTION_RUNTIME | Workflow 实际写 Trace。 |
| `app/reliability/retry.py` | DEAD_CODE | 仅 package export 与自身单测，正式重试另有实现。 |
| `app/reliability/timeout.py` | DEAD_CODE | 仅 package export 与自身单测，正式超时另有实现。 |
| `scripts/create_flagship_template.py` | CURRENT_DEMO | 生成当前旗舰模板。 |
| `scripts/render_word_pdf_pages.py` | CURRENT_DEMO | 文档视觉 QA 工具。 |
| `scripts/run_business_e2e.py` | CURRENT_TEST_SUPPORT | 当前 Safe Business E2E。 |
| `tests/document_workflow/test_business_core.py` | CURRENT_TEST_SUPPORT | 当前核心单测。 |
| `tests/document_workflow/test_business_e2e.py` | CURRENT_TEST_SUPPORT | 当前端到端、Resume、Freshness。 |
| `tests/reliability/test_budget.py` | CURRENT_TEST_SUPPORT | 当前 runtime 使用的 Budget。 |
| `tests/reliability/test_errors.py` | CURRENT_TEST_SUPPORT | 当前错误模型；有一条旧 Browser fixture 文本。 |
| `tests/reliability/test_progress.py` | CURRENT_TEST_SUPPORT | 当前 NoProgress。 |
| `tests/reliability/test_trace.py` | CURRENT_TEST_SUPPORT | 当前 Trace。 |
| `tests/reliability/test_retry.py` | DEAD_CODE | 只证明未接入 RetryPolicy 自身可工作。 |
| `tests/reliability/test_timeout.py` | DEAD_CODE | 只证明未接入 TimeoutPolicy 自身可工作。 |

Agent：`UNKNOWN=0`，`IMPLEMENTED_BUT_UNUSED=2` 个实现模块。

### 8.3 UI（14）

| 文件 | 分类 |
|---|---|
| `app.py` | CURRENT_DEMO |
| `config.py` | CURRENT_DEMO |
| `components/__init__.py` | SHARED_INFRASTRUCTURE |
| `components/evidence_view.py` | CURRENT_DEMO |
| `components/status_view.py` | CURRENT_DEMO |
| `components/workflow_view.py` | CURRENT_DEMO |
| `services/__init__.py` | SHARED_INFRASTRUCTURE |
| `services/agent_client.py` | CURRENT_DEMO |
| `services/rag_client.py` | CURRENT_DEMO |
| `tests/test_app.py` | CURRENT_TEST_SUPPORT |
| `tests/test_business_workflow_ui.py` | CURRENT_TEST_SUPPORT |
| `tests/test_clients.py` | CURRENT_TEST_SUPPORT |
| `tests/test_document_names.py` | CURRENT_TEST_SUPPORT |
| `tests/test_v3_ui.py` | CURRENT_TEST_SUPPORT |

UI：`UNKNOWN=0`，`DEAD_CODE=0`。

### 8.4 Workspace benchmark（6）

`benchmark_utils.py`、`capture_environment.py`、`benchmark_rag_retrieval.py`、`benchmark_rag_incremental.py`、`benchmark_agent_workflow.py`、`build_reports.py` 均分类为 `CURRENT_BENCHMARK`。它们产生提交 `c12dfa5` 的当前性能证据，不属于产品 runtime。

## 9. Dead Code 与假活代码

确认的文件级假活代码只有两组：

1. `app/reliability/retry.py` + `tests/reliability/test_retry.py`
   - `HTTPRetrieveClient` 自己使用 `rag_retry_limit` 循环，没有调用 `RetryPolicy`。
   - `SystemRandomSource`、`Sleeper`、`AsyncioSleeper` 在整个 tracked Python 中只有定义，没有实例化/调用。
2. `app/reliability/timeout.py` + `tests/reliability/test_timeout.py`
   - HTTP timeout 直接交给 `httpx.Client(timeout=...)`；Workflow deadline 使用 `workflow_timeout_seconds` 和 BudgetLedger。
   - `TimeoutResolver` 没有正式调用。

两模块被 `app/reliability/__init__.py` 导出，因此不能单独删文件；候选风险为 `REVIEW_REQUIRED`，下一轮必须同步解除 export 和删除相应自测。

细粒度 test-only Reliability surface：`ExecutionBudget` 12 个限制字段中，正式 Workflow 只配置 `max_steps`、`max_tool_calls`、`max_duration_ms`。其余 9 个维度由 Budget 单测覆盖，但正式业务不配置；其中 `SEARCH_CALLS`、`BROWSER_ACTIONS`、`DOWNLOADS` 明显带有通用 Agent 历史语义。它们位于仍被 runtime 使用的 `budget.py` 内，不能作为文件删除候选，只能在未来代码重构中审查。

## 10. 配置审计

### RAG

- `.env.example` 中正式键均被 `RDV2Settings`、`NativeRuntimePolicy` 或 `StructuredAnswerGenerator` 读取。
- `RD_V2_ALLOW_EXTERNAL_GENERATION=false` 是当前安全默认值，不是废弃 flag。
- 未发现 competition/candidate/company/BM25/Hybrid/Reranker runtime option。
- ignored 无扩展名 `env` 不会被当前 runtime 加载，含 3 个旧 provider credential 字段；视为 `UNUSED_CONFIG` 和潜在 secret hygiene 风险。报告不记录其值。
- `.gitignore` 还保留 4 条 `erc2_set` 与 3 条 BM25/Hybrid 报告目录规则，属于 stale ignore fragment，不计入 runtime config 数量。

### Agent

- `DocumentWorkflowConfig` 的 14 个字段都被验证、参与 fingerprint 或由 Facade/Workflow/RAG Client 使用。
- `document_workflow.example.env` 中 10 个键均映射到当前配置。
- ignored `config/config.toml` 的 6 个顶层区段、19 个叶子键（llm/browser/search/mcp/runflow/daytona）均无当前代码引用。该文件可能包含本地凭据，只标记 `REVIEW_REQUIRED`。

### UI

- `DemoConfig` 的 5 个环境键均由当前 UI 使用；无 unused UI config。

## 11. 依赖审计

| 项目 | Runtime | Test/Dev/Benchmark | UNUSED | 备注 |
|---|---|---|---:|---|
| RAG | numpy、torch、transformers、python-dotenv、pydantic、faiss-cpu、fastapi、uvicorn、可选 dashscope | pytest、httpx | 0 | `dashscope` 只在显式开启 `/query` 外部生成时延迟 import。 |
| Agent | pydantic、httpx、python-docx | pytest；`pypdfium2` 仅文档 render script 使用 | 0 | `pypdfium2` 是已使用但未在 requirements 声明的开发依赖。 |
| UI | streamlit、requests | pytest 来自共享 Agent 开发环境 | 0 | 当前 requirements 中两项均使用。 |

没有发现 rank_bm25、browser/search SDK、crawler、MCP、sandbox 或竞赛专用 package 仍在正式 requirements。

## 12. 重复实现

确认 1 组结构性重复：

- Agent `HTTPRetrieveClient`（httpx）与 UI `RAGClient`（requests）分别实现 RAG HTTP envelope、timeout 和错误转换。两者当前都被使用：前者服务 Document Workflow，后者服务 RAG UI 页面，因此不应直接删除。若未来建立共享 SDK，可统一契约模型和错误映射。

以下不是重复实现：

- RAG `RetrievalScope` 与 Agent `WorkflowScope` 分属服务边界。
- Agent `EvidenceStore` 是持久化底层，`EvidenceCache` 是 task/field/query 索引层。
- Agent `CheckpointStore` 是原子文件存储，`WorkflowRepository` 是查询/列表包装层。
- RAG Trusted QA Evidence/Citation 模型与 Agent Evidence 模型分属不同服务契约。
- RAG answer generation 与 Agent field drafting 负责不同输出。

## 13. 测试审计

| 项目 | 测试文件 | 分类 | 结论 |
|---|---:|---|---|
| RAG | 4 | CURRENT_BUSINESS / INTEGRATION / REGRESSION | 全部对应当前正式能力。 |
| Agent | 8 | 2 个业务测试；4 个当前 Reliability；2 个 obsolete self-test | retry/timeout 自测不能证明它们已接入。 |
| UI | 5 | CURRENT_BUSINESS / INTEGRATION | 覆盖 Facade-only、HTTP contract、文档名、版本 UI。 |

没有发现“已删除业务但仍能运行旧业务”的 tracked 测试。`test_timeout.py` 的 Research/Web Search 示例和 `test_retry.py` 属于待清理自测；`test_errors.py` 的 Browser 文本只是通用分类 fixture，模块本身仍被 runtime 使用。

## 14. README / Docs 审计

- RAG README/docs 将 DENSE_ONLY、SECTION_PATH、版本治理、增量、scope、diff、Trusted QA 与安全默认写为当前能力，命令与现有 CLI/API 一致。
- Agent README/docs 将 Document Workflow 与 Facade 写为当前业务；OpenManus/Knowledge Research 只出现在“项目演进”。
- `demo-ui/docs/demo_ui_report.md` 是过期 sprint report：仍写 RAG 290 + Agent 286 = 576，并描述 Facade 建立前的 UI 依赖。列为 `LIKELY_REMOVABLE`。
- `demo-ui/docs/demo_script.md` 与 `v3_demo_script.md` 分别覆盖完整双项目演示和版本专项演示，内容互补。
- 两个 cleanup manifest/report 与 benchmark report 是 `GENERATED_REPORT`/历史审计证据，旧词命中不构成当前业务残留。

## 15. 数据、Artifacts 与临时文件

### RAG

- `data/rd_v2_corpus/`：94 个本地文件，当前正式语料/冻结资产，`DO_NOT_REMOVE`。
- `开发过程资料/`：3 个用户真实研发文档，`DO_NOT_REMOVE`。
- `data/synthetic_versioned_corpus/`：4 个 tracked 当前 fixture，保留。
- `output/pdf/rd_v2_demo_specification.pdf`：tracked 安全合成 Demo PDF，保留。
- `artifacts/baseline_runtime/`：36 个 ignored 旧年报 baseline 文件，当前无引用，`REVIEW_REQUIRED`。
- `data/domain_corpus/`、`domain_corpus_v0_2/`、`test_set/`：共 235 个旧语料/索引/中间产物，当前无引用，`REVIEW_REQUIRED`。
- 11 个旧实验 report 目录：78 个文件，`LIKELY_REMOVABLE`。
- `tmp/`：14 个 PNG；`运行情况.txt`：1 个终端记录；均 `SAFE_TO_REMOVE`。
- `src/evaluation/__pycache__` 与 `src/versioning/__pycache__` 共有 28 个无源码 `.pyc`，属于生成残留，不能证明历史模块仍是 runtime。

### Agent

- `workspace/uv-cache` 55,100 个文件、`workspace/python` 3,443 个文件：受保护本地依赖环境，本轮不列入候选。
- `workspace/candidate_knowledge` 11、`research_requests` 1、`research_runs` 22、根部通用示例 4：共 38 个 Legacy 数据文件，均 `REVIEW_REQUIRED`。
- `logs/` 257 个文件和 `.tmp_phase1b/` 5 个文件：`SAFE_TO_REMOVE`。
- `runtime/post_rag_cleanup_integration` 6 个当前集成输出，不是 Legacy；保留。

### UI

- `runtime/` 17 个生成文件，包括 upload/output/smoke。由于可能含用户上传文档，统一标为 `REVIEW_REQUIRED`，不自动清理。

## 16. Root Directory Hygiene

RAG 根目录正式 tracked 文件已经简洁，但本地仍出现 ignored `artifacts`、旧 data/report、`tmp`、`运行情况.txt`、旧 `env`，以及空 `candidate_knowledge/`、`examples/` 目录。评价为 `ACCEPTABLE`。

Agent 根目录正式 Python 已集中到 `app/document_workflow` 与必要 Reliability，但仍有嵌套上游 `.github`、旧 config、257 个 logs、1.91 GB workspace、Phase 1B 临时目录和空 `cases/`。评价为 `POOR`。

UI 根目录结构清楚，生成物放在 ignored `runtime/`。评价为 `GOOD`。

## 17. 包命名

- RAG package：`enterprise-rd-document-rag`，干净。
- Agent package：`evidence-document-workflow-agent`，干净。
- Agent 文件夹仍叫 `OpenManus-rag`，README 保留历史说明；这是最明显的旧语义，但本轮只报告、不重命名。
- tracked Agent issue/workflow/Code of Conduct 仍引用 `FoundationAgents/OpenManus`；已进入 manifest。
- 没有 package/module 名仍包含 competition、erc2、annual_report 或 candidate。

## 18. API 审计

RAG 共 7 个 API，全部为 `CURRENT`：

| Method | Path | 分类 |
|---|---|---|
| GET | `/health` | CURRENT |
| GET | `/artifacts/status` | CURRENT |
| POST | `/query` | CURRENT |
| POST | `/retrieve` | CURRENT |
| GET | `/documents` | CURRENT |
| GET | `/documents/{document_id}/versions` | CURRENT |
| GET | `/documents/{document_id}/diff` | CURRENT |

`LEGACY=0`、`DEBUG=0`、`UNUSED=0`。没有 competition/candidate/company endpoint。

## 19. Facade 与跨项目边界

- CLI：只从 `app.document_workflow` package public export 导入 `DocumentWorkflowFacade`。
- UI：`AgentClient` 只导入 `DocumentWorkflowFacade`，不访问 Checkpoint filesystem、EvidenceCache、Repository 或 Workflow internals。
- Agent：没有 `src.*`、`rd_v2_runtime`、`document_lifecycle` 或 RAG 项目路径 import；只通过 HTTP `/retrieve` 和 `/documents` 调用 RAG。
- UI RAG 页面：只通过 HTTP Client 调 RAG public API，不读 RAG Python internals。

## 20. 候选 Manifest

`cleanup_candidate_manifest.json` 精确列出当前存在的 1,024 个文件，不包含 `.venv`、`workspace/uv-cache`、`workspace/python`、当前 `rd_v2_corpus`、用户 `开发过程资料` 或 Agent 当前 integration runtime。

| Risk | 文件数 |
|---|---:|
| SAFE_TO_REMOVE | 607 |
| LIKELY_REMOVABLE | 79 |
| REVIEW_REQUIRED | 338 |

按类别：596 Generated Data、314 Legacy Data、78 Historical Experiment、17 Local Runtime Data、6 Legacy Business metadata、6 Repository Metadata、2 Dead Code、2 Obsolete Test、2 Unused Config、1 Stale Doc。

`SAFE_TO_REMOVE` 的大头是 cache、logs、临时页面和已删除业务的 Phase 1B 临时输出；`REVIEW_REQUIRED` 的大头是可能含用户/业务内容的旧语料与 workspace 数据。该 manifest 本轮未执行。

## 21. 是否值得继续删除

值得，但应分两轮：

1. 先处理 manifest 中 `SAFE_TO_REMOVE` 的生成物和明确上游元数据，并决定是否保留 79 个旧实验报告。
2. 再单独审查 338 个数据/配置/代码候选。尤其是旧语料、workspace、credential 文件，以及 retry/timeout 的 export 依赖，不能只按数量删除。

正式 RAG 业务代码不需要继续大规模删除。Agent 只需要一次小范围、可验证的 Reliability 收口。当前最大的债务是 ignored 本地数据和仓库元数据，不是主业务实现。

## 22. 最终验收字段

```text
============================
RAG
============================

RAG_BUSINESS_SCOPE_SINGLE = YES
OLD_ANNUAL_REPORT_FILES_REMAIN = YES
COMPETITION_RUNTIME_REMAINS = NO
LEGACY_COMPANY_REMAINS = NO
CANDIDATE_CODE_REMAINS = NO
BM25_RUNTIME_REMAINS = NO
HYBRID_RUNTIME_REMAINS = NO
RERANKER_RUNTIME_REMAINS = NO
HISTORICAL_EXPERIMENT_CODE_REMAINS = YES
UNUSED_RAG_MODULES = 0
UNUSED_RAG_DEPENDENCIES = 0
UNUSED_RAG_CONFIGS = 3
UNTRACKED_LEGACY_RAG_DATA = YES

Notes:
- OLD_ANNUAL_REPORT_FILES_REMAIN 和 UNTRACKED_LEGACY_RAG_DATA 指 ignored 本地 baseline/test-set，不是 tracked runtime。
- HISTORICAL_EXPERIMENT_CODE_REMAINS 仅指 28 个 ignored orphan .pyc；历史 .py 源码不存在。
- UNUSED_RAG_CONFIGS 指 ignored `env` 的 3 个旧 provider key；正式 `.env.example` 为 0 unused。

============================
AGENT
============================

AGENT_BUSINESS_SCOPE_SINGLE = YES
RESEARCH_AGENT_REMAINS = NO
BROWSER_CODE_REMAINS = NO
CANDIDATE_CODE_REMAINS = NO
SANDBOX_CODE_REMAINS = NO
MCP_BUSINESS_REMAINS = NO
GENERAL_AGENT_RUNTIME_REMAINS = NO
IMPLEMENTED_BUT_UNUSED_RELIABILITY = 2
UNUSED_AGENT_MODULES = 2
UNUSED_AGENT_DEPENDENCIES = 0
UNUSED_AGENT_CONFIGS = 19

Notes:
- Research/Candidate 仍有 ignored 数据，但无 tracked source/runtime。
- UNUSED_AGENT_CONFIGS 指 ignored `config.toml` 的 19 个叶子键；正式 DocumentWorkflowConfig 为 0 unused。

============================
INTEGRATION
============================

AGENT_DIRECT_RAG_SOURCE_IMPORT = NO
UI_DIRECT_RAG_INTERNAL_ACCESS = NO
UI_DIRECT_AGENT_INTERNAL_ACCESS = NO
DUPLICATE_BUSINESS_IMPLEMENTATIONS = 1
SAFE_TO_REMOVE_FILES = 607
LIKELY_REMOVABLE_FILES = 79
REVIEW_REQUIRED_FILES = 338
CURRENT_BUSINESS_CODE_MODIFIED = NO
FILES_DELETED = 0
```

## 23. 最终评价

### RAG

```text
BUSINESS_PURITY = MEDIUM
LAYERING = CLEAR
LEGACY_DEBT = MEDIUM
DEAD_CODE_DEBT = LOW
REPOSITORY_HYGIENE = ACCEPTABLE
```

正式 tracked Runtime 的业务纯度实际为 HIGH；总评降为 MEDIUM，是因为当前本机 ignored 区仍保留能明确识别旧年报与旧实验阶段的文件。

### Agent

```text
BUSINESS_PURITY = MEDIUM
LAYERING = CLEAR
LEGACY_DEBT = MEDIUM
DEAD_CODE_DEBT = MEDIUM
REPOSITORY_HYGIENE = POOR
```

Facade、Workflow 与 RAG HTTP 边界清楚；总评受两个假活 Reliability 模块、嵌套 OpenManus metadata、旧 config、Research/Candidate workspace 和大量日志影响。

## 24. 本轮变更声明

本轮只新增：

- `project_delivery/final_residual_audit/final_residual_audit_report.md`
- `project_delivery/final_residual_audit/cleanup_candidate_manifest.json`
- `project_delivery/final_residual_audit/retained_module_justification.md`

没有执行 `rm`、`git rm`、文件移动、格式化、重命名、依赖变更、业务代码/README/config 修改或测试运行。
