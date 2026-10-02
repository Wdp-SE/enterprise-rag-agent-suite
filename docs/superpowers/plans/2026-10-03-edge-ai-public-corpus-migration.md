# 单一工业边缘 AI 语料迁移实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将活动产品统一迁移到 Seeed reComputer Industrial / Jetson 中文公开工程资料，保留通用版本化 RAG 与证据约束 Agent，并安全退役无关活动语料。

**Architecture:** 用逐源许可审核和固定快照生成唯一活动语料；以 manifest/profile 描述设备型号、模组、载板、软件基线和文档快照。RAG API 与 Streamlit 工作台从该 profile 提供筛选，Agent 以设备变更类别生成有限查询并只报告有来源支持的候选。为新语料建立独立检索与审查评测，再切换 Render 配置、删除旧活动索引及领域入口；历史评测留档。

**Tech Stack:** Python 3.12、FastAPI、Pydantic、BM25/现有检索策略、Streamlit、pytest、JSON manifests、Render Blueprint。

**Spec:** `docs/superpowers/specs/2026-10-03-edge-ai-public-corpus-migration-design.md`

## Global Constraints

- 唯一活动演示语料为 Seeed reComputer Industrial / Jetson 边缘 AI 设备中文公开资料。
- 每个纳入正文/图像的来源必须有单项许可和归属记录；许可不清楚的来源只保留链接和必要元数据，不复制正文或图片。
- 资料快照、设备型号/硬件配置、JetPack/L4T/BSP 软件基线分别建模；`latest` 只在已声明型号和软件基线内解释。
- 不得伪造企业工单、硬件兼容关系、测试结果或未经人工复核的 OCR 证据。
- RAG 只给可追溯证据；Agent 输出影响候选与缺口；人负责最终审核；不写回上游资料。
- Autoware、DolphinScheduler 与旧合成业务语料不得进入活动索引、默认工作台或发布制品；旧评测只能作为历史档案。
- 旧语料上的指标不得宣称为新语料成绩；检索指标、生成答案正确率和影响分析质量分别报告。
- 不覆盖或提交工作区现存的 `2026-10-01-rag-agent-accuracy-hardening-design.md` 改动、`.local-demo-temp/`、`RAG-Challenge-2-main/` 或其他未跟踪资料。
- 当前请求授权更新 GitHub `main`；没有授权在此计划内发布 Render 公网服务，因此本计划只验证部署配置与本地 smoke，不触发公网部署。

## Review Focus

- 未获再分发许可、来源文件哈希变化或不安全路径：导入校验拒绝纳入；由 Task 1 的来源校验测试覆盖。
- 用户指定 manifest 中不存在的型号、SKU、载板或软件基线：返回明确范围错误而不是扩大检索；由 Task 3 的 API 范围测试覆盖。
- 同型号的旧软件基线和当前基线存在相似文本：结果必须服从精确范围过滤并报告来源基线；由 Task 2/3 的索引与 API 测试覆盖。
- 用户没有提供决定兼容性所必需的硬件/软件信息：Agent 输出缺口，不生成肯定兼容结论；由 Task 4 的 Agent 测试覆盖。
- 命中内容来自旧领域、非 allowlist 来源或不在本次证据集合：API/UI/Agent 不展示为当前证据；由 Task 5/7 的工作台和发布完整性测试覆盖。

---

### Task 1: 来源许可、版本与固定快照入口

**Files:**
- Create: `versioned-rag-service/config/edge_ai_source_selection.json`
- Create: `versioned-rag-service/public_corpus_edge_ai/SOURCE_AUDIT.md`
- Create: `versioned-rag-service/scripts/import_edge_ai_sources.py`
- Modify: `versioned-rag-service/requirements.txt`
- Test: `versioned-rag-service/tests/test_edge_ai_source_import.py`

