# PP-Human 研发知识 RAG 与变更影响审查 Agent

面向 AI 应用开发岗位的垂直场景原型：围绕 PaddleDetection 中 PP-Human 行人分析流水线，研发人员可按官方版本检索中文技术资料；提出模型配置、行为分析、跟踪或部署变更后，Agent 调用同一 RAG 服务查找可能受影响的教程和配置，整理引用证据、验证建议与资料缺口，由工程师复核。

RAG 同时服务人工查询和 Agent。检索默认使用 BM25；版本、语言和来源在服务端约束。Agent 负责分类变更、拆分有限的检查问题、调用 RAG 并形成带证据的影响候选。没有证据时保留缺口，不把“未检索到”解释为“没有影响”，也不会写回公共资料或上游仓库。

## 当前语料

- 唯一发布方为 PaddlePaddle，仓库为 [`PaddlePaddle/PaddleDetection`](https://github.com/PaddlePaddle/PaddleDetection)，资料限定在 PP-Human 中文教程及直接使用的项目配置。
- 收录正式版本 v2.5.0、v2.6.0、v2.7.0、v2.8.0、v2.8.1 和 v2.9.0；当前默认版本为 v2.9.0。每条来源记录 release tag 对应 commit、仓库路径、SHA-256 和 Apache-2.0 许可出处。
- 语料包含 83 条版本来源、14 个文档主题和 761 个检索片段。v2.5.0 中有 1 个后来版本才出现的模型配置文件，审计清单将其记为该版本不存在，不用新版本内容补齐历史。
- 仅导入 Markdown 教程与必要 YAML 配置；不下载或再分发模型权重、视频、图片、个人数据或第三方数据集。
- 当前语料切换后，PP-Human 专项冻结评测仍待建立。旧语料的评测分数不代表 PP-Human 效果；README 和页面不会把待测数据说成准确率成绩。

该原型展示公开研发文档检索和变更审查方法，不代表 PaddlePaddle 官方产品或任何企业内部系统，也未接入企业工单、权限系统、真实视频和生产验证环境。它不分析真人影像、身份或员工行为数据。

## 业务闭环

1. 研发人员选择 PP-Human 已收录版本并查询模型、跟踪、行为分析或部署资料。
2. 变更审查按规则识别变更类别，围绕原始描述构造有限检索问题，并限定到目标版本和中文资料。
3. RAG 返回固定来源片段；Agent 将片段整理为可能受影响的材料、核查动作和证据缺口。
4. 工程师查看引用原文后确认、修改或驳回候选。系统不自动认定实际影响，也不修改上游资料。

## 主要组件

- `versioned-rag-service/`：FastAPI、按 release 固定的来源清单、中文 BM25 检索、引用追溯与来源完整性校验。
- `change-review-agent/`：PP-Human 变更类型规则、有限检索规划、证据校验与人工审核流程。
- `demo-ui/`：Streamlit 工作台，提供版本检索、来源浏览、变更候选和审核页面。
- `versioned-rag-service/public_corpus_pphuman/`：已构建的活动 PP-Human 语料、索引、版本快照和逐来源审计。
- `evaluation/`：历史试验保留作开发记录；PP-Human 专项评测尚未完成，不能引用历史业务语料指标作为当前成绩。

## 本地运行

需要服务端与工作台各自的 Python 依赖。服务默认读取 PP-Human 语料，生成能力由服务端环境变量和密钥配置控制；不在前端 secrets 中放模型密钥。

```powershell
Set-Location versioned-rag-service
$env:RAG_PUBLIC_CORPUS_ROOT = "public_corpus_pphuman"
$env:RAG_PUBLIC_RETRIEVAL_CONFIG = "public_corpus_pphuman/public_retrieval_runtime.json"
..\.venv\Scripts\python.exe -m uvicorn src.public_server:app --host 127.0.0.1 --port 8765
```

另开终端启动工作台：

```powershell
Set-Location demo-ui
$env:APP_ENV = "public_demo"
$env:RAG_API_BASE_URL = "http://127.0.0.1:8765"
..\change-review-agent\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8502
```

仓库根目录的 `start_prototype.ps1` 也已改为启动 PP-Human 后端语料。

## 来源更新

语料选择见 `versioned-rag-service/config/pphuman_source_selection.json`，领域与版本定义见 `pphuman_project.json`。重建脚本只接受官方 PaddleDetection 仓库，并要求输出路径为空：

```powershell
Set-Location versioned-rag-service
$env:PYTHONPATH = "."
python scripts/build_pphuman_corpus.py --repository-root <PaddleDetection本地仓库路径> --output <新的空目录>
```

构建新版本后，应先审查来源审计和版本差异，再重新构建评测集并验证 RAG/Agent；评测通过后才能更新线上语料配置。`render.yaml` 当前已指向本地代码中的 PP-Human 语料路径，但这次工作没有执行线上部署。

## 验证

```powershell
Set-Location versioned-rag-service
python -m pytest -q tests/test_pphuman_corpus.py tests/test_pphuman_server.py

Set-Location ..\change-review-agent
python -m pytest -q tests/test_pphuman_profile.py tests/test_change_request.py tests/test_public_review.py
```

发布前还需补齐并运行 PP-Human 的冻结检索与 Agent 评测，分别检查必需来源召回、版本正确率、引用有效率、无证据拒答和变更候选审核质量。

## 资料链接

- [PaddleDetection 官方仓库](https://github.com/PaddlePaddle/PaddleDetection)
- [PP-Human 中文快速开始](https://github.com/PaddlePaddle/PaddleDetection/blob/release/2.9/deploy/pipeline/docs/tutorials/PPHuman_QUICK_STARTED.md)
- [官方版本发布页](https://github.com/PaddlePaddle/PaddleDetection/releases)
- [Apache-2.0 许可证](https://github.com/PaddlePaddle/PaddleDetection/blob/release/2.9/LICENSE)
