# Retained Module Justification

本文件记录“名称或位置看起来像旧代码，但当前不应删除”的模块和数据，防止下一轮只按关键词或文件数量误删。

## RAG Runtime

| 路径 | 保留理由 |
|---|---|
| `RAG-Challenge-2-main/src/answer_generation.py` | `/query` 的正式结构化生成边界。默认关闭外部生成属于安全策略，不代表模块废弃。 |
| `RAG-Challenge-2-main/src/artifact_lifecycle.py` | Runtime 校验冻结资产状态和 SHA；artifact builder 与测试也使用。 |
| `RAG-Challenge-2-main/src/context_expansion.py` | 当前 SECTION_PATH 上下文扩展。代码中移除 `rrf_score` 等字段是兼容/防泄漏 guard，不是 RRF 实现。 |
| `RAG-Challenge-2-main/src/document_lifecycle.py` | 唯一 Document/DocumentVersion、ACTIVE/SUPERSEDED、增量、scope、diff 实现。 |
| `RAG-Challenge-2-main/src/local_embedding_worker.py` | 当前本地 embedding 进程隔离，由 `rd_v2_runtime` 启动。 |
| `RAG-Challenge-2-main/src/native_runtime.py` | 当前 Torch thread、MKLDNN 和向量批次约束。 |
| `RAG-Challenge-2-main/src/rd_v2_api.py` | 唯一 Web API。 |
| `RAG-Challenge-2-main/src/rd_v2_runtime.py` | 唯一 DENSE_ONLY + SECTION_PATH 查询 Runtime。对 Hybrid/Reranker flag 的读取只用于 fail-closed 拒绝旧资产。 |
| `RAG-Challenge-2-main/src/trusted_qa/*` | `/query` 的证据充分性、Citation audit、enforcement 与 trace。不是旧 candidate workflow。 |
| `RAG-Challenge-2-main/main.py` | 正式 serve、artifact validation、ingest/activate/diff/catalog CLI。 |
| `RAG-Challenge-2-main/scripts/build_rd_v2_final_artifact_manifest.py` | 正式资产构建/校验工具；写入 Hybrid/Reranker=false 是固定策略声明。 |
| `RAG-Challenge-2-main/scripts/run_v3_scope_benchmark.py` | 当前 scope benchmark，不是旧实验 runner。 |
| `RAG-Challenge-2-main/scripts/run_v3_versioned_e2e.py` | 当前 version lifecycle E2E。 |
| `RAG-Challenge-2-main/scripts/run_rd_v2_offline_runtime_smoke.py` | 当前离线 Runtime smoke。 |
| `RAG-Challenge-2-main/scripts/validate_retrieve_api.py` | 当前 `/retrieve` 契约验证。 |

## RAG Data / Reports

| 路径 | 保留理由 |
|---|---|
| `RAG-Challenge-2-main/data/rd_v2_corpus/` | 当前本地正式语料、规范化结果、manifest 与冻结检索资产；包含用户业务数据，不得按 ignored 状态删除。 |
| `RAG-Challenge-2-main/开发过程资料/` | 用户真实研发文档，属于当前业务输入；受保护。 |
| `RAG-Challenge-2-main/data/synthetic_versioned_corpus/` | 当前版本治理 E2E 的公开合成 fixture。 |
| `RAG-Challenge-2-main/output/pdf/rd_v2_demo_specification.pdf` | 当前安全 Demo PDF，可用于展示 PDF/结构化检索输入；不是 dummy business data。 |
| `RAG-Challenge-2-main/reports/v3_scope_benchmark.json` | 当前 scope benchmark 证据。与 post-cleanup 文件 hash 不同，不是字节重复。 |
| `RAG-Challenge-2-main/reports/v3_versioned_e2e_run/` | 当前 V3 生命周期验证证据。 |
| `RAG-Challenge-2-main/project_delivery/rag_business_cleanup/` | 已执行 302 文件清理的审计链和恢复依据。旧关键词出现在历史 manifest 中是预期的。 |
| `project_delivery/rag_v3_lifecycle/` | 当前生命周期增强工程报告。 |
| `project_delivery/performance_benchmark/` | 当前可复现的 RAG/Agent 性能方法、脚本、fixture 与测量结果。 |

## Agent Document Workflow