**Interfaces:**
- `load_source_selection(path: Path) -> dict`
- `validate_source_record(row: dict, *, source_root: Path) -> None`
- `normalize_source_file(source: dict, input_path: Path) -> tuple[str, dict]`，返回 UTF-8 Markdown 正文和源解析信息。
- 每条 allowlist 记录包含 `source_id`、`source_url`、`repository`、`commit` 或 `retrieved_at_utc`、`document_path`、`language`、`license`、`license_status`、`attribution`、`source_format`、`device_model`、`module_sku`、`carrier_board`、`software_baselines` 与 `local_path`。Facet 的 `*` 只表示文档的一般适用范围，不表示硬件兼容性；兼容结论必须由独立配置关系表中的来源明确支持。

- [x] **Step 1: 写来源校验的失败测试**：测试未审核/不可再分发来源、缺固定 commit、错误语言、路径穿越、未审核 URL host、SHA-256 错误、link-only 正文及导入后 symlink。
- [x] **Step 2: 运行测试确认失败**：`python -m pytest tests/test_edge_ai_source_import.py -q`；先观察缺模块红灯，再逐项观察 MDX 版本标签、表格跨度和 symlink 回归测试红灯。
- [x] **Step 3: 盘点并固定可用来源**：核对 Seeed 中文设备矩阵、Industrial/J20/J30/J40 设备指南、刷写/BSP/OTA、JetPack 版本关系、故障排查和 AI 部署资料；逐文件在 `SOURCE_AUDIT.md` 记录许可、归属、哈希、设备/软件适用范围。所有正文固定到官方仓库完整 commit；未核验许可的 datasheet/PDF/图片只保留链接。
- [x] **Step 4: 实现导入校验与归一化**：建立 JSON allowlist；导入器只读取固定本地快照，支持 Markdown、HTML 表格与文本型 PDF 页码归一化为 Markdown；保留原始 URL、页面/页码、源格式、解析状态。仅为离线 importer 在 `requirements.txt` 增加 `pypdf`，不进入 Render runtime requirements。Docusaurus 版本 Tab 标签和含 colspan/rowspan 的 HTML 表格会保留；代码围栏内容不被 HTML 清洗误删。图片 OCR 未启用。

```python
def validate_source_record(row: dict, *, source_root: Path) -> None:
    required = ("source_id", "source_url", "language", "license", "license_status", "attribution", "source_format", "local_path", "sha256")
    if any(not isinstance(row.get(key), str) or not row[key].strip() for key in required):
        raise ValueError("source record is incomplete")
    if row["license_status"] != "redistributable":
        raise ValueError("only redistributable source content may be indexed")
    source_path = (source_root / row["local_path"]).resolve()
    if not source_path.is_relative_to(source_root.resolve()) or not source_path.is_file():
        raise ValueError("source path is outside the pinned snapshot")
    if hashlib.sha256(source_path.read_bytes()).hexdigest() != row["sha256"]:
        raise ValueError("source content hash mismatch")
```
- [x] **Step 5: 运行来源导入测试**：导入器通过，18/18 来源许可与 SHA 校验为 redistributable；`python -m pytest tests/test_edge_ai_source_import.py -q` 19 passed。图片共 334 个引用从索引正文剔除，未声称 OCR 可检索。
- [x] **Step 6: Commit 来源与导入边界**：仅提交本任务文件及获许可的源快照；commit `23810bd feat: import audited Chinese Jetson corpus`。

### Task 2: 新领域语料 manifest、索引与硬件/软件过滤

**Files:**
- Create: `versioned-rag-service/public_corpus_edge_ai/corpus_manifest.json`
- Create: `versioned-rag-service/public_corpus_edge_ai/retrieval_policy.json`
- Create: `versioned-rag-service/public_corpus_edge_ai/public_retrieval_runtime.json`
- Modify: `versioned-rag-service/src/public_knowledge.py`
- Create: `versioned-rag-service/scripts/build_edge_ai_corpus.py`
- Create: `versioned-rag-service/tests/test_edge_ai_public_knowledge.py`

