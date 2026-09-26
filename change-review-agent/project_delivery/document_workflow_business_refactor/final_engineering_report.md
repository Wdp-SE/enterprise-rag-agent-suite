# Document Workflow Agent Business-Focused Refactoring 最终工程报告

生成日期：2026-09-18

## 1. 最终结论

`OpenManus-rag` 已收敛为单一业务产品：**基于 RAG 的企业研发文档起草与审核工作流 Agent**（Evidence-driven Document Workflow Agent）。产品入口只保留结构化 Word 模板解析、受控检索、Evidence 充分性判断、字段草稿、MISSING、Freshness/Integrity、单审核人 Review、Approved DOCX、Checkpoint/Resume。

本轮没有修改 `RAG-Challenge-2-main` Retrieval Core。相对删除前恢复点，该目录 diff 为 0。没有执行 `git push`、GitHub publish 或远程 release。

## 2. 删除前安全措施与恢复方式

- 删除前全部有效修改已保存到本地 Git 提交：`ab984fbff30542d512c5ee1f3de66c430c7ccac5`。
- 本地恢复标签：`backup/pre-legacy-removal-20260918`。
- 恢复命令示例：`git restore --source backup/pre-legacy-removal-20260918 -- OpenManus-rag`。如需整体回到恢复点，应先保存当前工作区，再由人工决定采用 branch、restore 或 reset。
- 删除前清单 SHA-256：`2A628D5601B07147435DADAD9C99952A3D4F399D16CFE88234870B183378D123`。
- 清单路径数 506，按 78 个目标现场重新枚举 506，集合差异 0，缺失 0，受保护路径命中 0。
- 保留代码对 `app.research`、旧 Agent/Tool/Sandbox/Flow/MCP/A2A、已删除 Reliability 模块的 import 引用为 0。

## 3. 实际删除结果

- 实际永久删除文件：**506**。
- 清单删除后残留：**0**。
- 清单内保留例外：**0**。
- Git 跟踪文件删除：266；其余为清单内缓存、生成物或未跟踪 Legacy 文件。
- 删除 Python 代码行：**23,989**。该数字仅作工程规模记录，不作为质量指标。
- Git 跟踪文本总删除行约 43,931，包含前端静态资源、文档、配置和锁文件，不等同于 Python 代码行。

删除的旧业务模块包括：

- Knowledge Research、Browser/Web Search、Source Discovery/Selection/Acquisition、Raw Source Archive。
- Candidate Package/Builder/Validator、旧 RAG Candidate Importer、Knowledge Draft Tool。
- 通用 OpenManus Agent、ReAct、ToolCall、Browser、MCP、Sandbox、Flow、Prompt、通用 Tool 集合、A2A 协议入口。
- 只服务旧执行器的 Reliability executor/policy/result/workflow_control。
- 旧 Research/Sandbox/Candidate/Document Workflow V2 测试、配置、Demo、文档和交付物。
- 旧 `main.py`、`run_research.py`、`run_flow.py`、`run_mcp*.py`、`sandbox_main.py` 等产品入口。
- 旧模型供应商示例配置、Research policy/profile、MCP 示例配置和旧依赖。

公共能力迁移与解耦：

- Evidence contract 从旧 Research 语义中抽出到 `app/document_workflow/evidence_models.py`。
- Evidence 持久化移入 `app/document_workflow/evidence_store.py`。
- Reliability 错误模型解除对旧 `app.exceptions` 和 Sandbox 的依赖。
- UI/CLI 统一切换到 `DocumentWorkflowFacade`，再删除旧业务模块。

## 4. 明确保留且未被删除的内容

- `.git` 及全部 Git 历史。
- `RAG-Challenge-2-main` Core 与 V3 生命周期成果。
- 用户 `OpenManus-rag/config/config.toml`。
- 本地 `OpenManus-rag/workspace`。
- 当前 `app/document_workflow` 新业务代码。
- 当前旗舰模板、安全 E2E、E2E 产物、最终工程报告与用户业务数据。
- Streamlit 的 RAG 知识底座 Tab 和 Document Workflow Agent Tab。

## 5. 最终核心目录

