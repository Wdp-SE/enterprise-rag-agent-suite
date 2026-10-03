# 单项目版本化研发知识检索与变更影响审查

这是面向 AI 应用开发岗位的工程原型，目标业务聚焦在一个工业视觉安全监控软件项目：研发人员按固定代码版本查询应用设计、实现、配置、部署和测试资料；变更时，系统查找同一项目内可追溯的潜在影响项与证据缺口，交由工程师确认。RAG 用于人工查询，也计划供变更审查 Agent 调用。Agent 不自动修改项目源文件或上游仓库。

## 当前数据与可用状态

唯一目标项目是 [`xbs0325/industrial-inspection`](https://github.com/xbs0325/industrial-inspection)，当前固定到 `main` 提交 `6d0df954f26b1810910db9f50727ca8bd19afa9f`。GitHub API 未返回许可证信息，仓库根目录也没有 LICENSE 文件；逐文件审计因此没有批准任何正文再分发。当前活动语料仅含项目元数据：**0 份可检索来源、0 个检索片段**，`rag_ready=false`。RAG 的搜索/生成接口会以 `PROJECT_CORPUS_INACTIVE_LICENSE_PENDING` 拒绝调用，避免把未授权内容复制到公开服务。UI 会显示许可阻塞的具体原因。

取得明确的内容再分发许可后，才可针对逐文件清单启用正文入库；此后再建立绑定同一仓库提交、解析器、索引策略和冻结题集的检索/审查评测。现在没有可代表该项目的 RAG 或 Agent 性能数字。仓库中旧领域（Seeed/Jetson）的语料、代码分支和评测文件属于历史材料，不是当前活动语料、业务介绍或成绩。

## 工程边界

- 一个主项目、一个固定 Git 提交；索引来源必须符合该项目的路径 allowlist，并带发布者、许可证审核记录、commit、文件哈希和来源定位。
- 许可证未批准、版本或哈希不一致、语料为空时，查询默认关闭；不回退到另一项目语料。
- 第三方引用只进入单独的依赖参考登记流程，必须单独审核、过滤和展示，不混入主项目检索结果或影响排序。
- 证据不足时保留缺口并要求人工确认；不能把语义相关说成已确认的依赖或影响。
- 这仍是公开资料原型，不连接企业工单、身份权限或真实审批平台，不代表生产环境验证。

## 技术组成

- `versioned-rag-service/`：FastAPI 服务、来源审计、许可门禁、版本固定和受约束的知识索引。
- `change-review-agent/`：变更分析与人工审核流程代码；需在主项目正文获准入库后，才能验证当前业务场景下的 RAG 联动效果。
- `demo-ui/`：Streamlit 工作台；后端已连接但语料不可用时会显示许可状态并禁用检索和审查。
- `versioned-rag-service/config/industrial_inspection_project.json`：唯一项目、提交、路径和许可审核定义。
- `versioned-rag-service/public_corpus_industrial_inspection/`：元数据声明和空索引，不含上游项目正文。
- `versioned-rag-service/scripts/audit_project_source.py` 与 `scripts/build_project_corpus.py`：审计固定版本并仅为逐文件明确批准的正文构建隔离语料。

## 本地运行

Python 3.12 环境安装服务与 UI 的依赖后，可启动 RAG API 和 Streamlit。当前运行预期是服务在线、工作区元数据可查看，但检索与生成不可用，直至许可证确认并重新构建/评测语料。

```powershell
$env:RAG_PUBLIC_CORPUS_ROOT = "public_corpus_industrial_inspection"
$env:RAG_PUBLIC_RETRIEVAL_CONFIG = "public_corpus_industrial_inspection/public_retrieval_runtime.json"
Set-Location versioned-rag-service
..\.venv\Scripts\python.exe -m uvicorn src.public_server:app --host 127.0.0.1 --port 8765
```

另开 PowerShell 窗口启动工作台：

```powershell
$env:APP_ENV = "public_demo"
$env:RAG_API_BASE_URL = "http://127.0.0.1:8765"
Set-Location demo-ui
..\change-review-agent\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8502
```

模型密钥只配置在 RAG 后端进程；没有可用语料时，API 会先拒绝检索，不会调用模型。

## 发布状态

`render.yaml` 已指向唯一项目的元数据语料；`/health` 应报告 `rag_ready=false`，`/public/workspace` 应报告单仓库、0 来源和许可阻塞状态。此状态不是可用于面试官实际检索的公开演示。将来上线可查询版本之前，需先取得许可或改选具有明确再分发许可的单一项目，并完成当前语料的冻结评测。代码更新、RAG 服务部署与 Streamlit 部署需分别核对，不应把旧的在线页面当作当前项目版本。

- [GitHub 源码](https://github.com/Wdp-SE/enterprise-rag-agent-suite)
- [RAG API 文档](https://version-aware-rag-public-demo.onrender.com/docs)（以服务当前部署状态为准）
- [RAG 服务说明](versioned-rag-service/README.md)
- [Streamlit 工作台说明](demo-ui/README.md)
- [单项目来源许可审计](versioned-rag-service/project_delivery/industrial_inspection_source_audit.json)
- [单项目边界实施计划](docs/superpowers/plans/2026-10-03-single-project-corpus-boundaries.md)