**Interfaces:**
- 保留当前 `PublicKnowledgeIndex.search(query, *, top_k, version, language, policy)` 参数，并添加可选 `device_model: str | None`、`module_sku: str | None`、`carrier_board: str | None`、`software_baseline: str | None`。
- 每个 chunk 复制来源 manifest 中非空的同名设备/软件元数据；`version` 继续表示资料快照，不改义为产品发行版。

- [x] **Step 1: 写 manifest 与过滤测试**：小型 fixture 覆盖通用指导、两个 JetPack 基线和两个设备型号；断言 manifest 区分 snapshot 与 software baseline、chunk 保留来源/设备字段、四个过滤器均为硬过滤且 AND 组合，通用来源可参与候选。
- [x] **Step 2: 运行测试确认失败**：`python -m pytest tests/test_edge_ai_public_knowledge.py -q` 初次结果 9 failed，暴露 index 缺设备过滤字段、scope 元数据与许可/中文来源校验；按测试失败补实现。
- [x] **Step 3: 实现 manifest 校验和 facet 过滤**：校验活动 workspace、中文语言、来源许可、Seeed Wiki 主机、路径、固定快照和哈希；chunk 保存设备/基线/来源字段；eligible 文档阶段按四个可选 facet 做精确交集，通用 `*` 只纳入通用说明，不代表兼容性。

```python
FACET_FIELDS = ("device_model", "module_sku", "carrier_board", "software_baseline")

def _matches_facets(chunk: dict, filters: dict[str, str | None]) -> bool:
    for field, expected in filters.items():
        if expected is None:
            continue
        observed = chunk.get(field)
        if isinstance(observed, list):
            if expected not in observed:
                return False
        elif observed != expected:
            return False
    return True
```
- [x] **Step 4: 建新语料与索引**：新增可重复 `scripts/build_edge_ai_corpus.py`，只接受与来源 allowlist 完全匹配的 18 份中文资料，生成 manifest、394 个 chunks、向量、BM25 基线策略及运行时配置；新语料快照 `wiki-1eadc6584f96`，策略状态为待重测。
- [x] **Step 5: 运行知识服务测试**：`python -m pytest tests/test_edge_ai_public_knowledge.py tests/test_public_knowledge.py -q` → 27 passed；实际 corpus build 成功，J4012 + JetPack 7.2 与 J4012 + JetPack 6.x 的检索 smoke 命中对应领域资料。
- [ ] **Step 6: Commit 新语料索引边界**：仅提交新领域 manifest、许可通过的语料资产、策略配置、服务实现和相应测试。

### Task 3: 公开 API 与客户端支持设备配置

**Files:**
- Modify: `versioned-rag-service/src/public_api.py`
- Modify: `versioned-rag-service/src/public_server.py`
- Modify: `demo-ui/services/public_knowledge_client.py`
- Modify: `versioned-rag-service/tests/test_public_server.py`
- Create: `versioned-rag-service/tests/test_edge_ai_public_api.py`

**Interfaces:**
- `SearchRequest` 新增与 Task 2 一致的四个可选 facet 字段；`POST /public/search`、`POST /public/query` 和 `/public/review-advice` 的内部检索都采用相同范围。
- `/public/workspace` 返回 `workspace_id`、`domain_profile`、`snapshots`、`available_versions`、`hardware_models`、`module_skus`、`carrier_boards`、`software_baselines`、`languages` 与来源计数；评测字段只有在新语料/代码/策略/题集指纹一致时返回。

- [ ] **Step 1: 写 API 合约测试**：断言有效设备筛选只返回匹配证据；未知型号或软件基线返回 HTTP 422 和稳定错误码；缺失可判定结论的必要配置时返回候选和缺口；健康与 workspace 只报告 `edge_ai_device` profile；任何旧领域 corpus 注入都被拒绝。
- [ ] **Step 2: 运行测试确认失败**：执行 `python -m pytest tests/test_edge_ai_public_api.py -q`，预期新 workspace 字段与请求过滤尚不存在。
- [ ] **Step 3: 更新请求模型和路由**：增加请求 facet 字段并校验它们属于 manifest 声明的选项；将它们传入 index search、生成证据和审查建议；去掉只对 Autoware 禁止英文的硬编码，改用 manifest 声明的语言集合通用校验。

