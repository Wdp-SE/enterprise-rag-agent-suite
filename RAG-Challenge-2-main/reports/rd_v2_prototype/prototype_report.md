# 《R&D Document RAG V2 Prototype Report》

## 1. 结论

本轮已在当前副本中跑通一条真实的 V2 主链：自建研发规格 PDF 经现有 PDFParser/Docling 解析、现有 PageTextPreparation 规整、Section-aware Parent/Child 分块、现有 DashScope Embedding 与 normalized FAISS、BM25、RRF、现有 LLM reranker、bounded section context、现有 structured generation、citation membership validation 和 Trusted QA post-answer enforcement，最终产出可追溯回答。

Hybrid 在冻结的 13 题小评测上表现混合：Hit@3 有提升，Hit@1 与 MRR 有下降。因此已验证 BM25/RRF “确实工作并在个别问题有价值”，但尚未验证整个 Hybrid 配置稳定优于 Dense。

## 2. 实际修改文件

- `main.py`：增加 `rd_v2` preprocess 选项。
- `src/pipeline.py`：增加 V2 配置、Section-aware chunk 接线、BM25 构建和 `rd_hybrid` 参数传递。
- `src/questions_processing.py`：增加 `generic_dense` / `rd_hybrid` 选择，复用现有 generation、citation 与 Trusted QA；上下文格式中增加 section/chunk 元数据。
- `src/retrieval.py`：Dense 结果增量保留 page/section/parent 元数据；旧 Dense 与旧 Hybrid API 保持兼容。
- `src/ingestion.py`：持久化 BM25 ingestion 改用技术文档 tokenizer。

当前目录没有 Git 元数据，无法生成可信的 Git diff；以上清单来自本轮实际写入记录。

## 3. 新增文件

- `src/sectioning.py`：确定性标题检测、Parent Section、Child Chunk 与 legacy fallback。
- `src/text_tokenization.py`：保留接口名、字段名、模块编号、数值及中文字符/二元组的本地 tokenizer。
- `src/rd_retrieval.py`：corpus-wide BM25Plus、RRF、deduplicate、RDHybridRetriever 与 bounded SectionContextExpander。
- `tests/test_rd_v2.py`：14 个 V2 关键测试。
- `scripts/build_rd_v2_demo_pdf.py`：无敏感信息的固定研发规格书生成器。
- `scripts/run_rd_v2_prototype.py`：解析/索引分进程入口与 13 题固定检索评测。
- `scripts/run_rd_v2_answer_smoke.py`：3 个真实 provider 端到端 smoke。
- `data/rd_v2_prototype/`：固定语料、metadata、ground truth、解析结果、25 个 child chunks、FAISS 与 BM25 artifact。
- `reports/rd_v2_prototype/evaluation_results.json`：逐题检索结果、分数、贡献与延迟。
- `reports/rd_v2_prototype/evaluation_summary.md`：检索评测摘要。
- `reports/rd_v2_prototype/answer_smoke_results.json`：真实 rerank/generation/citation/Trusted QA trace。

## 4. 最终真实调用链

```text
PDF
 -> existing PDFParser (Docling + supported PyPdfium backend, OCR disabled for text PDF)
 -> existing PageTextPreparation
 -> SectionAwareTextSplitter
 -> Parent Section + retrieval Child
 -> existing VectorDBIngestor -> normalized FAISS IndexFlatIP
 -> local BM25Plus
 -> RDHybridRetriever -> weighted RRF -> chunk_id deduplicate
 -> existing LLMReranker (only in bounded answer smoke)
 -> SectionContextExpander (hit + parent anchor + neighbor, token budget)
 -> existing QuestionsProcessor / APIProcessor
 -> existing Pydantic structured output
 -> existing document_id + page_number citation membership validation
 -> existing Trusted QA post-answer enforcement
```

Context expansion 不生成跨页伪 Parent citation。Parent 通过 `section_id/parent_id/section_path` 关联，送入生成器的每个 evidence 仍是带独立 `document_id/page_number/chunk_id` 的 child。

## 5. 复用的旧模块

- `PDFParser` 与 Docling converter。
- `PageTextPreparation`。
- `TextSplitter` 的 token 统计与 recursive child split。
- `VectorDBIngestor`、DashScope embedding、L2 normalization、FAISS IndexFlatIP。
- `VectorRetriever` 的跨文档 Dense 检索与 metadata/version 接口。
- `LLMReranker`。
- `QuestionsProcessor`、`APIProcessor`、generic structured prompts。
- Citation membership validation。
- Trusted QA signal/audit/post-answer fail-closed。
- 现有 pytest 与 evaluation 基础设施。

