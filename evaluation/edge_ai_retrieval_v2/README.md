# Edge AI 中文资料检索评测 v2

本评测只测 Seeed reComputer Industrial / Jetson 中文公开快照 `wiki-1eadc6584f96`。题目按 source ID 标注必要来源；DEV 与 HOLDOUT 按来源文档族整体隔离。当前索引没有第二个资料快照，也没有经过人工复核的图像 OCR 侧录，因此不报告历史版本对比或图片问答指标。

检索 runner 不调用 LLM API。它用服务实际的 `PublicKnowledgeIndex` 与 `PublicRetrievalRuntime`，在相同的冻结题集、Top-K、语言和硬件/软件过滤下比较 BM25 与显式多子句的 BM25 + RRF。运行前先创建一次锁，之后每次运行都会校验题集、语料、索引、策略配置及实现代码的 SHA-256。

```powershell
cd versioned-rag-service
..\OpenManus-rag\.venv\Scripts\python.exe ..\evaluation\edge_ai_retrieval_v2\run_evaluation.py --freeze-lock
..\OpenManus-rag\.venv\Scripts\python.exe ..\evaluation\edge_ai_retrieval_v2\run_evaluation.py --split all --output ..\evaluation\edge_ai_retrieval_v2\report.json
```

关键指标为必要来源召回率、完整必要来源集合率、错误型号/软件范围结果数、错误语言/快照数、无答案问题候选率及本地检索 P50/P95。无答案候选率不等于生成幻觉率；检索分数不证明回答正确。延迟是这台运行环境中的索引检索时间，不代表公网端到端时间。小题集结果用于发现失败样本，不应外推为生产效果。

HOLDOUT 在题目锁定后只作一次独立检查。不能依据 HOLDOUT 调整 query、切分、策略或语料；策略变更要提高版本并重新积累新的盲测来源族。
