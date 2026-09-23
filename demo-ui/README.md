# 研发变更审查工作台（Streamlit）

本界面把版本可信研发知识服务与人工审查 Agent 组织成一条业务路径：选择需求变更案例 → 分析影响与引用依据 → 审核局部修改 → 校验候选版本并安全发布。业务判定、检索和发布仍由现有 RAG / Agent 服务执行；界面只读取和展示真实状态。公开演示只使用合成资料。

![公开合成资料下的工作台首页](../project_delivery/ui_product_experience/public_workbench.png)

## 从新克隆仓库启动

先按[根目录 Quick Start](../README.md)创建 Python 3.12 环境并安装依赖，然后在仓库根目录执行：

```powershell
.\start_prototype.ps1
```

打开 http://127.0.0.1:8502。脚本使用已跟踪的 `RAG-Challenge-2-main/public_demo_artifacts/rd-v2-public-demo-v1`，将候选版本、上传与输出写入系统临时目录；不需要私有原文、旧 `runtime/` 或个人 API Key。端口被占用时可传入 `-RagPort` 和 `-UiPort`。

## 手动启动

以下命令假定已安装根目录 Quick Start 的依赖，分别在两个 PowerShell 窗口运行。

RAG 窗口，从仓库根目录进入 `RAG-Challenge-2-main`：

```powershell
cd RAG-Challenge-2-main
$env:APP_ENV = 'public_demo'
$env:RD_V2_PROJECT_ROOT = (Get-Location).Path
$env:RD_V2_ARTIFACT_ROOT = (Resolve-Path 'public_demo_artifacts\rd-v2-public-demo-v1').Path
$env:RD_V2_ALLOW_EXTERNAL_GENERATION = 'false'
$env:RD_V4_VERSION_STORE_ROOT = Join-Path $env:TEMP 'rag-agent-public-candidates'
New-Item -ItemType Directory -Path $env:RD_V4_VERSION_STORE_ROOT -Force | Out-Null
.\.venv\Scripts\python.exe -m uvicorn src.rd_v2_api:app --host 127.0.0.1 --port 8765
```

UI 窗口，从仓库根目录进入 `demo-ui`：

```powershell
cd demo-ui
$env:APP_ENV = 'public_demo'
$env:RAG_API_BASE_URL = 'http://127.0.0.1:8765'
$env:DEMO_RUNTIME_ROOT = Join-Path $env:TEMP 'rag-agent-public-ui'
$env:DEMO_ALLOW_RAG_QUERY = 'false'
..\OpenManus-rag\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8502
```

## 界面与演示路径

首页“工作台”展示系统定位、案例选择、实时文档与版本状态。选择 Case A（并发 500 → 1000）或 Case B（审计日志 7 → 30 天），点击“开始分析”，再在“变更分析”运行现有工作流。到“修改审核”并排检查修改前、建议修改和关联 Evidence，填写审核意见并批准、编辑或驳回。到“版本发布”应用已批准修改，检查候选版本和确定性门禁，再安全发布。

“知识检索”可演示版本范围内的原始证据与差异；“执行轨迹”“评测结果”用于解释过程；“扩展工具”保留 Word 模板起草与审核流程。公开资料默认禁用需要在线模型的 `/query`，主审查流程不依赖 DashScope Key。完整首次使用步骤见[演示流程](../project_delivery/ui_product_experience/demo_user_flow.md)。

## 公网配置

Streamlit Community Cloud 的入口是 `demo-ui/app.py`，Python 3.12。把 [Secrets 示例](.streamlit/secrets.toml.example)中的配置项填入平台设置，将 `RAG_API_BASE_URL` 设为实际 Render URL；不要提交真实 `secrets.toml`。现有服务与部署核对步骤见[部署指南](../project_delivery/public_value_prototype/free_deployment_guide.md)。

## 验证与边界

```powershell
..\OpenManus-rag\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests -q
```

Scope 是业务范围约束，不等同 ACL/RBAC；Evidence 提供可追溯来源，不自动证明结论正确；疑似影响始终是人工审核建议。当前是单审核人原型，原始 DOCX 不被局部修改流程覆盖。用户资料和运行输出不得提交到公开仓库。
