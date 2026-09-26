# 业务流程指标报告

指标来自 run_cross_case_evaluation.py 的真实 HTTP 调用和工作流状态，不包含估算的人力、成本或效率收益。两套案例主链未调用外部 LLM。

| 指标 | Case A | Case B | 合计 |
| --- | ---: | ---: | ---: |
| change_cases_completed | 1 | 1 | 2 |
| impact_candidates_found | 4 | 3 | 7 |
| confirmed_trace_count | 3 | 2 | 5 |
| suggested_impact_count | 1 | 1 | 2 |
| patch_candidates_generated | 1 | 1 | 2 |
| patches_approved / edited / rejected | 1 / 0 / 0 | 1 / 0 / 0 | 2 / 0 / 0 |
| conflict_blocks | 1 | 1 | 2 |
| duplicate_apply_blocks | 1 | 1 | 2 |
| candidate_publish_success | 1 | 1 | 2 |
| workflow_elapsed_ms | 2934.643 | 2539.264 | 5473.907 |
| rag_calls / llm_calls | 9 / 0 | 9 / 0 | 18 / 0 |
| evidence retrieved / valid / deduplicated / selected | 5 / 5 / 5 / 5 | 4 / 4 / 4 / 4 | 9 / 9 / 9 / 9 |

Evidence 仍按 Retrieved → Scope/Version/Freshness Validation → Deduplication → Selection 进入流程，没有把所有 Evidence 直接传入模型。

这些指标回答“系统在固定合成案例中实际完成了什么”，不能支持节省人工、提升效率、降低成本或真实企业准确率等结论。
