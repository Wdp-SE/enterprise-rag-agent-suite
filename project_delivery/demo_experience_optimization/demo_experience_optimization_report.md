# 秋招 Demo 体验与可解释性优化报告

## 1. 结论

本轮仅完成四项 P0：当前资料范围、Agent 局部刷新结果、业务化引用来源、业务化失败原因。未增加业务功能，未改变 RAG 检索、Evidence/Citation 校验、Freshness、Checkpoint/Resume、Human Review、Incremental Update 或 Version Governance 语义。

## 2. 修改文件与原因

| 文件 | 修改原因 |
|---|---|
| `demo-ui/app.py` | 在 RAG 与 Agent 页面接入真实 Scope 展示；结果绑定实际请求 Scope；展示业务失败原因和未审核章节数。 |
| `demo-ui/components/scope_view.py` | 新增薄展示 helper，把已有 project/document/type/version Scope 映射为业务名称；原始 Scope 仅放在技术详情。 |
| `demo-ui/components/evidence_view.py` | 统一 RAG 与 Agent 来源格式为文档、版本、章节、页码；内部 ID 收入技术详情。 |
| `demo-ui/components/workflow_view.py` | 展示真实局部刷新摘要，并把字段资料不足原因转换为业务提示。 |
| `demo-ui/components/business_messages.py` | 集中映射现有状态/异常码到五类用户提示，没有建立新异常体系。 |
| `demo-ui/services/agent_client.py` | 保留底层异常文字到 ServiceError 技术详情，便于 UI 精确映射；异常仍继续抛出。 |
| `demo-ui/README.md` | 小幅补充 Scope、Citation、局部刷新和 MVP 边界说明。 |
| `OpenManus-rag/app/document_workflow/workflow.py` | 将现有 Freshness 算法已经得到的 affected 集合写入可选 `refresh_summary`，没有重新判定或新增 RAG 调用。 |
| `OpenManus-rag/app/document_workflow/facade.py` | 向 UI 透传可选刷新摘要；历史任务读取已有 execution trace。 |
| `RAG-Challenge-2-main/src/rd_v2_runtime.py` | 在已有安全 Trace 中增加可选 `version_label`、`section_path`，并在 Trusted QA 信息中增加可选 `post_validation_status`。 |
| `demo-ui/tests/test_demo_experience.py`、`demo-ui/tests/test_v3_ui.py` | 验证当前/历史 Scope、来源字段、内部 ID 默认隐藏和业务失败映射。 |
| `OpenManus-rag/tests/document_workflow/test_business_e2e.py` | 验证真实刷新统计、未受影响章节不重跑、过期 Evidence 阻断正式输出。 |
| `RAG-Challenge-2-main/tests/test_rd_v2_engineering_hardening.py` | 验证新增安全 Trace 字段和 Invalid Citation 继续 Fail-Closed。 |

## 3. Scope 可视化

页面直接消费提交给 RAG 的 Scope 或 Agent Facade/Checkpoint 返回的 Scope。展示项目、文档类型、文档名称和版本范围；显式选择 `SUPERSEDED` 版本时显示“当前正在查询历史版本资料”。Resume 结果使用 `result["scope"]`，因此显示内容来自 Checkpoint 保存范围，不使用当前控件重新推断。内部 `document_id`、`version_id` 和原始 Scope 只在“技术详情”中出现。

Scope 是业务检索范围约束，不等同于 ACL/RBAC。

## 4. 局部刷新可视化

没有修改 Freshness 或 Resume 算法。原流程在 `cache.apply_freshness` 后已经得到 affected task 集合；本轮只把该集合与本次真实 trace 组合成可选 `refresh_summary`：

- 总章节：模板实际解析章节数；
- 受影响章节：既有 affected 集合；
- 复用章节：恢复前已有草稿且未受影响的章节；
- 重新检索章节：受影响且本次 `rag_calls > 0` 的章节；
- 重新生成章节：受影响且实际进入本次 trace 的章节；
- 保持不变章节：模板章节减去 affected 集合。

没有 affected 章节时字段为 `null`，UI 不显示刷新摘要。没有新增或重复 RAG 调用。

## 5. Citation / Evidence 展示

RAG 和 Agent 统一优先展示：

- `《文档名称》`
- `版本：Vx.x`
- `章节：xxx`
- `页码：第 xx 页`

RAG 问答的 validated source 原本只有 document/page，UI 无法得到业务版本名和章节路径，因此在已有安全 Trace 中向后兼容地增加两个可选展示字段。Agent 直接读取真实 Evidence 的 `version_label`、`section_path` 和 `page_number`。内部 document/version/section/chunk/evidence ID 默认只在技术详情中显示。

Citation / Evidence 表示来源可追溯，不表示答案必然正确、已自动证明事实真实性或零幻觉。

## 6. 失败提示映射

