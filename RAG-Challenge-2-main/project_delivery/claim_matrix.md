# Claim Matrix

| Claim | Evidence | Status | Safe for Resume? | Safe for Interview? | Limitation |
| --- | --- | --- | --- | --- | --- |
| Generic multi-document retrieval | `artifacts/competition_decoupling/generic_smoke_results.json`；Generic tests | VERIFIED | Yes | Yes | 仍是每文档独立 FAISS，不是分布式搜索 |
| Legacy/Generic 双模式 | `tests/test_generic_questions.py`、Full regression | VERIFIED | Yes | Yes | 默认仍为 legacy_company |
| Real FAISS IndexFlatIP | Runtime/Domain ingestion artifacts | VERIFIED | Yes | Yes | 旧未归一化索引不可沿用 |
| Normalized document/query embeddings | `artifacts/baseline_runtime/baseline_report.md`；vector tests | VERIFIED | Yes | Yes | 只对新建/已验证索引成立 |
| Cosine-interpretable scores | 单位范数 + IndexFlatIP | VERIFIED | Yes | Yes | 不等于 Evidence Sufficiency |
| Real-model Rerank | Runtime 14/15 改序；Domain Smoke 3/3 | VERIFIED | Yes | Yes | 不宣称普遍提升 Answer Accuracy |
| Parent Page retrieval | Runtime 15/15 parent 关联核验 | VERIFIED | Yes | Yes | score 是触发 chunk score，不是 page 重算分 |
| Composite Citation Validation | Generic `(document_id,page_number)` tests/runtime | VERIFIED | Yes | Yes | 只验证 membership |
| Semantic Citation Verification | 无 entailment model/judge | NOT IMPLEMENTED | No | Boundary only | Membership 不等于语义支持 |
| Candidate interface v2 | `artifacts/candidate_interface_v2/import_result.json` | VERIFIED | Yes | Yes | content_hash 仅格式校验；不自动入库 |
| Agent cannot write formal FAISS | Candidate tests；`ingestion_performed=false` | VERIFIED BOUNDARY | Yes | Yes | 依赖调用者只使用公开 Candidate 接口 |
| Selective Chinese OCR | OCR reports/tests | VERIFIED FOR CORPUS | Yes | Yes | 规则驱动，非通用 OCR benchmark |
| Rotation recovery | page 37 90°/270° report/cache evidence | VERIFIED CASE | Yes | Yes | 只处理显式异常方向页 |
| Version Governance | manifest、resolver、version tests | VERIFIED | Yes | Yes | 不做自动法律解释或冲突消解 |
| Historical retrieval | 2017 独立 46 pages / 110 vectors asset | VERIFIED | Yes | Yes | 只支持已有 manifest/index asset |
| Retrieval Hit@1 0.815 → 0.926 | 同一 34 题 v0.1 vs final reports | VERIFIED | Yes, with scope | Yes | 不是 Answer Accuracy |
| Trusted QA pre-generation Shadow | Phase 1/2 reports | VERIFIED | Yes | Yes | 未上线 hard reject |
| Single cosine Reject unavailable | 分布 overlap、Held-out Hard Negative | EVIDENCE-BASED NON-DEPLOYMENT | Yes | Yes | 不是“实现了置信度拒答” |
| Post-answer fail-closed | Phase 3 replay/runtime/tests | VERIFIED | Yes | Yes | 仅确定性结构/Citation 状态 |
| Historical Citation failures 2/2 intercepted | Phase 3 replay | VERIFIED SMALL SAMPLE | Yes, with count | Yes | 不是生产拦截率 |
| Zero extra Gate LLM calls | Phase 3 trace/report | VERIFIED | Yes | Yes | 正常 Generation 仍调用 LLM |
| 220 tests passed | Final Full regression evidence | VERIFIED | Yes | Yes | 测试覆盖不等于全输入正确 |
| Production Ready | 缺少 auth/async/distributed/monitoring | NO CLAIM | No | No | 工程原型，不是生产系统 |
| Zero Hallucination | 无 universal verifier | PROHIBITED | No | No | 仍存在语义不支持风险 |
| Universal Confidence | score overlap，无 learned confidence | PROHIBITED | No | No | pre-gen only Shadow |
| Automatic Legal Interpretation | 无法律推理/责任模块 | PROHIBITED | No | No | 仅检索公开文本 |
| Fully autonomous governance | Candidate 仍需人工审核 | PROHIBITED | No | No | 无 Conflict Resolver/自动发布 |
| 真实特种设备企业落地 | 仅公开资料 validation scenario | PROHIBITED | No | No | 不是行业工作经历 |

## 使用规则

简历优先使用 `VERIFIED` Claim；`VERIFIED SMALL SAMPLE` 必须保留样本数；`NOT IMPLEMENTED`、
`PROHIBITED` 只能作为边界或未来工作，不能改写成已完成功能。
