# 单项目研发知识工作台

Streamlit 工作台围绕一个工业视觉安全监控软件项目展示按代码版本查资料和变更影响审查的业务。目标公开来源为 `xbs0325/industrial-inspection`，固定提交 `6d0df954f26b1810910db9f50727ca8bd19afa9f`。它不是该项目官方产品，也不连接企业内部工单、身份系统或测试平台。

## 当前可用性

目标仓库未声明内容再分发许可证；目前没有任何源文件正文获准进入应用索引。工作区只提供来源、版本和许可状态元数据，0 份可检索来源、0 个片段。RAG 检索与 Agent 审查均禁用，UI 会明确说明许可证原因。不可把旧 Seeed/Jetson 语料或其历史成绩介绍成当前项目效果。

取得逐文件内容再分发许可并重新构建活动语料之后，RAG 才会开放；项目特定评测完成前，页面也不会展示其他业务语料的分数。

## 本地运行

先启动配置到 `public_corpus_industrial_inspection` 的 RAG API（详见[根目录说明](../README.md)），再启动 UI：

```powershell
$env:APP_ENV = "public_demo"
$env:RAG_API_BASE_URL = "http://127.0.0.1:8765"
..\change-review-agent\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8502
```

工作台从 `/public/workspace` 读取唯一项目身份、提交、语料状态和指纹。项目、仓库、许可状态或语言元数据不匹配时，公开演示会停止检索；语料仍待许可时，页面保留可浏览的状态说明，但禁用查询和审查。

审核记录只用于演示中的会话流程，不具备企业身份权限或集中审批留痕。代码库更新与 Render/Streamlit 部署是独立步骤，需分别核对线上构建 SHA。
