# Case B 设计说明

## 目标与变化

Case B 用独立合成资料验证同一核心流程可复用，不向 Agent 提供 Evaluation Ground Truth。

- 场景：审计日志留存周期从 7 天变为 30 天
- 组织 / 项目：demo_company_b / AUDIT
- Requirement：REQ-071
- Patch 目标：DES-031
- 已确认影响：DES-031、TC-207
- 疑似影响：OPS-031
- 候选版本：audit-design-v2

这是时间型合规要求变化，与 Case A 的容量和接口形态变化不同。

## 最小资料集

Case B 只增加既有系统支持的 DOCX：audit_requirements_v1/v2、audit_design_v1、audit_test_cases_v1、audit_runbook_v1。资料、清单和配置都在 demo_cases/case_b/，全部为合成数据。

## 复用与隔离

1. 使用正式 DOCX 结构解析器和同一 public-demo Artifact。
2. UI 只传 case_id；ChangeImpactClient 从 DemoCase 配置读取数据，没有 Case A/Case B 分支。
3. Agent 仍通过 HTTP 调用同一 RAG API。
4. 每次运行使用独立 session_id 和 case_id。
5. Baseline 只读，Patch、Review、Candidate 和模拟激活只写入 Session Workspace。
6. expected impact 只用于结果断言，不作为 Agent 输入。
7. Case B 没有修改 Domain、Retriever 或 Agent 核心模型。

Case B 证明两套结构和变化类型不同的合成案例复用了同一核心流程，不能证明覆盖所有企业研发场景。
