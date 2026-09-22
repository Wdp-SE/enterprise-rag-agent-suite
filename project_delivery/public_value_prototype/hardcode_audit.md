# Case Hardcode Audit

## 审计范围

只读搜索了 RAG-Challenge-2-main/src、OpenManus-rag/app、demo-ui、测试、脚本、合成资料与 Evaluation。关键词包括 REQ-023、500、1000、Case A 文件名、章节、Patch、Evidence 和预期影响。

## 分类

### SAFE_DEMO_DATA

- project_delivery/v4_change_impact_review/demo_data/*
- project_delivery/v4_change_impact_review/evaluation_dataset.json
- project_delivery/v4_change_impact_review/evaluation_results.json
- project_delivery/public_value_prototype/demo_cases/*
- Prototype Final 演示资料

这些值定义完全合成的 Case A / Case B 与固定回归 Ground Truth，不参与通用领域算法分支。

### TEST_ONLY

- RAG/Agent/UI 单元测试中的 500、1000、REQ/DES/TC 标识
- run_v4_business_smoke.py、run_v4_evaluation.py、run_cross_case_evaluation.py
- 版本生命周期离线 E2E 的合成容量数据

这些值只用于验证已知行为；expected impact 只在工作流完成后断言，不进入 Agent 提示。

### RUNTIME_CONFIGURATION

- demo-ui/services/demo_cases.py 提供轻量 DemoCase 加载入口。
- case-a.json / case-b.json 保存各自的文档、版本、目标编号、Patch 和候选版本。
- demo-ui/services/change_impact_client.py 只读取 DemoCase，不含 REQ-023、DES-014、500/1000、Case A 文件名或 Case 分支。
- OpenManus-rag/app/document_workflow/rag.py 中的 DemoRAGClient 是显式 demo/offline 夹具，与 HTTP 正式路径隔离。

审计前，Case A 编排值位于 change_impact_client.py 和一个 UI 占位文案；本轮已迁移到 DemoCase 配置并由回归测试锁定。

### BUSINESS_LOGIC_VIOLATION

未发现 RAG Retriever、Version Governance、Engineering Diff、Impact、Evidence Selection、Quality Gate、Patch、Review、Conflict、Idempotency、Checkpoint 或 Candidate Activation 根据 Case A 编号、500/1000 或固定 Evidence ID 做业务分支。

## 结论

BUSINESS_LOGIC_VIOLATION：0。

核心领域逻辑没有 Case-specific branching。Case A 和 Case B 的差异只存在于合成数据与轻量配置层。