```python
class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=20)
    version: str = Field(default="current", min_length=1, max_length=64)  # corpus snapshot
    language: Literal["zh"] = "zh"
    device_model: str | None = None
    module_sku: str | None = None
    carrier_board: str | None = None
    software_baseline: str | None = None
```
- [ ] **Step 4: 更新 workspace 响应与客户端**：workspace 由 manifest/profile 产生，不含 Autoware 专属评测分支或旧语料 fallback；`PublicKnowledgeClient.search` 与 `query_official` 接受并序列化设备 facet。
- [ ] **Step 5: 运行 API 回归**：执行 `python -m pytest tests/test_edge_ai_public_api.py tests/test_public_server.py -q`；旧域评测相关断言改为历史档案不向活动 workspace 暴露。
- [ ] **Step 6: Commit API 范围契约**：提交 API、客户端和对应测试。

### Task 4: 设备变更领域 Agent 与证据来源校验

**Files:**
- Create: `change-review-agent/config/edge_ai_device_change_profile.json`
- Create: `change-review-agent/app/domain_profile.py`
- Modify: `change-review-agent/app/change_request.py`
- Modify: `change-review-agent/app/public_review.py`
- Modify: `change-review-agent/tests/test_change_request.py`
- Modify: `change-review-agent/tests/test_public_review.py`

**Interfaces:**
- `load_change_profile(path: Path) -> dict` 校验 profile id、分类、检索焦点和必要配置。
- `build_request_plan(summary: str, *, change_type: str | None = None, impact_scope: str | None = None, profile: dict | None = None, device_model: str | None = None, module_sku: str | None = None, carrier_board: str | None = None, software_baseline: str | None = None, target_snapshot: str = "current") -> dict`；返回原始描述、分类来源、最多四个检索问题、目标设备/软件基线和预期资料类型。
- Agent 的检索 gateway `search(question, *, version, language, top_k=5, device_model=None, module_sku=None, carrier_board=None, software_baseline=None)` 将 Task 3 的设备 facet 传给每个子查询；证据来源按当前 workspace manifest 的 allowlist 主机、repository/commit 或固定页面 hash 校验，不再只接受 GitHub `blob` URL。

- [ ] **Step 1: 写设备变更规划和安全断言测试**：覆盖 J40/J30 型号变化、模组/载板替换、JetPack/L4T/BSP 升级、电源/热/接口配置、AI runtime/部署、测试资料变化；断言最多四次检索、原描述保留、未知型号要求人工补充、无匹配证据不会产生“兼容/不受影响”的肯定结论。
- [ ] **Step 2: 运行 Agent 测试确认失败**：执行 `python -m pytest tests/test_change_request.py tests/test_public_review.py -q`；预期仍含 Autoware planning 分类、双语审查和 GitHub-only 来源限定。
- [ ] **Step 3: 加设备领域 profile**：把设备变更类别、中文关键词、检索焦点、预期资料类型及人工 checklist 放在 JSON profile；通用 clause splitting、查询预算和原文保留继续留在 `change_request.py`，无领域支持的请求回退为 general 并标记未识别。

