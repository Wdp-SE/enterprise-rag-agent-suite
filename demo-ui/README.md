# PP-Human 研发知识工作台

Streamlit 工作台围绕 PP-Human 行人分析应用研发资料，提供版本化中文文档检索、来源浏览和变更影响候选审查。人工查询与 Agent 审查调用同一个 RAG API；Agent 只整理带来源的候选和缺口，工程师负责审核。工作台不会修改 PaddleDetection 上游内容。

## 当前范围

工作区限定为 PaddlePaddle/PaddleDetection 的 PP-Human 官方中文教程和关联配置，版本 v2.5.0–v2.9.0（含 v2.8.1），默认最新版 v2.9.0。导入 83 条版本来源、14 个主题和 761 个检索片段；图片、视频、模型权重和第三方数据集不在检索范围。PP-Human 专项评测待完成，因此不展示其他语料的分数作为本场景成绩。

该项目用于说明 RAG 和 Agent 在计算机视觉应用研发资料检索与变更检查中的工程方案，不代表 PaddlePaddle 官方产品或真实企业审批系统，也不处理真人影像、身份信息或员工行为记录。

## 本地运行

先按[服务说明](../versioned-rag-service/README.md)启动 PP-Human RAG API，再从本目录启动：

```powershell
$env:APP_ENV = "public_demo"
$env:RAG_API_BASE_URL = "http://127.0.0.1:8765"
..\change-review-agent\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8502
```

工作台从 `/public/workspace` 读取知识空间身份和可用版本；当前页面仅接受 PP-Human 与中文语料。知识空间不匹配时会停止查询，避免返回其他领域的来源。

模型密钥只配置在 RAG 后端。审查结论需要人工审核；演示中的会话记录不具备企业身份权限或集中审批能力。线上发布需单独核对 Render 与 Streamlit 两端的构建版本和工作区指纹。
