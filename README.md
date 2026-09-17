# Enterprise RAG & Reliable Agent Suite

这是一个面向企业研发资料的 AI 工程化作品集，包含两个相互独立、可组合运行的项目，以及统一的 Streamlit 演示界面。

## 项目组成

- [`RAG-Challenge-2-main`](RAG-Challenge-2-main/)：企业文档可信知识库与问答系统，覆盖通用多文档检索、中文 OCR、版本感知检索、可追溯引用、评测与 Trusted QA。
- [`OpenManus-rag`](OpenManus-rag/)：基于 OpenManus 的可靠任务执行 Agent，覆盖知识调研 Workflow、证据包、任务策略、超时重试、预算、无进展检测和结构化 Trace。
- [`demo-ui`](demo-ui/)：统一调用两个项目公开边界的 Streamlit 展示层。

## 数据与安全边界

仓库不包含个人 API Key、真实企业研发文档、真实语料的解析文本、向量索引或本地运行输出。公开演示应使用合成、公开或已获授权的数据；`.env.example` 仅提供变量名，不包含凭据。

## 运行入口

分别阅读以下说明：

- [RAG 项目说明](RAG-Challenge-2-main/README.md)
- [Agent 项目说明](OpenManus-rag/README.md)
- [统一 UI 说明](demo-ui/README.md)

## 开源声明

两个子项目均基于 MIT License 项目进行二次开发。原始许可证和著作权声明保留在各自子目录中，README 记录了二次开发范围、验证结果与能力边界。