```python
plan = build_request_plan(
    summary, change_type=change_type, impact_scope=impact_scope, profile=profile,
    device_model=device_model, module_sku=module_sku,
    carrier_board=carrier_board, software_baseline=software_baseline,
    target_snapshot=target_snapshot,
)
for query in plan["queries"][:4]:
    result = gateway.search(
        query, version=plan["target_snapshot"], language="zh", top_k=10,
        device_model=plan["device_model"], module_sku=plan["module_sku"],
        carrier_board=plan["carrier_board"], software_baseline=plan["software_baseline"],
    )
```
- [ ] **Step 4: 限定检索和证据**：对变更输入抽取/接收用户确认的设备型号、模块、载板和软件基线；子查询共享这些过滤条件；只把本轮 RAG 返回的证据 ID 传入生成；来源校验依据当前 manifest，而非把任何可访问 URL 当作受信证据。
- [ ] **Step 5: 运行 Agent 回归**：重跑两个 Agent 测试文件和 `python -m pytest tests/change_impact_review -q`（在 `change-review-agent/` 执行）；测试要证明无证据时保留缺口、有证据才列影响候选、人工审核字段保留。
- [ ] **Step 6: Commit 领域审查 profile**：提交 Agent profile、规则、来源校验和回归测试。

### Task 5: 单一领域工作台与公开说明

**Files:**
- Modify: `demo-ui/services/public_workspace_profile.py`
- Modify: `demo-ui/services/public_knowledge_client.py`
- Modify: `demo-ui/public_workbench.py`
- Modify: `demo-ui/app.py`
- Modify: `demo-ui/tests/test_public_workspace_profile.py`
- Modify: `demo-ui/tests/test_public_official_workbench.py`
- Modify: `demo-ui/tests/test_app.py`
- Modify: `demo-ui/README.md`
- Modify: root `README.md`

**Interfaces:**
- UI 从 `workspace.domain_profile` 读取产品名称、允许的筛选值、示例问题、变更类别、来源说明和评测状态。
- 知识查询和 Agent 页面用独立控件设置资料快照、设备型号、模组/载板和软件基线；工作台不把资料快照显示成产品发行版。

- [ ] **Step 1: 写 profile 与用户流程测试**：workspace profile 只接受 `edge_ai_device` 和 `zh-CN`；示例问题只能来自新领域 profile；页面渲染中不出现活动 Autoware/DolphinScheduler 入口、旧分数、双语提示或旧产品示例；查询客户端收到用户选中的四个过滤字段。
- [ ] **Step 2: 运行 UI 测试确认失败**：执行 `python -m pytest tests/test_public_workspace_profile.py tests/test_public_official_workbench.py -q`（在 `demo-ui/` 执行），记录未满足的断言。
- [ ] **Step 3: 将 profile 校验改为领域 ID 校验**：删除单仓库 Autoware 绑定，检查 `workspace_id`、profile id、语言和声明来源；不匹配时禁用查询并显示实际 profile 错误。
- [ ] **Step 4: 移除旧 Streamlit 演示切换**：把 `demo-ui/app.py` 简化为只导入并运行 `public_workbench.render()`；删除 `DEMO_LEGACY_FIXTURES` 分支和用于旧合成工单 UI 的 imports。更新 `test_app.py`，验证启动始终进入当前 public workbench，设置旧环境变量也不能切换至旧界面。
- [ ] **Step 5: 更新页面流和显示**：替换旧业务文案、问题示例、筛选项与 Agent 类型；评测页只渲染指纹匹配的新评测和明确的指标口径；“版本与历史”区分资料快照、设备型号、JetPack/L4T 基线；未评测状态写清楚，不回显历史领域数值。

```python
profile = workspace["domain_profile"]
device_model = st.selectbox("设备型号", profile["hardware_models"], key="edge_device_model")
software_baseline = st.selectbox("软件基线", profile["software_baselines"], key="edge_software_baseline")
snapshot = st.selectbox("资料快照", workspace["available_versions"], key="corpus_snapshot")
```
- [ ] **Step 6: 重写用户文档并验证界面**：README 介绍唯一的新业务、来源边界、运行方式、公开限制和准确性评测；用 UI 测试检查主要页面文案，运行 `python -m pytest tests/test_public_workspace_profile.py tests/test_public_official_workbench.py tests/test_app.py -q`。
- [ ] **Step 7: Commit 工作台切换**：提交 profile/client/UI/README 改动。

### Task 6: 冻结新语料检索与变更审查评测

