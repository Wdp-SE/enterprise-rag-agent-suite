# 运行手册

## 1. 环境要求

- Python：`>=3.12,<3.13`（最终验证环境为 3.12.13）
- pip：最终验证环境为 25.0.1
- Docker Desktop / Docker Engine：仅 Sandbox 测试和相关功能需要
- 网络：只有在线 Search、Browser、下载和真实 LLM synthesis 需要
- 操作系统：Windows 已完成 Docker named-pipe 回归；Linux/macOS 需使用各自虚拟环境激活命令

不要复用系统 Python 3.11 运行本项目测试。

## 2. 建立环境

### Windows PowerShell

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
Copy-Item config/config.example.toml config/config.toml
python -m pip check
```

### Linux/macOS

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
cp config/config.example.toml config/config.toml
python -m pip check
```

为避免大量依赖漂移，已有可用环境不要无目的执行全量 `--upgrade`。`config/config.toml` 是本地配置，已被 `.gitignore` 排除；不要提交 API Key、Authorization Header 或真实凭据。

## 3. 基础 smoke

```powershell
python -c "from app.agent.manus import Manus; from app.agent.knowledge_research import KnowledgeResearchAgent; print('imports ok')"
python main.py --help
python run_research.py --help
python -m pip check
```

已知：`openmanus.exe --help` 可能因既有 setup.py console entrypoint 问题失败。当前使用 `python main.py`，该问题不阻断 Research Workflow。

## 4. 测试命令

始终使用 `python -m pytest`，保证 pytest 与当前虚拟环境一致。

```powershell
# Minimal Core
python -m pytest tests/research -q

# Live Workflow
python -m pytest tests/research_live -q

# Reliability Phase 1A–1D
python -m pytest tests/reliability -q

# Docker Sandbox
docker info
python -m pytest tests/sandbox -q

# 全项目
python -m pytest tests -q
```

最终基线：Minimal Core 41、Live Workflow 78、Reliability 214、Sandbox 28，共 361 passed。

## 5. 离线演示

离线演示不调用 Search、Browser、下载、LLM 或 RAG。

```powershell
python main.py --help
python run_research.py --help
python -m pytest tests/research/test_offline_e2e.py -q
python -m pytest tests/research_live/test_workflow.py -q
python -m pytest tests/reliability/test_workflow_control.py -q
```

真实运行工件位于：

```text
workspace/research_runs/kr_20260828T082105547457Z_b40bc521/
├── evidence/evidence.json
├── raw_sources/
└── outputs/
    ├── run_manifest.json
    ├── research_report.md
    ├── structured_result.json
    ├── evidence_selection_report.json
    ├── research_report_llm.md
    ├── structured_result_llm.json
    └── llm_synthesis_metrics.json
```

合法 Candidate 契约 Fixture 位于：

```text
tests/fixtures/candidate/valid_candidate/
```

## 6. 运行受限规模的在线 Research Workflow

运行前：

1. 复制并填写本地 `config/config.toml`；
2. 检查 Search/LLM provider 的实际模型和网络权限；
3. 确认本次任务允许外部访问与成本；
4. 保持 `max-candidates <= 8`、`max-sources <= 3`。

```powershell
python run_research.py `
  --profile config/research_profiles/special_equipment_validation.toml `
  --policy config/research_policies/default.toml `
  --workspace workspace `
  --max-candidates 8 `
  --max-sources 3
```

如需启用现有 Browser fallback：

```powershell
python run_research.py `
  --profile config/research_profiles/special_equipment_validation.toml `
  --policy config/research_policies/default.toml `
  --workspace workspace `
  --max-candidates 8 `
  --max-sources 3 `
  --browser-fallback
```

不要为一次局部失败连续重跑完整在线流程。先根据 run manifest 的 error code 在 Fixture 测试中复现并修复。

## 7. 对已有 Evidence 做 LLM 预检

下列命令只加载已有 run、执行确定性 EvidenceBudgetPlanner，不调用真实模型：

```powershell
python run_research.py `
  --profile config/research_profiles/special_equipment_validation.toml `
  --workspace workspace `
  --llm-preflight-run kr_20260828T082105547457Z_b40bc521
```

检查 `selected_estimated_tokens < max_evidence_budget`，并确认 selected prompt estimate 低于 context budget 且有安全余量。

真实 LLM 命令为：

```powershell
python run_research.py `
  --profile config/research_profiles/special_equipment_validation.toml `
  --workspace workspace `
  --llm-synthesis-run kr_20260828T082105547457Z_b40bc521
```

它会产生真实外部调用。现有 run 已经成功生成 LLM 结果，除非明确需要新的验证，不要重复执行。

## 8. 结果判读

### ResearchResult

- `COMPLETE`：目标流程完成且 Evidence 足够；
- `PARTIAL`：部分来源失败，但剩余 Evidence 足以生成有限结果；
- `INSUFFICIENT_EVIDENCE`：不应生成确定性专业 finding。

### Candidate

- `CREATED`：首次原子发布；
- `REUSED`：相同稳定输入已存在且验证通过；
- Validator `accepted=true`：包满足本地契约，不等于知识已审批。

### RAG Import

- 目标结果：`accepted=true, ingestion_performed=false`；
- 如果 rejected，应根据 issue code 修复 Agent 输出，不能绕过外部 Validator；
- 禁止调用 `approve_candidate()`、Embedding 或 FAISS 写入。

## 9. 常见故障

### `docker.from_env()` 失败

先执行 `docker info`。若 daemon 未运行，启动 Docker Desktop；不要 mock 或 skip Sandbox 测试。

### Windows `NpipeSocket` 问题

当前仓库已包含兼容补丁并有回归测试。如果再次出现 `_sock` AttributeError，检查是否运行了未包含该补丁的旧版本或错误虚拟环境。

### Python 版本错误

运行 `python --version` 和 `Get-Command python`。应使用项目 `.venv` 的 Python 3.12，不要用系统 3.11。

### 下载返回 403

按 `ACCESS_DENIED` 记录，优先换取其他已选来源或使用允许的 Browser fallback。不要对非幂等或明确拒绝请求无限重试。

### TLS EOF

若操作幂等且预算允许，可由 RetryPolicy 做有限重试。先区分短暂网络错误和证书/配置错误。

### 扫描 PDF

预期错误为 `UNSUPPORTED_SCAN_PDF`。首版不安装大型 OCR；换用文本版本或其他公开来源。

### Evidence 过大

先运行 `--llm-preflight-run`。Planner 不修改 EvidenceStore，只选择一次 synthesis 的输入子集。

### 真实 Candidate 目录无法访问

这可能是当前 Windows workspace 的局部 ACL。不要用破坏性命令强删；可以使用新的 workspace 重建，演示契约时使用 `tests/fixtures/candidate/valid_candidate`。

## 10. 清理原则

- `__pycache__`、`.pytest_cache`、日志与浏览器缓存属于可再生本地工件，可在打包副本中清理；
- `workspace/research_runs/kr_...` 是真实验证证据，不删除；
- `tests/fixtures` 是回归资产，不删除；
- `workspace/python`、`workspace/uv-cache` 体积可能很大，当前仅记录，不在不明确影响的情况下删除；
- 不对 ACL 异常目录执行递归强制删除；
- 清理前先确认目标绝对路径位于项目内。