## 6. 新增模块行为

- Section detection 支持 `1`、`1.1`、`1.1.1`、`第1章`、`第一章`、`第1节`、`一、`、`（一）`、Appendix 和 parser H1/H2；零标题时回退旧 page chunker。
- Child 增量保留 `section_id`、`parent_id`、`section_path`、`document_id`、`page_number` 与 `chunk_id`。
- Sparse 使用 BM25Plus；零 lexical-overlap 候选会被过滤，corpus 词频不被去重。
- RRF 不直接相加 Dense/BM25 原始分数；按 `chunk_id` 去重，参数集中在 `RDRetrievalConfig`。
- Context Expansion 默认包含命中 child、该 Parent 的首个可引用 child anchor、同 Section 前后 neighbor，并遵守 token budget。

## 7. Demo 运行命令

```powershell
# 已提供 PDF、解析资产和索引时，直接重跑评测
.venv\Scripts\python.exe scripts\run_rd_v2_prototype.py

# 从仓库内 PDF 重新走解析；本机已有 Docling 缓存可加 --offline-parse
.venv\Scripts\python.exe scripts\run_rd_v2_prototype.py --prepare --offline-parse

# Windows 上单独进程构建 Section/Child、Dense/FAISS 与 BM25
.venv\Scripts\python.exe scripts\run_rd_v2_prototype.py --rebuild-indexes

# 再运行固定评测
.venv\Scripts\python.exe scripts\run_rd_v2_prototype.py

# 3 个真实端到端 smoke（会调用 DashScope）
.venv\Scripts\python.exe scripts\run_rd_v2_answer_smoke.py

# 全量回归
.venv\Scripts\python.exe -m pytest -q
```

解析与索引刻意拆进两个 Python 进程，避免当前 Windows 环境中 Docling 与 FAISS 的 OpenMP runtime 冲突。

## 8. 测试 Corpus 与 ingestion 结果

Corpus 是 12 页英文自建研发规格书 `R&D Document Intelligence Platform Specification`，内容覆盖模块、接口、字段、依赖、数值指标、可靠性、安全与验收；不含真实项目或受限数据。

- PDFs: 1
- Pages: 12
- Detected headings: 12
- Parent sections: 13（含 1 个 preamble）
- Child chunks: 25
- Child -> Parent mappings: 25/25
- Multi-child sections: 12
- FAISS vectors: 25，全部 unit-normalized
- BM25 artifact: 已生成

## 9. Prototype Evaluation

共 13 题：12 个 answerable、1 个 unanswerable。类型覆盖 semantic、exact_term、interface、field、numeric、dependency、cross_section、acceptance、unanswerable。Hit/MRR 只统计 answerable；unanswerable 不参与命中指标，也未选择 cosine rejection threshold。

| Mode | Hit@1 | Hit@3 | Hit@5 | MRR |
|---|---:|---:|---:|---:|
| generic_dense | 0.916667 | 0.916667 | 1.000000 | 0.937500 |
| rd_hybrid | 0.833333 | 1.000000 | 1.000000 | 0.902778 |

Context-expanded evidence 是 prompt assembly 顺序，不是独立 retrieval ranking，因此没有用其顺序计算另一套 Hit/MRR。

## 10. 改善、无变化、退化与组件贡献

改善案例：

- RD05 `Which module consumes normalized_blocks?`：Dense 相关页 rank 4，Hybrid rank 3。相关 chunk 的 Dense candidate rank 为 4，BM25 rank 为 2；这是可追溯的 BM25 正贡献。

无变化案例：10/12 answerable 的 reciprocal rank 不变，包括 semantic、exact module ID、两个接口、数值和 acceptance 问题。

退化案例：

- RD07 `What does timeout_ms control?`：Dense rank 1，Hybrid rank 2。BM25 把 Appendix glossary 中 `timeout_ms: maximum export wait...` 的短精确定义提到第一；冻结 ground truth 只标注详细定义页 7，因此仍按退化计，不回改 ground truth。

Section / Context Expansion：7 个问题增加了位于 expected page 的 sibling evidence，包括 RD01、RD02、RD03、RD05、RD09、RD10、RD11；这些 evidence 保留独立 citation identity。它证明扩展实际执行，但当前单文档小语料不足以量化生成质量增益。

## 11. 真实端到端 smoke