```text
OpenManus-rag/
├── app/
│   ├── document_workflow/
│   │   ├── facade.py
│   │   ├── workflow.py
│   │   ├── scope.py
│   │   ├── models.py
│   │   ├── planning.py
│   │   ├── rag.py
│   │   ├── evidence_models.py
│   │   ├── evidence_store.py
│   │   ├── evidence.py
│   │   ├── sufficiency.py
│   │   ├── drafting.py
│   │   ├── freshness.py
│   │   ├── integrity.py
│   │   ├── template.py
│   │   ├── review.py
│   │   ├── repository.py
│   │   ├── state.py
│   │   ├── policy.py
│   │   └── configuration.py
│   └── reliability/
│       ├── budget.py
│       ├── errors.py
│       ├── progress.py
│       ├── retry.py
│       ├── timeout.py
│       └── trace.py
├── scripts/
│   ├── create_flagship_template.py
│   └── run_business_e2e.py
├── tests/
│   ├── document_workflow/
│   └── reliability/
├── run_document_workflow.py
├── requirements.txt
└── README.md

demo-ui/
├── app.py
├── services/agent_client.py
├── components/workflow_view.py
└── tests/
```

最终保留 39 个 Python 文件、6,543 行，覆盖业务实现、可靠性、脚本和测试。

## 6. 真实依赖边界

- **UI 边界**：`demo-ui/services/agent_client.py` 只导入 `DocumentWorkflowFacade`；UI 不直接访问 Evidence cache、Checkpoint 文件、FAISS 或内部 WorkflowState。
- **Facade 边界**：`facade.py` 协调 Workflow runner、Repository、Review 和 Finalization，不承担模板解析或检索实现。
- **RAG 边界**：`rag.py` 定义 retrieval client；WorkflowScope 随每次 `/retrieve` 请求传递。Planning/Drafting 不直接发 HTTP。
- **LLM 边界**：`drafting.py` 的 `FieldDraftingService` 默认 EXTRACTIVE；GENERATIVE 通过可注入 backend，且只允许 public/synthetic/approved-redacted 或明确本地模型数据策略。
- **Persistence 边界**：`repository.py` 管理 workflow 列表与摘要；`state.py` 管理 checkpoint/scope fingerprint；`evidence_store.py` 管理 Evidence 原子持久化。
- **Review 边界**：`review.py` 保存 reviewer、时间、comment、draft hash、approved content hash 与编辑内容；`integrity.py` 在正式输出前 fail closed。

这里的 Scope 是业务检索范围隔离，不是 ACL/RBAC；Review 是 Single Reviewer MVP，不是企业 OA；Evidence-grounded Draft 不声明 zero hallucination。

## 7. 核心业务闭环

- WorkflowScope 在创建时冻结，进入 state、RAG 请求、Evidence、Trace 和 Checkpoint；Resume 校验 fingerprint，禁止静默换 Scope。
- QueryPlanner 每 Field 生成 1 个 primary query，最多 2 个 fallback query。
- EvidenceSufficiency 输出 SUFFICIENT / INSUFFICIENT / MISSING。
- FieldDraftingService 支持 EXTRACTIVE 与受数据策略约束的 GENERATIVE；多条 Evidence 可共同形成字段草稿。
- 无证据为 MISSING，Evidence 不足为 INSUFFICIENT_EVIDENCE；未知或越界 Evidence ID 阻断 Finalization。
- Word parser 支持 Heading/标题 1/2/3、outline level、paragraph、table、placeholder；替换保留目标 Run 的粗体、斜体等格式。
- 正文使用编号引用，文末 Citation Appendix 输出真实 Evidence metadata。
- Draft 可下载；只有所有 required section 均 APPROVED 且 Integrity guard 通过，才生成 Approved DOCX。
- ACTIVE Scope 下 superseded Evidence 变为 STALE；Resume 只刷新受影响 SectionTask。

## 8. 最终验证结果

- Python compileall：PASS。
- Facade/Scope/Retry/Timeout import check：PASS。
- Agent Core + Reliability：**112 passed / 0 failed**。
- Streamlit UI：**12 passed / 0 failed**。
- Safe Business E2E：PASS；`safe_end_to_end=true`。
- Multi Evidence Draft：PASS。
- 至少一个 MISSING 且 fail closed：PASS。
- Section APPROVE、EDIT + APPROVE、REJECT：PASS。
- Required section REJECTED 时 Official Output 阻断：PASS。
- 全部批准后 `approved.docx` 生成：PASS。
- Checkpoint/Resume 保持 Scope、跳过已完成 Section：PASS。
- STALE Evidence 只刷新受影响 Section：PASS。
- Word run formatting 和 Citation Appendix：PASS。
- Streamlit Live Smoke：健康端点 `200 / ok`，首页 `200` 且返回 Streamlit 页面；测试服务已关闭。
- CLI `--help`：PASS。
- `pip check`：PASS，No broken requirements found。
- `git diff --check`：PASS。
- 本轮相对恢复点的 RAG Core diff：0。