**Files:**
- Create: `evaluation/edge_ai_retrieval_v1/README.md`
- Create: `evaluation/edge_ai_retrieval_v1/cases.jsonl`
- Create: `evaluation/edge_ai_retrieval_v1/split_lock.json`
- Create: `evaluation/edge_ai_retrieval_v1/run_evaluation.py`
- Create: `evaluation/edge_ai_change_review_v1/README.md`
- Create: `evaluation/edge_ai_change_review_v1/cases.jsonl`
- Create: `evaluation/edge_ai_change_review_v1/run_evaluation.py`
- Create: `versioned-rag-service/src/public_evaluation_release.py`
- Test: `versioned-rag-service/tests/test_public_evaluation_release.py`

**Interfaces:**
- 检索 runner 在不调用模型 API 的情况下接收 `--split dev|holdout|all` 与策略名，验证题集/语料/策略哈希后输出按 split 与类别分组的 JSON 报告。
- Agent runner 分别报告规则查询覆盖、证据候选覆盖、缺口和人工评分；不得将流程覆盖当作影响准确率。
- `validate_public_evaluation_release(manifest, corpus_root, build_identity) -> dict | None` 只在所有冻结指纹和发布策略匹配时返回可展示报告。

- [ ] **Step 1: 建立人工标注题集**：按来源文档族编写事实问答、型号/基线过滤、多来源关联、表格/图纸线索（仅在已复核来源存在时）和领域内无答案案例；每题标注必要来源、允许型号/软件范围及答案是否可由资料回答。按来源族划分 DEV/HOLDOUT，保持 HOLDOUT 问题不用于规则调试。
- [ ] **Step 2: 写 runner 的完整性和指标测试**：测试题集 hash 变动、错语料指纹、无答案题、错误型号/软件证据、Top-K 变化时的报告状态；断言输出 Recall@K、完整证据集率、版本/型号错误数、无答案候选与延迟，并报告样本分母。
- [ ] **Step 3: 实现冻结与复算**：先锁定题集/切分/语料/代码/配置指纹，再运行实际 DEV/HOLDOUT。仅比较当前已实现的 BM25、字段/分面和混合候选；OCR 只在审核 sidecar 存在时比较。没有独立 reranker 实现就不新增模型依赖或宣称重排效果。检索指标使用 source ID 而非易随切块变化的 chunk ID。

```python
rows = search(case["query"], policy=policy, top_k=case["top_k"], scope=case["allowed_scope"])
required = set(case["required_source_ids"])
ranked_ids = [row["source_id"] for row in rows]
source_recall = len(required & set(ranked_ids)) / len(required) if required else None
complete = bool(required) and required.issubset(ranked_ids)
wrong_scope_count = sum(row["source_id"] not in case["allowed_source_ids"] for row in rows)
```
- [ ] **Step 4: 评估 Agent 端到端审查**：对固定假设变更记录必需查询、明确关系、预期候选、必要缺口和人工评分 rubric；先保留盲化 HOLDOUT，记录每类失败案例。API generation 模型准确率单独人工复核，不用 RAG 命中率代替。
- [ ] **Step 5: 绑定可发布评测**：将新的报告元数据写入 manifest；实现通用指纹校验器，在 workspace 响应返回数据前验证语料、索引、retrieval config、题集与报告 hash；过期或不一致时只显示“当前版本未验证评测”。
- [ ] **Step 6: 运行冻结评测与测试**：重跑两份 runner 的 `--split all`，保存实际结果和失败分类；执行 `python -m pytest tests/test_public_evaluation_release.py tests/test_public_server.py -q`。
- [ ] **Step 7: Commit 新评测与发布门禁**：提交题集、锁、runner、报告、指纹校验及测试；报告保留真实输出，不手工挑选/改写有利数字。

### Task 7: 旧活动语料退役、Render 配置和发布 smoke

