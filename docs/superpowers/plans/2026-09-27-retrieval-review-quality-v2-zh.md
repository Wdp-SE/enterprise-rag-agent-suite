# 检索与审查质量 V2 实施计划

> **2026-09-28 续做说明：** 本文件保留 52 份来源 / 659 个 chunk 上的 V2 实验与当时的阻塞记录，不能作为当前运行质量结论。官方固定提交来源现已扩至 132 份 / 1322 个 chunk，旧条目和旧片段 ID 保持不变；扩充后的检索复评单独记录在 `evaluation/real_world_retrieval/quality_v3/`。默认 BM25 暂未晋级或替换。本页下方关于网络阻塞、语料未扩充的文字是此前执行状态。

> **供执行者使用：** 按任务逐项执行本计划，并用 `- [ ]` 勾选进度。

**目标：** 扩充与版本对应的官方证据，在一套新建且锁定的评测集上衡量检索改进，并把变更审查建议整理成可核对的结构化结果，同时保留人工审批边界。

**架构：** 保持现有公开 FastAPI / Streamlit 接口和 BM25 行为作为基线。增加带来源记录的官方资料、包含标题层级的 chunk 元数据和一个按字段加权的 BM25 候选策略；建立独立的 V2 评测集；只有通过新评测门槛后才切换默认检索策略。变更审查使用独立的结构化模型契约，普通 RAG 回答生成保持不变。

**技术栈：** Python、FastAPI、Streamlit、NumPy、JSON/JSONL、pytest、Git。

**设计稿：** `docs/superpowers/specs/2026-09-27-retrieval-review-quality-v2-design.md`（中文版：`docs/superpowers/specs/2026-09-27-retrieval-review-quality-v2-design-zh.md`）

## 全局约束

- 将现有 V1.0 公开语料、查询集、Ground Truth、selection lock 和 final-selection 结果作为历史基线；不要覆盖这些评测结果文件。
- 每份新增资料都必须固定到 Apache DolphinScheduler 官方 commit 或 release，并记录规范 URL、仓库路径、语言、许可/署名、抓取时间和 SHA-256。
- 只增加相关的官方文档及直接关联的官方变更记录；不得把假设文本当作上游资料，也不得导入整个上游仓库。
- 模型输出不得创建“已确认”的文档关联；已确认关联必须来自已登记的明确来源链接。
- 每个模型证据 ID 都必须与该请求实际提供的证据逐一核验；保留拒答/降级行为和人工审核流程。
- 不写入 Apache 上游或公共基线；不得加入 API Key、Secret、私人绝对路径或本地运行产物。
- 不触碰或暂存无关的未跟踪目录 `RAG-Challenge-2-main/`。
- 在分支 `codex/retrieval-review-quality-20260927` 上工作；`main` 是规范主线，只有全部获准的验证门槛通过后才更新。禁止 force-push。

## 重点评审风险

- 如果固定在 3.4.2 commit 的来源中没有某个页面，必须记录为不可用；不能从 3.4.3 复制或自行编造。测试 manifest 与来源 commit 是否一致。
- 跨文档查询必须要求 Top-5 覆盖全部预期的独立来源；评测联合来源召回率，不能只看“至少命中一个相关来源”。
- 无答案或版本冲突请求不得变成确定口吻的模型答案；测试拒答和明确歧义输出。
- Prompt injection 文本和检索证据之外的模型引用不得影响审查或被接受；测试证据 ID 成员校验和失败关闭行为。
- 模型未启用、响应格式错误、服务商不可用时，仍须保留可用的检索证据，并将结果标记为待人工决定；逐项测试降级行为。

---

### 任务 1：扩充固定版本的官方来源并重建语料产物

> **当前状态：受阻。** 当前执行环境无法获取 Apache 固定版本页面（本地代理拒绝请求，官方 GitHub/raw 页面返回 cache miss）。没有伪造或替换上游文本；仓库仍是 52 份来源 / 659 个 chunk。需要在可访问官方来源的环境继续此任务。

