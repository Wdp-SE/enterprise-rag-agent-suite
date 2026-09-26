# Final Public Prototype 报告

## 结论

项目已从单一演示脚本收口为可配置、可重复验证、可准备公网部署的软件工程 AI 原型。RAG 53、Agent 104、UI 26 项测试通过；固定评测 7/7，跨案例两套流程通过；本地 public profile 与只读 Smoke 通过。真实公网部署和真实用户试用尚未发生，不能假装已完成。

## 1. 为什么不是只针对 Case A 写死？

REQ-023、500/1000、文档名、章节和 Patch 只在 Demo 数据、测试或 Evaluation。DemoCase、Agent、RAG 和候选版本服务由输入配置和数据驱动，没有 Case A 业务分支。

## 2. Case B 验证了什么？

它用不同组织、项目、Requirement、变化类型、章节、Evidence、Patch 和资产组合，在不修改核心 Domain / Retriever / Agent 的情况下完成同一闭环，共 15 项检查通过。

## 3. 哪些是跨案例核心？

DOCX 结构处理、版本治理、ACTIVE/SUPERSEDED、Scope-aware DENSE_ONLY + SECTION_PATH、Evidence/Citation、Version Diff、Impact 分层、Evidence Budget、局部 Patch、Review、Conflict、Idempotency、Checkpoint、Candidate Validation 和 Safe Activation。

## 4. 哪些仍是 Demo 配置？

合成文档、ID、预期影响、Patch 文案、Case 标题、固定 Ground Truth、Public Artifact 和演示顺序。

## 5. 真实业务价值是什么？

把新旧研发资料混用和 AI 未经证据/审核修改文档的风险，转为可追溯、可阻断、可审核、可重复验证的流程原型。

## 6. 不能证明什么？

不能证明覆盖所有企业场景、真实数据准确率、人工/成本收益、生产吞吐、SLA 或公网性能。7/7、MRR=1.0 和跨案例全通过都只属于固定合成评测。

## 7. 为什么不能宣称生产级？

缺少认证、ACL/RBAC、持久数据库、企业 Connector、生产监控、备份、HA、密钥治理、审计与真实企业数据验证。

## 8. 为什么公网 Session 临时？

它用于独立体验且不长期保存用户操作，符合免费平台短生命周期，不承担企业持久化职责。

## 9. 为什么免费部署不用数据库？

Baseline 为合成只读数据，Session 允许重启后丢失；数据库/Redis 不增加本轮验证价值。

## 10. 如何保证用户互不污染？

UI 生成合法 session_id，Session 与 Case 使用独立目录；RAG public API 强制 Session Header，并按 Session 分配版本库。Baseline 只读。

## 11. 如何防止 LLM 滥用？

MAX_LLM_CALLS_PER_SESSION 配置上限，UI/API 均 fail-closed；超限明确提示且不返回假结果。

## 12. 如何管理 Secret？

仓库只存占位示例。真实 DASHSCOPE_API_KEY 由 Render Environment 或 Streamlit Secrets 注入，.env/secrets.toml 不提交。最终 Secret Scan 为 0 命中。

## 13. 后端不可用怎么办？

首页仍显示简介、Case 和 Backend Status；有限重试后显示冷启动提示与重新连接，不显示 traceback。

## 14. 平台重启后如何恢复？

只加载并校验 Git 内轻量 Artifact，不执行 OCR、模型下载或全量 Embedding 重建；新 Session 从 Baseline 开始。

## 15. 本地运行为何不受影响？

local/public_demo 使用同一代码，只由配置区分。本地默认仍是 RAG 127.0.0.1:8765、UI 127.0.0.1:8502。新鲜本地后端上的固定评测和 Streamlit Smoke 均通过。

## 16. 距真实企业部署还缺什么？

Authentication、ACL/RBAC、Persistent Database、Enterprise Connectors、Production Monitoring、Backup、HA、Secret Rotation、合规审计、容量规划和真实企业数据验证。

## 最终证据

- VALUE-1～4：PASS
- DEPLOY-1～10：PASS（真实公网创建不在本轮授权范围）
- Fixed Evaluation：7/7，MRR 1.0，P50 64.330 ms，P95 68.384 ms
- Cross-case：Case A / B 各 15 项 PASS，Baseline 不变
- Business / Safe Business / Versioned / Offline / Public / Streamlit Smoke：PASS
- compile/import、pip check、Secret Scan、git diff --check：PASS
- Public Artifact：9 个文件、34,035 bytes，无本机绝对路径
- 真实公网部署 / 外部试用：尚未执行
- 受保护目录：未读取、未修改、未暂存