Provider/model：DashScope `qwen-turbo` 用于现有 reranker 和 answer generation；embedding 为 `text-embedding-v1`。每题一次批量 rerank 和一次 structured generation。

| ID | 结果 | Citation | Trusted QA action | Rerank tokens | Answer tokens | Total tokens | Latency |
|---|---|---|---|---:|---:|---:|---:|
| SM01 `/api/v2/ingest` | substantive answer | page 4, valid | PASS | 964 | 1194 | 2158 | 4.644 s |
| SM02 concurrent users | `240` | page 8, valid | PASS | 974 | 1125 | 2099 | 3.484 s |
| SM03 retention days | `N/A` | empty, valid | VALID_ABSTENTION | 922 | 1120 | 2042 | 3.583 s |

- Structured output success: 3/3
- Citation membership success: 3/3
- Post-answer validation: 2 `VALID` + 1 `ANSWER_IS_NA`
- Extra hallucination-detection LLM calls: 0

## 12. 当前测试结果

- 初始基线：220 passed。
- 最终全量：234 passed，1 个 DashScope Assistants API deprecation warning。
- V2 新增：14 passed。
- 覆盖：heading detection、fallback、Child -> Parent、BM25 exact interface/field、RRF merge、duplicate removal、bounded expansion、existing reranker compatibility、citation membership compatibility。
- `generic_dense` 由原有 regression tests 和真实 13 题评测共同验证，未被替换。

## 13. 当前已知问题

1. 当前 checkout 路径含中文，Docling 原生组件会打印 `deepsearch_glm/resources` 路径编码警告；本次 PDF 仍成功解析 12 页。正式工程化应在 ASCII 安装路径验证或升级 Docling 后端。
2. Docling、FAISS 在同一 Windows 进程可能加载冲突的 OpenMP runtime；prototype runner 已通过 parse/index 分进程规避，未使用不安全环境变量。
3. Evaluation 只有一个 12 页 synthetic 文档，无法证明对真实数百页、多文档、OCR 表格语料的普适提升。
4. Equal-weight RRF 在 glossary 短定义上可能压过正文详细定义；尚未在冻结 dev/holdout 上调权或加入 section-type prior。
5. 当前 runtime BM25 在启动时由 chunk JSON 构建；持久化 BM25 artifact 已生成，但尚未做统一 manifest、版本校验与直接加载。
6. Parent/neighbor expansion 使用 token budget 与可引用 child，不做 parent 摘要；长 Section 的远距离依赖仍可能丢失。
7. Evaluation 的 unanswerable 只用于行为观察，不以 cosine threshold 拒答；继续依赖 structured/citation/post-answer fail-closed。

## 14. 仍属于 Prototype 的实现

- 基于 regex 的 conservative Section Detection。
- 本地 BM25Plus 与字符/二元组中文 tokenization。
- Equal-weight RRF 默认参数。
- In-memory sparse index 加载。
- Parent anchor + immediate neighbor 的简单 context policy。
- 单 synthetic corpus 的固定小评测与 3-query online smoke。
- 无并发 ingestion、增量更新、artifact schema migration 与运行期监控。

## 15. 下一步最值得工程化的 5 点

1. 冻结一套获准的真实脱敏研发文档 dev/holdout，至少覆盖多文档、100+ 页、OCR、表格与版本冲突，再决定 Hybrid 是否保留。
2. 将 Section/Chunk/BM25 artifact 加 schema version、content hash、embedding model 与 tokenizer version 校验，并直接加载持久化 sparse index。
3. 在 dev set 上做有限 RRF weight/top-k ablation，在 holdout 上一次性验证，重点约束 glossary/body 排名冲突。
4. 解决 Windows Docling/FAISS 原生依赖隔离与 ASCII path 支持，形成明确的可重复 ingestion command。
5. 增加 context budget、跨页 Section、表格 chunk 与 citation coverage 的集成测试及运行指标。

## 16. 最终状态

```text
PROTOTYPE_MAIN_CHAIN = PASS
HYBRID_VALUE_VERIFIED = INCONCLUSIVE
CITATION_COMPATIBLE = YES
READY_FOR_ENGINEERING_HARDENING = NO
```

`READY_FOR_ENGINEERING_HARDENING` 为 NO 的原因不是主链未跑通，而是 Hybrid 的固定评测仍是 Hit@3 提升、Hit@1/MRR 下降的混合信号；在真实脱敏长文档 holdout 上确认净收益前，不建议投入大规模生产化。