**文件：**
- 新建：`versioned-rag-service/scripts/sync_pinned_sources.py`
- 新建：`versioned-rag-service/public_corpus/source_coverage.json`
- 新建：`versioned-rag-service/public_corpus/sources/3.4.2/{en,zh}/` 下实际存在的 3.4.2 页面
- 修改：`versioned-rag-service/public_corpus/corpus_manifest.json`
- 修改：`versioned-rag-service/public_corpus/chunks.json`
- 修改：`versioned-rag-service/public_corpus/dense_vectors.npy`
- 修改：`versioned-rag-service/public_corpus/retrieval_policy.json`
- 测试：`versioned-rag-service/tests/test_public_knowledge.py`
- 测试：`versioned-rag-service/tests/test_sync_pinned_sources.py`

**接口：**
- 输入：现有 manifest 中固定的 commit：3.4.2 为 `71eb6412f940afa1f171f1097dc0e99ed61d16e2`，3.4.3 为 `a190201acffa03d199d4ca216288734a6513de3d`。
- 输出：`sync_sources(root: Path, fetcher) -> dict[str, int]`、`raw_source_url(commit: str, path: str) -> str`，以及一份能区分“已获取页面”和“固定 commit 中不存在路径”的覆盖记录；最终 manifest 和索引产物须能被 `PublicKnowledgeIndex` 接受。

- [x] **步骤 1：先写来源溯源失败测试。** 已添加固定 URL/路径遍历、来源字节哈希与存在/缺失记录、网络错误时不写入，以及拒绝未固定到当前版本 commit 的 allowlist 测试。

```python
def test_raw_source_url_uses_the_pinned_commit():
    assert raw_source_url(
        "71eb6412f940afa1f171f1097dc0e99ed61d16e2",
        "docs/docs/zh/guide/parameter/priority.md",
    ) == (
        "https://raw.githubusercontent.com/apache/dolphinscheduler/"
        "71eb6412f940afa1f171f1097dc0e99ed61d16e2/"
        "docs/docs/zh/guide/parameter/priority.md"
    )
```

- [x] **步骤 2：运行新测试并确认失败。** 首次因同步器不存在而失败；补充固定 commit 校验测试后，也先因未校验 allowlist commit 而失败。

运行：`pytest versioned-rag-service/tests/test_sync_pinned_sources.py -q`

- [x] **步骤 3：实现固定来源同步器。** 仅使用 3.4.3 官方 Markdown 路径作为 allowlist，只从固定的 3.4.2 commit 获取对应页面；404 记录为缺失，保留署名/许可元数据，并在所有响应校验完成后才写文件。注入 fetcher 的离线测试验证了该契约。

- [ ] **步骤 4：重建并验证语料。** 实际同步和索引重建受阻：只读访问也无法解析 `raw.githubusercontent.com`。本步骤没有修改语料文件；恢复官方源访问后再运行命令。默认检索策略保持 BM25。

运行：`python versioned-rag-service/scripts/sync_pinned_sources.py --rebuild`

- [x] **步骤 5：运行来源和公开索引测试。** 注入来源契约测试和当前 public-index 完整性测试共 15 项通过；针对新下载来源的实际验证仍属于受阻的步骤 4。

运行：`pytest versioned-rag-service/tests/test_sync_pinned_sources.py versioned-rag-service/tests/test_public_knowledge.py -q`

### 任务 2：保留标题上下文，并增加实验性的字段加权 BM25 候选策略

**文件：**
- 修改：`versioned-rag-service/src/public_knowledge.py`
- 修改：`versioned-rag-service/tests/test_public_knowledge.py`
- 修改：`versioned-rag-service/public_corpus/chunks.json`
- 修改：`versioned-rag-service/public_corpus/retrieval_policy.json`

**接口：**
- 输入：固定版本的 Markdown 来源，以及现有 `PublicKnowledgeIndex.search(query, ..., policy=...)` 接口。
- 输出：chunk 元数据新增 `document_title` 和继承而来的 `heading_path`；新增实验策略 `bm25_fields`；除非任务 3 通过晋级门槛，否则默认策略保持不变。

- [x] **步骤 1：先写标题路径失败测试。** 使用多层 Markdown 标题，断言子 chunk 保留完整祖先路径和最末级标题。

```python
def test_parts_keep_inherited_heading_path():
    parts = _parts("# API\n## Workflow\n### Recovery\nDefault: retry")
    assert parts[0] == ("Recovery", ["API", "Workflow", "Recovery"], "Default: retry")
```

