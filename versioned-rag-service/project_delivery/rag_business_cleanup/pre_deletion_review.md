# RAG 业务收口：删除前审阅报告

生成时间：2026-09-18
状态：代码收口与删除前审计完成，永久删除等待用户对本轮新清单的明确批准。

## 目标边界

唯一业务为企业研发文档知识服务。唯一正式检索为 DENSE_ONLY + SECTION_PATH。

正式能力包括 ingestion、document lifecycle、version governance、incremental update、scope retrieval、version diff、trusted QA、citation 与 artifact validation。

移除范围包括竞赛模式、候选工作流、旧公司专用逻辑、词法与混合生产链、原型运行时、无关示例、根目录实验脚本及其专属测试和历史交付物。

## 恢复点

- Git 提交：6860b0da45b545ffa4ce376771d76ed801646742
- 本地恢复标签：backup/pre-rag-business-cleanup-20260918
- 清理开始前工作区：干净

## 已完成的正式代码收口

- 根 CLI 只保留 serve、validate-artifacts、ingest-version、activate-version、diff 与 catalog。
- 正式生成器改为独立的研发文档证据约束模块，不再导入旧 api_requests。
- 上下文扩展只接受已验证冻结分块，并按 document_id、version_id、section_id 隔离邻近内容。
- 上下文结果只保留 Dense 评分；旧词法、融合和重排字段会被剔除。
- Trusted QA 信号直接接收正式版本治理状态，不再依赖旧 versioning 包。
- Trusted QA 包不再导出候选评估和历史 Holdout API。
- 依赖配置已按正式运行链收敛，并保留本地 PyTorch/Transformers 查询嵌入依赖。
- README 与九份架构文档已改为唯一业务边界。

## 新删除清单

文件：legacy_removal_manifest.json

- 删除文件数：302
- 路径清单 SHA-256：7294dcbd12c8d802ec32cf570a4b38cc5b0d68b4c793b0357614f2500f508489
- root：3
- artifacts：7
- candidate_knowledge：6
- data：31
- docs：8
- examples：8
- project_delivery：9
- reports：115
- scripts：47
- src：42
- tests：26

清单为每个文件记录相对路径、字节数、文件 SHA-256 和删除原因。它不包含 .git、OpenManus-rag、data/rd_v2_corpus、本地未跟踪文件或用户业务数据。

## 删除前审计

pre_deletion_audit.json 的结果：

- 清单数量匹配：通过
- 路径唯一：通过
- 所有目标存在：通过
- 所有目标位于 RAG 项目内：通过
- 受保护路径检查：通过
- 302 个文件大小与 SHA-256：通过
- 正式 Python 文件 AST 解析：24/24 通过
- 正式导入闭包引用待删除模块：0
- 静态依赖审计结论：可删除

## 当前验证

- 正式文档生命周期、运行时、API 与新增契约测试：34 passed
- compileall：通过
- 正式模块导入：通过
- CLI 命令边界：通过
- git diff --check：通过

## 删除后的必做验证

批准并执行清单后，将继续完成：

- 清单删除数量与 Git 删除数量核对
- 仅保留目录结构与禁用业务标记扫描
- 全部保留测试
- V3 versioned E2E
- scope benchmark
- offline runtime Smoke
- retrieve API 校验
- Agent 核心与 Streamlit UI 回归
- git diff --check
- 最终工程报告

## 当前阻塞

自动审批拒绝了永久删除，因为本轮 302 文件清单是新生成的，不等同于此前批准的 506 文件清单，并且包含历史报告与旧交付物。需要用户明确批准 legacy_removal_manifest.json 中这 302 个文件后才能执行。
