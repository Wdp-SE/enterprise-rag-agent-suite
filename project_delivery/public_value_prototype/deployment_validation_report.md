# 部署适配验证报告

## 结论

代码已具备 public profile、轻量 Artifact、远程 RAG URL、Session 隔离、只读 Baseline、冷启动处理和 LLM Budget。本轮没有创建真实 Render / Streamlit 应用，真实公网 URL Smoke 仍需所有者部署后执行。

本地 public profile 已验证：/health 为 READY / COMPLETE；Artifact 含 9 个合成文档、11 个版本、128 维向量；策略为 DENSE_ONLY + SECTION_PATH；只读 Smoke 返回当前版本 public-b-req-v2；跨案例 HTTP Evaluation 通过；Baseline SHA-256 前后一致。

## VALUE 与 DEPLOY

| ID | 检查 | 结果 |
| --- | --- | --- |
| VALUE-1 | Case A 完整流程 | PASS |
| VALUE-2 | Case B 复用同一核心流程 | PASS |
| VALUE-3 | 正式业务代码无 Case-specific branching | PASS |
| VALUE-4 | Case B 不读取 Case A Ground Truth | PASS |
| DEPLOY-1 | local configuration | PASS |
| DEPLOY-2 | remote RAG URL | PASS |
| DEPLOY-3 | Linux path / pathlib / /tmp profile | PASS |
| DEPLOY-4 | Session A / B isolation | PASS |
| DEPLOY-5 | Session 不修改 Baseline | PASS |
| DEPLOY-6 | restart reloads Baseline | PASS |
| DEPLOY-7 | UI survives unavailable backend | PASS |
| DEPLOY-8 | cold-start message | PASS |
| DEPLOY-9 | LLM Budget fail-closed | PASS |
| DEPLOY-10 | secrets absent | PASS，304 text / 24 binary / 0 hit |

## 完整回归

| 检查 | 结果 |
| --- | --- |
| RAG 全量 | PASS，53 passed |
| Agent 官方 tests 目录 | PASS，104 passed |
| UI 全量 | PASS，26 passed |
| Fixed Evaluation | PASS，7/7；Hit@5 / Recall@5 / MRR = 1.0 / 1.0 / 1.0 |
| Fixed Retrieval Latency | P50 64.330 ms；P95 68.384 ms |
| Cross-case HTTP Evaluation | PASS，Case A / B 各 15 项 |
| V4 Business Smoke | PASS，3 change / 3 confirmed / 1 suggested |
| Safe Business E2E | PASS |
| Versioned RAG E2E | PASS |
| Offline Runtime Smoke | PASS |
| Public read-only Smoke | PASS |
| Streamlit Smoke | /_stcore/health 200 ok；首页 200 |
| Human Review / Checkpoint / Freshness / Conflict / Idempotency | PASS，由 Agent 全量测试与跨案例评测覆盖 |
| compile/import | PASS，RAG / Agent / UI |
| pip check | PASS，两个环境均无破损依赖 |
| Secret Scan | PASS，0 potential match |
| git diff --check | PASS |

Agent 初次不带 tests 路径运行时，pytest 误收集了本地 workspace/uv-cache 内第三方 win32com 测试并触发访问冲突。该目录不是项目测试或本轮改动；按官方 tests 目录重跑后 104 项全部通过，未读取、清理或修改本地缓存。

## 依赖与启动

- Render 依赖：RAG-Challenge-2-main/requirements-render.txt
- Streamlit 依赖：demo-ui/requirements.txt
- Render Build：pip install -r requirements-render.txt
- Render Start：uvicorn src.rd_v2_api:app --host 0.0.0.0 --port $PORT
- Streamlit Entry：demo-ui/app.py

## 尚未声称完成

- 未创建公网服务或取得 Live Demo / API Docs URL。
- 未测试真实公网冷启动和端到端时延。
- 未配置真实 DashScope Secret。
- 未开展 3～5 人真实外部试用。
- 本地 P50/P95 不代表公网端到端延迟。