- [x] **步骤 2：运行测试并确认它因当前 chunk 只保存叶子标题而失败。**

运行：`pytest versioned-rag-service/tests/test_public_knowledge.py::test_parts_keep_inherited_heading_path -q`

- [x] **步骤 3：实现标题路径元数据和字段化评分。** 保留当前 BM25 实现，作为对比基线。新增分别计算标题、标题路径和正文词频的候选评分；在代码中明确写出权重，并将这些字段加入新生成的 chunks。

- [x] **步骤 4：编写并运行排序测试。** 断言标题/章节精确匹配能提升候选排序，同时现有 fixture 在 `policy="bm25"` 下的结果保持不变。

运行：`pytest versioned-rag-service/tests/test_public_knowledge.py -q`

- [x] **步骤 5：** 使用任务 1 的命令重建 chunks 和索引哈希，然后再次运行公开索引校验测试。

### 任务 3：建立独立的 V2 检索评测集

**文件：**
- 新建：`evaluation/real_world_retrieval/quality_v2/queries.jsonl`
- 新建：`evaluation/real_world_retrieval/quality_v2/ground_truth.jsonl`
- 新建：`evaluation/real_world_retrieval/quality_v2/frozen_split.json`
- 新建：`evaluation/real_world_retrieval/quality_v2/selection_lock.json`
- 新建：`evaluation/real_world_retrieval/quality_v2/run_quality_v2.py`
- 新建：`evaluation/real_world_retrieval/quality_v2/test_quality_v2.py`
- 新建：`evaluation/real_world_retrieval/quality_v2/results/`

**接口：**
- 输入：V2 语料 manifest、`PublicKnowledgeIndex`，以及与现有检索 Benchmark 兼容的查询/Ground Truth 字段。
- 输出：`complete_source_recall(ranked_source_ids: list[str], required_source_ids: set[str]) -> bool`、40 条新编写案例、确定性的 20/20 DEV/HOLDOUT 划分、输入哈希锁、各策略指标，以及仅写入 `quality_v2/results/` 的排序证据 ID。来源 ID 使用 `version|language|document_key`，避免 manifest 顺序变化导致整数 ID 漂移。

- [x] **步骤 1：先写划分和指标失败测试。** 断言各类别的查询 ID 可重复、DEV 20 条加 HOLDOUT 20 条、两个划分互不重叠、输入哈希被锁定，并测试双来源查询的完整来源评分。

```python
def test_cross_document_metric_requires_both_sources():
    assert complete_source_recall(["source-a"], {"source-a", "source-b"}) is False
    assert complete_source_recall(["source-a", "source-b"], {"source-a", "source-b"}) is True
```

- [x] **步骤 2：运行测试并确认它因 V2 划分和 runner 尚不存在而失败。**

运行：`pytest evaluation/real_world_retrieval/quality_v2/test_quality_v2.py -q`

- [x] **步骤 3：基于固定来源和已记录的 3.4.2→3.4.3 变更编写 40 个新问题。** 包含 8 个跨文档案例、8 个版本范围案例、6 个中文案例、6 个英文案例、4 个中英混合案例、4 个困难/歧义案例和 4 个无答案案例。记录精确的预期证据标记和来源身份；明确标记假设场景。离线可验证的来源仍来自现有 52 文档快照；联网取新官方来源受执行环境代理限制，未伪造语料。

- [x] **步骤 4：实现确定性划分和 runner。** 使用按类别分层的 SHA-256 分配方式，锁定查询集、Ground Truth 和语料 manifest 的哈希；按去重后的来源而非重复 chunk 计算 Recall@5、MRR 和 nDCG@5，同时报告多来源完整 Top-5 召回率、无答案问题 Top-1 分数分布（仅作检索诊断）、错误和本机 warm P95。不要把近邻候选存在与否标成错误答案。

- [x] **步骤 5：只运行 DEV 候选对比。** 对比 `bm25` 和 `bm25_fields`，输出写到 `quality_v2/results/`。不要运行 V1 final-selection runner，也不要覆盖任何 V1 结果。

运行：`python evaluation/real_world_retrieval/quality_v2/run_quality_v2.py --split dev --policies bm25,bm25_fields`