| 现有状态或错误 | 用户提示 |
|---|---|
| `NO_EVIDENCE`、`EVIDENCE_TOO_SHORT`、`INSUFFICIENT_EVIDENCE` | 当前选择的资料范围内未找到足够依据，暂不生成该内容。 |
| `STALE_EVIDENCE_REFRESH`、`EVIDENCE_FRESHNESS_INVALID` | 引用资料已更新，该章节需要重新检索后才能继续。 |
| `REVIEW_REQUIRED`、`ALL_REQUIRED_SECTIONS_MUST_BE_APPROVED` | 还有 X 个必要章节尚未审核通过，暂不能生成正式文档。 |
| `INVALID_EVIDENCE_REFERENCE`、`EVIDENCE_MEMBERSHIP_INVALID`、无有效 Citation | 当前草稿引用的资料不满足校验要求，请重新获取证据后继续。 |
| `STRUCTURED_OUTPUT_INVALID`、`GENERATION_OR_SCHEMA_ERROR` | 模型返回内容未满足当前结构要求，本次结果已停止进入正式流程。 |

技术原因仍在“技术详情”、Trace 和后端异常链中保留；没有吞异常或把 Fail-Closed 改成自动补全。

## 7. API 调整

存在三类向后兼容的可选展示字段调整：

1. RAG safe trace 增加 `version_label` 和 `section_path`；
2. RAG `trusted_qa` 增加 `post_validation_status`；
3. Agent execution trace / Facade result 增加可选 `refresh_summary`。

已有字段、HTTP 路径、请求 Scope、检索结果、Citation membership 和业务行为均未改变。这些字段是必要的：否则 UI 要么无法展示真实章节/版本，要么需要复制 Freshness 判断逻辑。

## 8. 测试结果

| 验证项 | 结果 |
|---|---|
| RAG 完整回归 | PASS，34 passed |
| Agent 完整回归 | PASS，87 passed（基线 86，新增 1 条过期 Evidence 正式输出阻断测试） |
| UI 完整回归 | PASS，15 passed（基线 12，新增 3 条聚焦展示测试） |
| Python compile | PASS，86 个 tracked / 本轮新增 Python 文件 |
| 正式模块 import | PASS，RAG / Agent |
| pip check | PASS，RAG 与 Agent/UI 均为 No broken requirements found |
| RAG Offline Runtime Smoke | PASS，Artifact COMPLETE，DENSE_ONLY + SECTION_PATH，未调用在线模型 |
| RAG Versioned E2E | PASS，历史版本检索与 Section Diff 正常 |
| RAG HTTP `/retrieve` | PASS，返回 3 条，版本与章节字段完整 |
| Agent ↔ RAG 真实 HTTP | PASS，4 章节、4 字段、14 条唯一 Evidence、Draft 存在、状态 REVIEW_REQUIRED |
| Safe Business / Human Review | PASS |
| Checkpoint / Resume | PASS，Scope fingerprint 保持，已完成章节不重跑 |
| Evidence Freshness | PASS，仅受影响章节重检索/重生成 |
| 过期 Evidence 正式输出阻断 | PASS，现有 membership/freshness 完整性校验拒绝输出 |
| Streamlit Smoke | PASS，health 200/`ok`，首页 200 且识别为 Streamlit |
| Benchmark 有效性 | PASS，6 个入口可编译，历史报告无 diff；未重跑完整 Benchmark |
| Secret Scan | PASS，扫描 203 个文本文件，0 potential match |
| `git diff --check` | PASS |

## 9. A–I 重点验收

- A：RAG Client 测试确认请求中的 Scope 与展示 helper 消费的原始 Scope 相同。
- B：Checkpoint/Resume 测试确认 scope fingerprint 不变；页面展示 Facade 返回的 Checkpoint Scope。
- C：刷新摘要直接断言真实 trace 统计，没有硬编码 2/8。
- D：测试继续确认未受影响章节没有新增 RAG 调用。
- E：当前有效版本与显式历史版本均有直接展示测试。
- F：RAG 与 Agent 来源的文档、版本、章节、页码来自真实 Trace/Evidence，并有字段一致性测试。
- G：资料不足仍生成 MISSING 并阻止未经人工补充的正式输出。
- H：过期 Evidence 直接测试确认正式输出被完整性校验阻断。
- I：必要章节未全部审核时仍无法 finalize；Safe Business E2E 验证驳回后阻断、全部通过后才生成。

## 10. 用户可见变化

用户现在能看到当前搜索哪些资料、是否正在查历史版本、每条来源的文档/版本/章节/页码、版本更新后哪些章节被重用或重做，以及流程停止的业务原因。内部 ID 和错误码不再占据主视图，但仍可在技术详情中检查。

## 11. 未变化的核心逻辑

未修改 Embedding、FAISS、DENSE_ONLY、SECTION_PATH、Top K、Scope 语义、Document Lifecycle、Incremental Update、Version Governance、Evidence 模型、Citation membership、Trusted QA 决策、Freshness 判定、Checkpoint/Resume 状态机、Human Review 状态机、Approved DOCX 规则或 Agent ↔ RAG HTTP 边界。未新增依赖、框架、服务或在线调用。

保留的 79 个 `LIKELY_REMOVABLE`、334 个 `REVIEW_REQUIRED`、`CODE_OF_CONDUCT.md`、ignored 大目录、两个受保护集成 DOCX 和面试指南均未处理。

## 12. Git diff 摘要

最终代码差异包含 11 个 tracked 文件修改，当前统计为 273 行新增、62 行删除；另新增 3 个展示/测试 Python 文件和本报告。改动集中在展示层、可选 Trace 元数据和对应验收测试。Performance Benchmark 目录无 diff。