| 路径 | 保留理由 |
|---|---|
| `OpenManus-rag/app/document_workflow/facade.py` | CLI/UI 的唯一稳定业务入口。 |
| `OpenManus-rag/app/document_workflow/workflow.py` | 当前编排器，实际调用 Scope、RAG、Evidence、Sufficiency、Draft、Freshness、Budget、Progress、Trace。 |
| `OpenManus-rag/app/document_workflow/evidence_models.py` | Agent 自有 Evidence contract；不能用 RAG 内部模型替换，否则破坏 HTTP 边界。 |
| `OpenManus-rag/app/document_workflow/evidence_store.py` | Evidence 的持久化底层。 |
| `OpenManus-rag/app/document_workflow/evidence.py` | 在 EvidenceStore 之上的 task/field/query cache 与 freshness 索引；不是重复实现。 |
| `OpenManus-rag/app/document_workflow/state.py` | Checkpoint 原子读写与状态 schema。 |
| `OpenManus-rag/app/document_workflow/repository.py` | Workflow list/get repository；包装 CheckpointStore，不是第二套 checkpoint。 |
| `OpenManus-rag/app/document_workflow/rag.py` | Agent 的 RAG HTTP 边界、scope contract、DemoRAG 测试替身与 RAGTool。 |
| `OpenManus-rag/app/document_workflow/drafting.py` | EXTRACTIVE 和受数据分类约束的 GENERATIVE drafting。`GenerativeDraftingBackend` 是注入协议。 |
| `OpenManus-rag/app/document_workflow/template.py` | 唯一 Word Template Parser/Renderer。 |
| `OpenManus-rag/app/document_workflow/review.py` | 人工审核与正式输出门禁。 |
| `OpenManus-rag/app/document_workflow/freshness.py` | Resume 时判断 Evidence 版本新鲜度。 |
| `OpenManus-rag/app/document_workflow/integrity.py` | 输出完整性和审核一致性校验。 |
| `OpenManus-rag/app/reliability/budget.py` | Workflow 实际使用 BudgetLedger；不能因为含通用 test-only 维度而删整文件。 |
| `OpenManus-rag/app/reliability/progress.py` | Workflow 实际使用 NoProgressDetector。 |
| `OpenManus-rag/app/reliability/trace.py` | Workflow 实际写 trace；TraceRecorderProtocol 是当前类型边界。 |
| `OpenManus-rag/app/reliability/errors.py` | Budget/Trace 的结构化错误与 sanitizer；Browser 测试文本不等于 Browser runtime。 |
| `OpenManus-rag/app/reliability/__init__.py` | 仍承载四个当前 Reliability 模块的 public export。若未来移除 retry/timeout，只编辑相应 export，不删整个 package init。 |
| `OpenManus-rag/run_document_workflow.py` | 正式 CLI，只通过 Facade。 |
| `OpenManus-rag/scripts/create_flagship_template.py` | 当前旗舰 DOCX 模板生成工具。 |
| `OpenManus-rag/scripts/render_word_pdf_pages.py` 与 `render_document_demo_with_word.ps1` | 当前 DOCX 视觉 QA 工具链。 |
| `OpenManus-rag/scripts/run_business_e2e.py` | 当前 Safe Business E2E。 |

## Agent Repository / Runtime Data

| 路径 | 保留理由 |
|---|---|
| `OpenManus-rag/.gitattributes` | 对 DOCX/PDF/binary 与行尾有实际作用。 |
| `OpenManus-rag/.pre-commit-config.yaml` | 从 Agent 子目录手动执行 pre-commit 时可用；不是上游业务代码。 |
| `OpenManus-rag/LICENSE` | 开源/上游许可依据，不应因品牌收口删除。 |
| `OpenManus-rag/config/document_workflow.example.env` | 当前正式环境变量模板。 |
| `OpenManus-rag/project_delivery/document_workflow_business_refactor/` | 506 文件清理、当前模板和 Safe E2E 的交付证据。 |
| `OpenManus-rag/runtime/post_rag_cleanup_integration/` | 当前 RAG 清理后的集成验证输出，不是 Research/Candidate legacy。 |
| `OpenManus-rag/workspace/uv-cache/` 与 `workspace/python/` | 本地依赖/runtime cache；虽不属于业务，但属于受保护 local workspace，本轮不得删除。 |

## UI

| 路径 | 保留理由 |
|---|---|
| `demo-ui/services/agent_client.py` | 只依赖 `DocumentWorkflowFacade`，是正确 UI→Agent 边界。 |
| `demo-ui/services/rag_client.py` | RAG 页面需要独立 HTTP client；与 Agent client 有结构重复，但两个调用方都实际使用。 |
| `demo-ui/config.py` | 当前安全数据门禁、文档显示名和本地路径配置。 |
| `demo-ui/components/*` | 当前 Streamlit 页面渲染，无旧 business component。 |
| `demo-ui/docs/demo_script.md` | 完整双项目四分钟演示。 |
| `demo-ui/docs/v3_demo_script.md` | 版本治理专项五分钟演示；与前者互补。 |
| `demo-ui/runtime/` | 当前生成数据；可清理但可能包含用户上传，必须先按 run 审查。 |

## 不应误删的历史说明

以下历史内容可以保留，因为它们明确标为演进/审计证据，没有把旧业务宣传为当前能力：

- RAG/Agent README 的业务边界与项目演进段落。
- 两次 legacy cleanup 的 manifest、计划、执行记录和 final engineering report。
- 当前 performance benchmark 的方法、环境、JSON 与 Markdown 结果。

关键词命中本身不是删除依据；只有在 runtime、tests、benchmark、demo、docs 和动态加载交叉检查均无当前用途后，才进入 `cleanup_candidate_manifest.json`。