**Files:**
- Modify: `render.yaml`
- Modify: `start_prototype.ps1`
- Modify: `versioned-rag-service/.env.example`
- Modify: `versioned-rag-service/scripts/public_release_smoke.py`
- Modify: `versioned-rag-service/tests/test_public_release_smoke.py`
- Modify: `versioned-rag-service/tests/test_deployment_manifests.py`
- Modify: `versioned-rag-service/tests/test_public_knowledge.py`
- Modify: `versioned-rag-service/tests/test_figure_evidence.py`
- Modify: `versioned-rag-service/tests/test_public_demo_profile.py`
- Modify: `versioned-rag-service/README.md`
- Create: `evaluation/archive/README.md`
- Delete: `versioned-rag-service/tests/test_autoware_source_sync.py`
- Delete: `versioned-rag-service/tests/test_autoware_documentation_import.py`
- Delete: `versioned-rag-service/tests/test_autoware_bilingual_smoke.py`
- Delete after Task 1–6 pass: `versioned-rag-service/public_corpus/`
- Delete after Task 1–6 pass: `versioned-rag-service/public_corpus_autoware/`
- Delete after fixture-backed regression tests pass: `versioned-rag-service/public_demo_artifacts/rd-v2-public-demo-v1/`
- Delete after active references are removed: `versioned-rag-service/scripts/build_public_demo_artifact.py`
- Delete after references are removed: `versioned-rag-service/config/autoware_source_selection.json`, `autoware_retrieval_policy.json`, `autoware_documentation_selection.json`
- Delete after replacement tests pass: `versioned-rag-service/scripts/fetch_autoware_sources.py`, `sync_autoware_sources.py`, `import_autoware_documentation.py` and their Autoware-specific test modules

**Interfaces:**
- Render `RAG_PUBLIC_CORPUS_ROOT` and `RAG_PUBLIC_RETRIEVAL_CONFIG` both point into `public_corpus_edge_ai`.
- Release smoke requires expected UI/API revision, corpus/profile id, source language, new evidence probes, and matching corpus/config/evaluation fingerprints; its JSON result contains no old-domain probe name.

- [ ] **Step 1: Write retirement and release tests**：release smoke rejects Autoware or DolphinScheduler workspace, wrong `workspace_id`, non-Chinese hits, mixed-device or wrong-baseline hits, unknown hashes and stale UI/API revisions; deployment tests assert Render points only to the new corpus root/config.
- [ ] **Step 2: Run tests to capture current failures**：执行 `python -m pytest tests/test_public_release_smoke.py tests/test_deployment_manifests.py -q`（在 `versioned-rag-service/` 执行）。
- [ ] **Step 3: Update deployment and smoke probes**：把检索探针替换为已通过新 HOLDOUT 标注的安全示例问题；验证 workspace 与 health 的 build/fingerprint 一致，额外调用 public scope refusal 确认拒答不触发 generation。

```yaml
      - key: RAG_PUBLIC_CORPUS_ROOT
        value: public_corpus_edge_ai
      - key: RAG_PUBLIC_RETRIEVAL_CONFIG
        value: public_corpus_edge_ai/public_retrieval_runtime.json
```
- [ ] **Step 4: 切换本地启动脚本并关掉旧 runtime toggle**：`start_prototype.ps1` 将 `RAG_PUBLIC_CORPUS_ROOT` 与 retrieval config 指向 `public_corpus_edge_ai`，去除 `DEMO_LEGACY_FIXTURES`、`RD_V2_ARTIFACT_ROOT` 的活动设置。`versioned-rag-service/.env.example` 删除旧 synthetic artifact root 示例，只保留当前公共服务变量。
- [ ] **Step 5: Archive 历史评测并移除活动 legacy 代码/索引**：增加 archive index，标明旧题集只描述旧语料且不参与当前发布；删除 API/工作台中的 Autoware、DolphinScheduler 历史成绩渲染与 legacy validators；删除旧活动语料目录及旧采集配置/脚本/测试；删除 Render 构建目录中的 `public_demo_artifacts/rd-v2-public-demo-v1`，把原来依赖此目录的 Runtime 测试改用 `tests/fixtures/` 下最小、显式合成的 fixture。保留旧 evaluation 目录，但从默认 README、workspace API 和部署制品中解耦。
- [ ] **Step 6: 限制发布包与合成 fixture**：扫描 `render.yaml` 服务 root 和构建产物，确认发布 runtime 索引只读取 `public_corpus_edge_ai`；合成 fixture 只位于测试目录且不被 manifest 引用。不要清理工作区既有未跟踪目录。
- [ ] **Step 7: 运行删除后回归与旧词扫描**：执行 `python -m pytest tests/test_public_release_smoke.py tests/test_deployment_manifests.py tests/test_public_server.py -q`；运行 `rg -n "Autoware|autoware|DolphinScheduler|dolphinscheduler" src scripts render.yaml README.md`，活动服务路径必须无命中，归档评测目录不在扫描范围。
- [ ] **Step 8: Commit 活动语料退役与发布配置**：确认 staged 文件名只属于本任务后提交，不使用 `git add -A`。

