# V4 只读影响分析

## 结论

V4 可以作为 V3 上的受控增量实现，不需要改写冻结的 Dense 检索、Trusted QA、现有 Document Workflow 或 Streamlit 技术栈。最小可行边界是：RAG 新增企业配置、EngineeringItem、TraceLink、Item Diff、Exact Identifier 与候选版本服务；Agent 新增变更影响工作流并复用现有 HTTP、Evidence、Freshness、Checkpoint 原子写入、单审核人和 DOCX 能力；UI 新增一个独立页签。

当前开发分支为 `feature/change-impact-review`。V4 不处理任何仓库清理候选，也不触碰本地 ignored 目录、受保护 DOCX、面试文档或 `CODE_OF_CONDUCT.md`。

## 15 项影响分析

### 1. Document / DocumentVersion

位置：`RAG-Challenge-2-main/src/document_lifecycle.py`。

`Document`、`DocumentVersion`、`DocumentCatalog` 已提供稳定文档身份、ACTIVE/SUPERSEDED 版本状态、前序版本和目录校验。V4 不复制 Version 模型。`organization_id` 保留在新的 EngineeringItem 和 OrganizationProfile 中作为业务归属字段；首版不把它加入现有目录 schema，避免破坏冻结 Artifact 兼容性，也不将其解释为多租户隔离。

### 2. Section / Citation / Evidence

- Section：`SectionSnapshot` 位于 `RAG-Challenge-2-main/src/document_lifecycle.py`。
- Citation：问答来源和引用审计位于 `src/rd_v2_api.py`、`src/answer_generation.py`、`src/trusted_qa/`。
- Agent Evidence：`OpenManus-rag/app/document_workflow/evidence_models.py`，稳定身份包含内容哈希、版本、页码、章节和来源。

V4 Patch 直接引用既有 `Evidence.evidence_id`，不新建第二套 Evidence/Citation 模型。

### 3. Version Diff

`compare_section_versions()` 和 `DocumentCatalog.diff()` 已实现按 Section Path 对齐的确定性 ADDED/MODIFIED/REMOVED/UNCHANGED。V4 新增的是同样确定性的 EngineeringItem Diff，以稳定的 `external_identifier` 对齐；不修改原 Section Diff。

### 4. Scope Retrieval

`RetrievalScope`、`DocumentCatalog.matches()`、`RDV2DenseRetriever.retrieve()` 已在排序前执行 project/document/type/version/active 范围过滤。V4 Exact Identifier Retrieval 必须先应用同样的业务归属和版本范围，再进行编号精确匹配；正式 Dense 路径保持原样。

### 5. Agent Workflow

`OpenManus-rag/app/document_workflow/workflow.py` 负责现有模板解析、任务计划、RAG Evidence、起草、选择性刷新与停止条件；`facade.py` 是 UI/CLI 稳定入口。V4 增加独立的 change-impact 工作流状态机，沿用 facade 分层思想，但不把 Patch 状态强塞进原模板字段流程。

### 6. Human Review

`review.py` 已实现单审核人、APPROVED/REJECTED、人工编辑后哈希和最终完整审批检查。V4 保持相同的单审核人和 fail-closed 规则，并为每条 Patch 记录 APPROVE/EDIT/REJECT；EDIT 后必须再次确认才可应用。原 Section Review 不改语义。

### 7. Checkpoint / Resume

`state.py` 的 `CheckpointStore` 使用同目录临时文件、`fsync` 和 `os.replace` 原子提交，并校验 schema 与身份。V4 复用这套原子存储实现，扩展为受 schema 约束的变更任务 payload；不引入数据库或第二套非原子持久化。

### 8. Freshness

`freshness.py` 的 `EvidenceFreshnessValidator` 根据当前 ACTIVE version 与显式历史范围判断 FRESH/STALE/UNKNOWN。V4 继续使用该验证器，并在应用 Patch 前额外核对 Scope Fingerprint、Evidence Content Hash、Target Anchor 和 Original Content Hash。失效只阻断依赖该 Evidence 的 Patch。

### 9. DOCX 生成 / 修改