pytest 的唯一非失败提示为环境中的 `pytest-asyncio` future-default deprecation warning，以及 UI 测试缓存目录无法写入的 cache warning；测试本身全部通过。

## 9. 最终验收矩阵

```text
BUSINESS_SCOPE_SINGLE = YES
DOCUMENT_WORKFLOW_ONLY = YES
LEGACY_KNOWLEDGE_RESEARCH_REMOVED = YES
LEGACY_BROWSER_RESEARCH_REMOVED = YES
LEGACY_SOURCE_ACQUISITION_REMOVED = YES
LEGACY_CANDIDATE_PACKAGE_REMOVED = YES
LEGACY_RAG_IMPORTER_REMOVED = YES
UNUSED_LEGACY_CONFIG_REMOVED = YES
UNUSED_LEGACY_DEPENDENCIES_REMOVED = YES
UNUSED_LEGACY_TESTS_REMOVED = YES
UNUSED_LEGACY_DOCS_REMOVED = YES
DOCUMENT_WORKFLOW_FACADE = PASS
UI_INTERNAL_COUPLING = LOW
RAG_BOUNDARY_CLEAR = YES
LLM_BOUNDARY_CLEAR = YES
PERSISTENCE_BOUNDARY_CLEAR = YES
WORKFLOW_SCOPE_READY = YES
SCOPE_CHECKPOINTED = YES
SCOPE_RESUME_VALIDATED = YES
QUERY_PLANNER_READY = YES
FIELD_DRAFTING_SERVICE = PASS
MULTI_EVIDENCE_DRAFT = PASS
MISSING_FAIL_CLOSED = PASS
EVIDENCE_SUFFICIENCY = PASS
EVIDENCE_FRESHNESS = PASS
HUMAN_REVIEW_LOOP = PASS
SECTION_EDIT_REVIEW = PASS
SECTION_APPROVE = PASS
SECTION_REJECT = PASS
OFFICIAL_OUTPUT_GUARDED = PASS
CHECKPOINT_RESUME = PASS
STALE_EVIDENCE_LOCAL_REFRESH = PASS
WORD_FORMAT_PRESERVATION = PASS
CITATION_APPENDIX = PASS
SAFE_END_TO_END = PASS
UI_SMOKE = PASS
RAG_CORE_UNCHANGED = YES
CURRENT_RELEVANT_TEST_RESULT = 124 passed / 0 failed (Agent/Reliability 112 + UI 12)
REMOVED_FILES_COUNT = 506
REMOVED_CODE_LINES = 23989
FINAL_CORE_MODULES = DocumentWorkflowFacade, WorkflowScope, Template Parser/Renderer, SectionTask/FieldTask Planning, QueryPlanner, RAG Retrieval Boundary, Evidence Store/Cache/Sufficiency/Freshness, FieldDraftingService, Integrity, Review, Repository, Checkpoint/Resume, Reliability
REMOVED_LEGACY_MODULES = Knowledge Research, Browser/Web Search, Source Acquisition, Candidate Package, RAG Importer, General Agent/ReAct/ToolCall, Sandbox, MCP, A2A, legacy Flow/Prompt/Tool, legacy configs/tests/docs/entrypoints
READY_FOR_RESUME = YES
READY_FOR_INTERVIEW = YES
READY_FOR_DEMO = YES
PRODUCTION_READY = NO CLAIM
```

## 10. 已知边界

- 当前审核流为单审核人 MVP，没有 SSO、RBAC、多人会签或流程设计器。
- Scope 只约束业务检索范围，不能替代企业权限系统。
- GENERATIVE 模式依赖配置的 backend；未满足数据安全策略时会拒绝调用。
- 当前测试证明约定范围内的格式保持，不等于支持任意复杂 Word 文档。
- 本轮完成后停止增加新 Agent、Browser、Web Search、Multi-Agent 或新业务场景。
