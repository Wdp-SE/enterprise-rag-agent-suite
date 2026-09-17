# Knowledge Research Minimal Core 实施报告

## 1. 新增与修改文件

- 新增 `app/research/`：严格模型、Profile loader、SourcePolicy、EvidenceStore、RawSourceArchive、稳定 ID、DraftGenerator、CandidateBuilder、CandidateValidator 与共享 Candidate 契约。
- 新增 `app/tool/knowledge_draft.py`，继承现有 `BaseTool`；仅在 `app/tool/__init__.py` 增加导出。
- 新增 `config/research_profiles/special_equipment_validation.toml` 和 `config/research_policies/default.toml`。
- 新增 `tests/fixtures/research/`、`tests/fixtures/candidate/valid_candidate/` 与 `tests/research/`。
- 未修改 BaseAgent、ReActAgent、ToolCallAgent、Manus、PlanningFlow、BaseTool、Search 或 Browser 行为。

## 2. ResearchProfile

`ResearchProfile` 使用 Pydantic 严格校验，包含 `profile_id`、`domain`、`research_topic`、`research_questions`、`preferred_source_types`、`knowledge_category`、`max_sources` 和类型化 `output_requirements`。垂直场景内容仅存在 TOML 配置，核心实现没有特种设备法规或业务规则。

## 3. Evidence

`Evidence` 包含稳定身份、事实文本、来源机构/URL/类型、文号、日期、采集时间、本地原始文件、页码/章节、来源等级及文本哈希。URL、时区、工作区相对路径、非空文本、哈希与 ID 都会校验。DraftGenerator 的专业事实只取自 Evidence。

## 4. content_hash / raw_file_hash

- `content_hash = SHA256(NFKC + 空白规范化后的 Evidence.content UTF-8 字节)`。
- `raw_file_hash = SHA256(PDF/HTML/TXT 原始文件字节)`。
- 两者分别写入 `sources.json`，不复用字段，也不要求相等。
- CandidateValidator 从 Evidence 文本重算前者，从 `raw_sources/` 文件字节重算后者，并分别返回 `CONTENT_HASH_MISMATCH` 或 `RAW_FILE_HASH_MISMATCH`。

## 5. SourcePolicy

SourcePolicy 从 TOML 加载按优先级排序的 `domain_patterns`、`organization_types` 与 `source_types` 规则，返回 `level/reason/rule_id`。核心代码不包含具体可信站点，未匹配来源回退为 TIER3。

## 6. EvidenceStore

EvidenceStore 支持 `add/get/list/deduplicate/save/load`。去重键至少覆盖稳定 `evidence_id` 与“规范化来源身份 + content_hash”；持久化采用稳定排序 JSON、临时文件、flush/fsync 和 `os.replace`。

## 7. RawSourceArchive

只接受工作区内真实存在的 PDF、UTF-8 HTML、UTF-8 TXT；检查扩展名/基础签名，拒绝绝对路径、父目录逃逸、symlink 路径组件与非普通文件。归档文件名为 `{raw_file_hash}.{ext}`，复制后重算字节哈希，同一原始文件复用已有归档。

## 8. Stable ID 策略

- Evidence ID：规范化来源身份 + page/section + content_hash 的规范 JSON SHA256 前缀。
- Candidate/Document ID：domain + research_topic + category + 排序后的 Evidence 身份集合，使用不同命名空间哈希。
- Sxx：按 source level、organization、canonical source URL、content_hash、evidence_id 稳定排序后依次分配 S01、S02、S03。
- created_at、调用顺序和随机数均不参与身份计算。

## 9. KnowledgeDraftTool

工具输入仅含 `research_topic/domain/category/evidence_ids`，没有 status 或 approval 入参。Evidence 只能从 EvidenceStore 获取；缺失、数量不足或缺少原始文件时返回 `INSUFFICIENT_EVIDENCE`，不会调用 CandidateBuilder。第一版使用可替换 `DraftGenerator` 接口与 `DeterministicDraftGenerator`，未调用 LLM。

## 10. CandidateValidator

发布前校验必需目录/文件、严格 metadata/sources schema、固定 CANDIDATE 状态、稳定 document ID、连续唯一 Sxx、引用存在性与覆盖、Evidence 映射、两类独立哈希、raw 文件存在性/范围/普通文件/symlink、文件名哈希和未引用 raw 文件。任何 issue 都阻止 staging 发布。

## 11. Offline 调用链

`ResearchProfile + SourcePolicy -> Evidence -> EvidenceStore -> KnowledgeDraftTool -> CandidateBuilder(staging) -> RawSourceArchive + Stable IDs + DeterministicDraftGenerator -> CandidateValidator -> os.replace(final Candidate Package)`。

最终目录为：

```text
candidate_knowledge/{candidate_id}/
├── document.md
├── metadata.json
├── sources.json
└── raw_sources/
```

## 12. 测试结果

- 新增离线测试：`41 passed`，0 failed，0 skipped。
- 覆盖用户列出的 20 项必测条件；E2E 第一次返回 CREATED，第二次返回 REUSED，包摘要、Candidate ID 与 Document ID 不变。
- 新增实现随后已在独立 Python 3.12.13 完整依赖环境中复跑，仍为 `41 passed`。
- 现有 sandbox 测试现已完整收集 25 项，但宿主机 Docker daemon 未能启动，结果为 7 failed / 18 errors；详见 `full_regression_gate_report.md`。
- 本阶段遵守完全离线约束，没有联网安装依赖、没有启动 Docker、没有调用 Search/Browser/LLM/RAG。

## 13. Sample Candidate Package

合法离线样例位于 `tests/fixtures/candidate/valid_candidate/`，包含 3 份 raw source，`sources.json` 同时保存且区分 `content_hash/raw_file_hash`；该 Fixture 已由 CandidateValidator accepted。

## 14. 尚未实现能力

KnowledgeResearchAgent、真实 Search/Browser、真实公开资料调研、LLM DraftGenerator、RAG `import_candidate()` 联动、approve/正式知识库写入、Retry/NoProgress/Structured Trace、Version/Conflict/Health、Multi-Agent、UI 均未实现。

## 15. 下一阶段判断

Minimal Core 的离线业务链路已稳定可用，Python 3.12 依赖环境也已恢复。但按“原 OpenManus 现有测试必须通过”的严格完成口径，仍需先启动可用的 Docker daemon 并完成 sandbox 回归，同时处理或明确接受既有 console entrypoint packaging 问题。在这些门槛闭合前，不建议正式开始在线 Search/Browser 调研。