- [x] **步骤 6：先应用晋级门槛，再运行一次 HOLDOUT。** `bm25_fields` 通过 DEV 门槛；单次 HOLDOUT 未通过，Recall@5 和跨文档完整召回低于 BM25，因此保留 BM25 默认策略，并记录在 `quality_v2/results/holdout__*.json`。

运行：`python evaluation/real_world_retrieval/quality_v2/run_quality_v2.py --split holdout --policies bm25,bm25_fields`

### 任务 4：将模型辅助审查建议结构化，并校验其证据

**文件：**
- 修改：`versioned-rag-service/src/answer_generation.py`
- 修改：`versioned-rag-service/src/public_api.py`
- 修改：`versioned-rag-service/tests/test_public_server.py`
- 修改：`versioned-rag-service/tests/test_formal_runtime_contract.py`
- 修改：`change-review-agent/app/public_review.py`
- 修改：`change-review-agent/tests/test_public_review.py`

**接口：**
- 输入：仅限 Agent 已检索并提供的当前版本证据 chunk；通用 RAG 答案继续使用当前回答/引用契约。
- 输出：`change_interpretation`、`impact_candidates[{evidence_chunk_id, reason, suggested_action}]`、`evidence_gaps`、`version_ambiguities`、`reviewer_actions` 和固定的 `REQUIRES_HUMAN_REVIEW` 状态。每个 ID 必须属于本次 RAG 证据；已确认关联仍由确定性逻辑产生，不属于模型输出。

- [x] **步骤 1：先写审查响应失败测试。** 覆盖合法结构化响应、未知证据 ID、缺少字段、格式错误的 JSON、服务商不可用；断言通用答案解码器和提示词契约保持不变。

```python
def test_review_advice_rejects_evidence_id_outside_supplied_chunks():
    payload = {"impact_candidates": [{
        "evidence_chunk_id": "not-supplied", "reason": "相关证据",
        "suggested_action": "人工核对",
    }]}
    with pytest.raises(ValueError, match="evidence"):
        validate_review_evidence_membership(payload, allowed_chunk_ids={"chunk-1"})
```

- [x] **步骤 2：运行定向测试并确认它们因尚无独立审查 schema 而失败。**

运行：`pytest versioned-rag-service/tests/test_formal_runtime_contract.py versioned-rag-service/tests/test_public_server.py change-review-agent/tests/test_public_review.py -q`

- [x] **步骤 3：实现独立的审查提示词和解码器。** 保持 `StructuredAnswerGenerator.generate()` 的外部契约不变。严格校验响应键、字段类型、状态和每条建议影响的证据 ID 是否来自本次提供的 chunks。绝不接受模型创建的“已确认”关联。

- [x] **步骤 4：** 在 `/public/review-advice` 和 `PublicReviewAgent` 中接入结构化响应。凭据缺失或服务商报错时，保留已检索候选并返回非成功的审查建议状态；不得把降级证据伪装成模型已确认的影响。

- [x] **步骤 5：运行定向服务和 Agent 测试。** 后端 39 项、Agent 7 项通过；包含未知 chunk 拒绝及固定待人工审核状态。

运行：`pytest versioned-rag-service/tests/test_formal_runtime_contract.py versioned-rag-service/tests/test_public_server.py change-review-agent/tests/test_public_review.py -q`

### 任务 5：呈现结构化审查结果并更新项目文档

**文件：**
- 修改：`demo-ui/public_workbench.py`
- 修改：`demo-ui/tests/test_public_official_workbench.py`
- 修改：`README.md`
- 修改：`demo-ui/README.md`
- 新建：`evaluation/real_world_retrieval/quality_v2/report.md`

**接口：**
- 输入：任务 4 校验通过的结构化审查响应，以及任务 3 的 V2 指标。
- 输出：分别展示假设、建议候选、证据缺口、审核人操作和人工决定的 UI 区域；文档明确区分 V1 历史选型结果与当前实测行为。

- [x] **步骤 1：先编写 UI 失败测试。** 断言变更理解、建议理由/动作、证据缺口和待人工审核状态可见。

- [x] **步骤 2：运行定向 UI 测试。** 最初选用的解释器未安装 Streamlit；随后使用已有的 `data-juicer` 环境运行公共工作台 AppTest。