`template.py` 已支持 DOCX Heading、Paragraph、Table、跨 Run 文本替换和输出文件不覆盖输入文件。V4 新增受限的 `REPLACE_PARAGRAPH` 写入器：只允许唯一 anchor、原文哈希匹配和输出到 Candidate 文件。图片、流程图、复杂表格和任意 OOXML 不自动修改。

### 10. UI 如何调用 RAG / Agent

`demo-ui/services/rag_client.py` 是 RAG HTTP 薄客户端；`services/agent_client.py` 只经 Agent facade；`app.py` 组织 RAG 与 Document Workflow 页签。V4 增加一个“工程变更审核工作台”页签，通过 Agent facade 发起任务；Agent 继续经既有 RAG HTTP 客户端边界调用 RAG，不读取 FAISS。

### 11. EngineeringItem 的位置

放在 RAG 新增的 `src/engineering_change/` 包。它属于“资料里有什么”，模型保持跨企业稳定，企业编号只在 adapter 中解析为 `external_identifier`。

### 12. TraceLink 的位置

与 EngineeringItem 同属 RAG `src/engineering_change/`。TraceLink 明确保存 `provenance=EXPLICIT|SEMANTIC` 和 `status=CONFIRMED|SUGGESTED|REJECTED`，服务层禁止将 SEMANTIC/SUGGESTED 自动升级。

### 13. PatchCandidate 的位置

放在 Agent 新增的 `app/change_impact_review/` 包。Patch 是“接下来做什么”，包含 base version、唯一 paragraph anchor、原文与哈希、建议文本、Evidence、Review 和应用状态。

### 14. 可完全复用的能力

- RAG：Document/Version/Section、Section Diff、VersionLifecycleService、Embedding Reuse、Scope、Dense baseline、FastAPI、目录最后提交的安全激活。
- Agent：HTTP RAG 边界、Evidence 模型与稳定身份、Freshness、原子 checkpoint、单审核人规则、DOCX 读取/写出、结构化 trace、facade 分层。
- UI：现有配置、状态展示、中文组件风格和 Streamlit 测试方式。

### 15. 必须新增而非重构的能力

- `OrganizationProfile` 与 `IdentifierExtractor`；
- `EngineeringItem`、Item Diff、TraceLink；
- Scope 之后的 Exact Identifier Retrieval；
- Confirmed Trace 与 Suggested Impact 分流；
- `ChangeTask`、`ImpactCandidate`、`PatchCandidate`；
- 段落级冲突检查、Patch 幂等键、Patch 审核记录；
- Candidate Version 构建状态与失败原因；
- V4 工作台和固定评测集。

这些能力以新增小模块接入，冻结的 V3 正式 Dense/Trusted QA 路径不被替换。

## 关键设计调整

1. 不让 V4 直接修改冻结年度 RAG Artifact。V4 的合成演示使用现有 `VersionLifecycleService` 建立独立版本存储，通过同一个 FastAPI 应用暴露受控工程接口；这保留了现有正式问答稳定性，又真实复用了版本治理、增量向量和安全激活。
2. Candidate 构建调用 `ingest_version(..., activate=False)`，完成 DOCX、Section、Embedding、Index 和业务校验后再调用 `activate_version()`。现有目录最后原子提交保证失败前 ACTIVE 版本不丢失。
3. Exact Identifier 是 V4 工程接口中的前置检索器；Dense baseline 仍是 V3 正式策略。固定评测未证明净收益前，不引入 BM25/RRF。
4. 第二企业仅提供 OrganizationProfile 与输入夹具测试，不新增 UI、Pipeline、数据库或 Workflow。

## 主要风险与控制

| 风险 | 控制 |
|---|---|
| Suggested 被误当事实 | 枚举与服务不变量；UI 分区显示；无自动升级 |
| Patch 写错位置 | 唯一 paragraph anchor + 原文 + SHA256 三重检查 |
| Resume 重复写入 | 稳定幂等键与 applied key 集合 |
| Evidence 或目标已变化 | Freshness、scope/version/content/anchor/hash 在 apply 前重验 |
| 候选构建失败导致无有效版本 | `activate=False` 构建，所有校验通过后原子激活 |
| 破坏 V3 | 新包、新 API 路由、新 UI 页签；每个里程碑运行 V3 回归 |
| 形成伪多租户平台 | organization_id 只做归属与配置选择，无账号、权限、schema 隔离 |