### Task 8: 全量验收并更新 GitHub main

**Files:**
- Verify: `versioned-rag-service/`
- Verify: `change-review-agent/`
- Verify: `demo-ui/`
- Verify: `render.yaml`, root `README.md`, `evaluation/edge_ai_*`

**Interfaces:**
- 工作区已有本地修改保持原状；执行合并前只允许本分支提交包含本计划及其实现明确拥有的文件。

- [ ] **Step 1: 运行完整后端与 Agent 测试**：分别在 `versioned-rag-service/`、`change-review-agent/`、`demo-ui/` 执行 `python -m pytest -q`；记录退出码和失败摘要。
- [ ] **Step 2: 运行语料、索引、检索和审查 smoke**：从干净语料重建索引；执行新 retrieval 与 change-review 评测；启动 API 后验证 `/health`、`/public/workspace`、query 与 review 流程均使用新 profile/hash；本地 Streamlit UI 检查默认最新快照、设备筛选、证据链接和缺口显示。
- [ ] **Step 3: 运行发布配置与内容扫描**：运行 release smoke 的本地 mock tests、`git diff --check`，并复核发布根目录不包含旧活动 corpora；核对归档报告保留但没有当前指标引用。
- [ ] **Step 4: 审查分支差异和工作区隔离**：检查 `git diff origin/main...HEAD` 与 `git status --short`；不暂存、不重置现有用户改动或未跟踪资料。发现 main 已前进时先同步并重跑受影响检查。
- [ ] **Step 5: 更新 main**：若远程仓库接受直接快进，使用 `git push origin HEAD:main`；若仓库策略拒绝直接推 main，则推送当前分支并创建/更新供用户审阅的 PR，不绕过保护规则、不 force-push。更新后读取远端 `main` SHA，确认包含新 corpus profile、评测和退役变更。
- [ ] **Step 6: 报告边界**：提供 main commit、测试及离线评测实际结果、来源许可覆盖、当前已知缺口；说明 Render 配置已指向新 corpus，但本计划没有执行公网部署。

## 计划自审

- 设计稿每项均映射到任务：来源治理/版本语义 → Tasks 1–2；RAG 配置过滤/API → Tasks 2–3；Agent 影响审查 → Task 4；工作台 → Task 5；评测与策略 → Task 6；退役、部署和 smoke → Task 7；全量回归与 main → Task 8。
- Review Focus 的五种错误条件分别由 Tasks 1、2–4、5、7 的明确测试覆盖。
- 接口命名保持一致：`device_model`、`module_sku`、`carrier_board`、`software_baseline` 从 manifest → index → API/client → Agent/UI；`workspace_id` 是工作区身份，`version` 仍表示资料快照。
- 旧评测保留在 archive 边界；旧运行语料、旧在线文案和旧成绩校验从当前 service/UI/deploy 路径移除，不把归档当作新成绩。
- 没有为未知来源许可、硬件版本或性能数字填入假值；若 Task 1 发现无法合法构建足够语料，应停止索引发布并报告来源缺口。