运行：`pytest demo-ui/tests/test_custom_change_review.py demo-ui/tests/test_business_workflow_ui.py -q`

- [x] **步骤 3：呈现结构化字段并保留现有安全降级。** 保留公共基线免责声明，以及当前仅保存在会话中的审核决定行为。

- [x] **步骤 4：更新 README 并添加 V2 报告。** V2 候选未通过 HOLDOUT 晋级门槛；保留 BM25 正式默认，V1 选型报告不变，并单独记录 V2 划分、指标和未扩充语料的限制。

- [x] **步骤 5：运行定向 UI 测试和文档空白检查。** 公共工作台 AppTest 通过（34 项），运行于 Python 3.10 / Streamlit 1.56；Streamlit 提示 Python 3.10 不在其支持的 3.11–3.13 范围内。`git diff --check` 通过。

运行：`pytest demo-ui/tests/test_custom_change_review.py demo-ui/tests/test_business_workflow_ui.py -q`

### 任务 6：验证完成的改动，并将其晋级到 `main`

**文件：**
- 只验证任务 1–5 明确列出的文件；不要暂存工作区的无关内容。

- [x] **步骤 1：运行检索、API、Agent、UI 和同步器契约定向测试。** 公共知识/服务/运行时契约测试 40 项通过；Agent 审查测试 8 项通过；V2 评测测试 7 项通过；公共工作台 AppTest 34 项通过（Python 3.10 / Streamlit 1.56）；同步器契约与公共索引测试 15 项通过。真实来源同步仍受 DNS 阻断。未运行无关全量测试，也未调用真实付费模型。

运行：`python -m pytest versioned-rag-service/tests/test_public_knowledge.py versioned-rag-service/tests/test_formal_runtime_contract.py versioned-rag-service/tests/test_public_server.py -q`；`python -m pytest change-review-agent/tests/test_public_review.py -q`；`python -m pytest evaluation/real_world_retrieval/quality_v2/test_quality_v2.py -q -p no:cacheprovider`；以及使用现有 Streamlit 环境运行 `demo-ui/tests/test_public_official_workbench.py` AppTest。

- [x] **步骤 2：运行语料/哈希校验和 `git diff --check`。** 当前 chunks 哈希与 `retrieval_policy.json` 一致；659 个旧 chunk 的字段值和顺序均保留，只新增 `document_title`、`heading_path`。52 份来源 manifest 和 dense 向量字节未变，默认策略仍是 BM25。V2 候选未通过 HOLDOUT 晋级门槛。

- [x] **步骤 3：检查变更路径、暂存路径、diff、Secret 扫描和 tracked 状态。** 已检查相关代码 diff；没有暂存文件，也没有发现凭据样式字面量；官方语料来源、向量、V1 final-selection 结果和 public baseline 均未修改。无关未跟踪目录 `RAG-Challenge-2-main/` 保持未触碰。由于任务 1 受阻、晋级门槛未完成，没有暂存文件。

- [ ] **步骤 4：所有检查通过后，在 `codex/retrieval-review-quality-20260927` 上创建一个实现提交。**

- [ ] **步骤 5：获取 `origin` 并确认 `origin/main` 没有分叉。** 如果远端 main 已前进，停止并协调，不覆盖远端工作。

```powershell
git fetch origin
git merge-base --is-ancestor origin/main codex/retrieval-review-quality-20260927
```

- [ ] **步骤 6：快进本地 `main`，正常推送并核对远端 HEAD。** 禁止 force-push。如果推送因凭据或传输问题被阻止，保持远端不变并报告具体错误。

```powershell
git switch main
git merge --ff-only codex/retrieval-review-quality-20260927
git push origin main
git ls-remote origin refs/heads/main
```

---

## 自检

- 已批准设计中的每个范围项都映射到了任务 1–6。
- 新语料、评测集、审查响应契约和 UI 展示分别有测试步骤。
- 不覆盖现有 V1 选型产物；新 runner 只向 `quality_v2/` 写结果。
- 已确认关联由确定性逻辑产生；模型只能提出与所给证据绑定的建议。
- 不写入公共基线或上游。最后的 Git 操作为普通快进和普通 push，绝不 force-push。
