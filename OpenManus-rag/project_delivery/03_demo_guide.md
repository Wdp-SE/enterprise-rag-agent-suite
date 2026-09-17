# 演示指南

## 1. 演示目标

推荐用 4–5 分钟证明三件事：

1. OpenManus 原有能力没有被改造成垂直专用 Agent；
2. 一次公开资料调研可以形成 Raw Source → Evidence → ResearchResult → 多种输出的完整追溯链；
3. Reliability 组件有清晰决策与测试边界，不靠“失败后无限重跑”。

默认采用“已有真实工件 + 本地离线测试”的方式。这样既能展示真实联网/LLM结果，又不会在面试现场依赖网络、外部 API 或重复消耗 token。

## 2. 演示前检查

在项目根目录、已激活 Python 3.12 虚拟环境的终端执行：

```powershell
python --version
python -m pip check
python main.py --help
python run_research.py --help
```

期望：Python 3.12、依赖无冲突、两个入口均能展示帮助。`main.py` 是原 OpenManus 入口，`run_research.py` 是新增 Research 入口。

若需要运行 Sandbox 测试，先执行：

```powershell
docker info
```

## 3. 推荐演示脚本

### 0:00–0:40：项目定位与边界

打开根目录 `README.md` 的架构图并说明：

- BaseAgent、ReAct、Tool Calling、Search、Browser、Files、MCP 是 OpenManus 原有能力；
- 新增的是阶段式 Research Workflow、证据契约、输出 Adapter 和 Reliability 组件；
- `run_research.py` 是独立入口，原 `main.py` 不受影响；
- 特种设备只是 Profile，不存在于核心流程规则中。

### 0:40–1:20：配置驱动

打开：

- `config/research_profiles/special_equipment_validation.toml`
- `config/research_policies/default.toml`

指出 Profile 描述 domain、topic、questions、preferred source types 和输出要求；SourcePolicy 以规则判定 Tier，不硬编码“某站点绝对正确”。解释换行业时主要更换配置。

### 1:20–2:30：真实 Evidence 链

运行 ID：`kr_20260828T082105547457Z_b40bc521`。

依次展示：

1. `workspace/research_runs/kr_20260828T082105547457Z_b40bc521/outputs/run_manifest.json`
2. `workspace/research_runs/kr_20260828T082105547457Z_b40bc521/raw_sources/`
3. `workspace/research_runs/kr_20260828T082105547457Z_b40bc521/evidence/evidence.json`
4. `workspace/research_runs/kr_20260828T082105547457Z_b40bc521/outputs/structured_result.json`
5. `workspace/research_runs/kr_20260828T082105547457Z_b40bc521/outputs/research_report.md`

讲解要点：

- 搜索得到 7 个候选，策略选择 3 个，最终 2 个下载成功、1 个失败；
- 成功来源被保存为原始 HTML，Search snippet 没被当作 Evidence；
- 22 条 Evidence 包含 source URL、local file、section、`content_hash` 和 `raw_file_hash`；
- 下载失败被记录为 limitation，Workflow 没有用常识把缺失资料补齐。

### 2:30–3:20：Evidence Budget 与 LLM

展示：

- `workspace/research_runs/kr_20260828T082105547457Z_b40bc521/outputs/evidence_selection_report.json`
- `workspace/research_runs/kr_20260828T082105547457Z_b40bc521/outputs/llm_synthesis_metrics.json`
- `workspace/research_runs/kr_20260828T082105547457Z_b40bc521/outputs/research_report_llm.md`

真实结果：22 → 6 条 Evidence，估算 token 35,313 → 9,640；`qwen-max` 实际用量 5,974 tokens、延迟 11,500 ms；8 个 finding 全部引用 SelectedEvidence。

强调：完整 22 条 Evidence 没有被删除；Planner 只是确定性地选择单次 LLM 输入子集。GroundingValidator 只验证 Evidence ID 的存在和集合归属，不证明语义蕴含。

### 3:20–4:00：Candidate 与 RAG 边界

真实 Candidate ID：`cand_special-equipment-validation_4996f87d16f2cd6b`。若当前机器可访问该目录，可展示 `workspace/candidate_knowledge/`；若目录受 Windows ACL 限制，改用仓库中同契约的离线 Fixture：

- `tests/fixtures/candidate/valid_candidate/document.md`
- `tests/fixtures/candidate/valid_candidate/metadata.json`
- `tests/fixtures/candidate/valid_candidate/sources.json`
- `tests/fixtures/candidate/valid_candidate/raw_sources/`

说明真实联动已得到 `accepted=true`、`ingestion_performed=false`。Agent 只能生成 `CANDIDATE`，未调用 approve、Embedding 或 FAISS。

### 4:00–5:00：可靠性与回归

运行两个小而稳定的测试组：

```powershell
python -m pytest tests/research_live/test_evidence_budget.py -q
python -m pytest tests/reliability/test_workflow_control.py -q
```

然后展示总体结果（时间允许可现场运行）：

```powershell
python -m pytest tests -q
```

最终基线为 `361 passed`。说明预算是权威账本、Trace 是 best-effort 投影；NoProgress 观察阶段进展；TaskPolicy 能输出 CONTINUE/STOP/FALLBACK/REPLAN，但当前 Research 集成为 observer。

## 4. 可选在线演示

不建议在普通面试现场运行。确有稳定网络、已配置本地凭据且可以接受外部成本时：

```powershell
python run_research.py `
  --profile config/research_profiles/special_equipment_validation.toml `
  --policy config/research_policies/default.toml `
  --workspace workspace `
  --max-candidates 8 `
  --max-sources 3
```

该命令会执行 Search/Acquire，不能保证第三方站点当场可用。不要为了局部失败连续重跑完整任务。

对已有 run 做 LLM 预检（不调用模型）：

```powershell
python run_research.py `
  --profile config/research_profiles/special_equipment_validation.toml `
  --workspace workspace `
  --llm-preflight-run kr_20260828T082105547457Z_b40bc521
```

真实 LLM synthesis 入口为 `--llm-synthesis-run`，会产生一次模型调用。现有工件已经完成这一步，演示时无需再次执行。

## 5. 常见追问的现场回答

**为什么不直接把网页摘要喂给 RAG？**

因为摘要不是原始事实来源，且无法验证模型是否删改信息。系统保留 HTML/PDF 字节、`raw_file_hash`、可定位 Evidence 和 `content_hash`，再从同一 Evidence 生成所有输出。

**为什么不用 LLM 自由规划所有阶段？**

公开资料调研的关键不是最大自由度，而是限制 Search/Download 数量、保存证据和可重复测试。LLM 仍可替换 Synthesizer，但流程阶段由代码确定。

**为什么说可靠而不是生产级？**

因为已有结构化错误、重试、超时、预算、进度、轨迹和策略组件，以及 361 项回归；但全局执行接管、分布式状态、语义蕴含校验和大规模压力验证仍未完成。

## 6. 演示截图建议

准备以下 5 张截图即可：

1. README 总体架构 Mermaid；
2. `run_manifest.json` 中 7/3/2/1/22 的真实指标；
3. 一条 Evidence 的 source locator 与双 hash；
4. selection report 的 22 → 6 与 LLM metrics；
5. `361 passed` 的最终测试输出。

截图中不要包含 `config/config.toml`、API Key、Authorization Header、环境变量或本机绝对路径。
