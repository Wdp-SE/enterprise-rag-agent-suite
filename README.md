# Enterprise RAG & Reliable Agent Suite

这是一个面向企业研发资料的 AI 工程化作品集，由版本化 RAG 知识底座、证据驱动文档工作流 Agent 和统一 Streamlit 界面组成。

## 项目组成

- [`RAG-Challenge-2-main`](RAG-Challenge-2-main/)：企业文档可信知识库与问答系统，覆盖通用多文档检索、中文 OCR、版本感知检索、可追溯引用、评测与 Trusted QA。
- [`OpenManus-rag`](OpenManus-rag/)：基于 RAG 的企业研发文档起草与审核工作流 Agent，覆盖 Scope、Evidence Sufficiency、字段草稿、单审核人闭环、正式输出门禁、Checkpoint/Resume 和 Evidence Freshness。
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


## RAG V3 生命周期增强

当前版本增加稳定 Document / DocumentVersion 模型、单 ACTIVE 约束、默认 ACTIVE-only 检索、项目/类型/多文档/历史版本 Scope、增量 Section 变更检测、内容哈希 Embedding 复用、确定性 Version Diff，以及 Agent Resume Evidence Freshness。冻结的 DENSE_ONLY + SECTION_PATH 检索数学保持不变。

V3 使用 data/synthetic_versioned_corpus 下的公开合成数据完成离线 E2E；没有把真实内部资料发送给在线模型。工程报告位于 project_delivery/rag_v3_lifecycle/v3_engineering_report.md。

