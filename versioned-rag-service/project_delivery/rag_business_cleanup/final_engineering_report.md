# 企业研发文档 RAG 业务收口最终工程报告

生成日期：2026-09-18

## 1. 最终结论

RAG-Challenge-2-main 已收敛为单一业务产品：企业研发文档知识服务。

唯一正式检索策略为 DENSE_ONLY + SECTION_PATH。正式运行链只包含 ingestion、document lifecycle、version governance、incremental update、scope retrieval、version diff、trusted QA、citation 和 artifact validation。

竞赛模式、候选工作流、旧公司专用逻辑、旧词法/混合/重排生产实现、原型运行时、无关示例和根目录实验脚本已经从受版本控制的业务代码库移除。删除后未增加新业务功能。

## 2. 恢复点与删除授权

- 清理前提交：6860b0da45b545ffa4ce376771d76ed801646742。
- 本地恢复标签：backup/pre-rag-business-cleanup-20260918。
- 标签解引用后指向上述提交。
- 用户明确批准 legacy_removal_manifest.json 中 302 个文件。
- 删除路径集合 SHA-256：7294dcbd12c8d802ec32cf570a4b38cc5b0d68b4c793b0357614f2500f508489。
- 每个文件在删除前均重新核对路径、Git 跟踪状态、字节数和 SHA-256。
- 正式 Python 导入闭包对清单文件的引用数为 0。

## 3. 实际删除结果

- manifest 文件数：302。
- 实际删除文件数：302。
- manifest 删除后残留：0。
- 因正式 Runtime、测试、Agent、UI 或 E2E 引用而保留的例外：0。
- 最终 Git 删除项：302，与批准清单完全相等。
- 删除文件总大小：8,757,575 字节。

分类：

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

Safe E2E 在执行时临时清空了 6 个旧 Agent DOCX。它们不在 RAG manifest 中，已从当前 HEAD 原样恢复，因此未扩大删除范围。

## 4. 正式代码收口

### 4.1 唯一入口

main.py 只保留六个正式命令：

- serve
- validate-artifacts
- ingest-version
- activate-version
- diff
- catalog

不再存在竞赛问题处理、公司路由、通用问答模式、原型脚本或并行实验入口。

### 4.2 检索

src/rd_v2_runtime.py 固定并验证：

- retrieval_policy = DENSE_ONLY
- dense_representation = SECTION_PATH
- 归一化 Dense 向量和稳定排序
- 查询前 RetrievalScope 候选过滤
- 冻结资产的状态、哈希、数量、维度与单位范数校验
- ACTIVE/SUPERSEDED 版本约束

资产策略中若启用词法检索、混合融合或重排器，运行时会拒绝加载。这些名称只保留为 fail-closed 策略校验字段和防回归测试输入，不存在对应生产实现。

### 4.3 上下文与回答

- context_expansion.py 只接受已校验冻结分块。
- 邻近扩展按 document_id、version_id、section_id 隔离。
- 输出只传播 Dense 分数；旧词法、融合和重排分数字段会被删除。
- answer_generation.py 只支持证据约束的结构化研发文档回答。
- 外部生成默认关闭；未配置安全授权时 /query 返回数据策略禁用状态。
- 引用必须属于本次 Evidence 的 document_id 与 page_number。

### 4.4 文档生命周期

document_lifecycle.py 提供：

- 稳定文档身份
- ACTIVE/SUPERSEDED 版本治理
- 规范化 SectionSnapshot ingestion
- 内容哈希向量复用
- 活动索引原子刷新
- 项目、类型、文档、版本范围检索
- ADDED、REMOVED、MODIFIED、UNCHANGED 章节差异

正式 ingestion 边界是规范化章节、源文件字节和经审计的向量映射，不宣称支持任意格式文件的通用解析。

### 4.5 Trusted QA

- 信号收集不再依赖旧 versioning 包。
- 包导出边界不再包含候选策略、历史 Holdout 评估或旧 shadow evaluator。
- 结构化输出错误、无有效引用和伪造引用在 ENFORCE 模式下失败关闭。
- Trusted QA 不声明完成语义蕴含证明。

### 4.6 本地运行可靠性

本地查询嵌入继续使用 spawn 子进程隔离 PyTorch/Transformers 与 FAISS。UI Smoke 发现 Ctrl+C 停服时子进程会打印 KeyboardInterrupt 堆栈，已补充 EOFError、KeyboardInterrupt 与 OSError 的优雅退出处理。复测后服务与子进程无堆栈关闭。

## 5. 最终核心目录

    RAG-Challenge-2-main/
    ├── main.py
    ├── src/
    │   ├── answer_generation.py
    │   ├── artifact_lifecycle.py
    │   ├── context_expansion.py
    │   ├── document_lifecycle.py
    │   ├── local_embedding_worker.py
    │   ├── native_runtime.py
    │   ├── rd_v2_api.py
    │   ├── rd_v2_runtime.py
    │   └── trusted_qa/
    │       ├── audit.py
    │       ├── enforcement.py
    │       ├── models.py
    │       ├── policy.py
    │       └── signals.py
    ├── scripts/
    │   ├── build_rd_v2_final_artifact_manifest.py
    │   ├── run_rd_v2_offline_runtime_smoke.py
    │   ├── run_v3_scope_benchmark.py
    │   ├── run_v3_versioned_e2e.py
    │   └── validate_retrieve_api.py
    ├── tests/
    │   ├── test_document_lifecycle_v3.py
    │   ├── test_formal_runtime_contract.py
    │   ├── test_rd_v2_engineering_hardening.py
    │   └── test_rd_v3_runtime_api.py
    └── docs/
        ├── architecture.md
        ├── incremental_update.md
        ├── known_limitations.md
        ├── native_runtime_notes.md
        ├── retrieval_api.md
        ├── retrieval_design.md
        ├── retrieval_scope.md
        ├── version_diff.md
        └── version_governance.md

最终 src 为 15 个 Python 文件、2,849 行；正式脚本 5 个；测试文件 4 个；业务文档 9 份。

## 6. 完整验证结果

### RAG

- compileall：PASS。
- 正式模块 import：PASS。
- 全部保留测试：34 passed / 0 failed。
- Frozen Artifact 校验：PASS。
- 正式资产：3 documents、3 versions、5,090 chunks。
- 检索策略：DENSE_ONLY。
- Dense 表示：SECTION_PATH。
- 离线 Runtime Smoke：PASS。
- retrieved_trace_count：10。
- 在线模型调用：false。
- 请求正文日志：false。
- 真实 HTTP /retrieve 校验：4 queries，全部字段、内容哈希、排名、分数和资产一致性通过。

### 文档生命周期 Safe E2E

- 数据策略：SYNTHETIC_OFFLINE。
- 在线模型调用：false。
- V1 新建：3 个新章节、3 个新向量。
- V2 增量：1 个未变章节复用向量，1 个修改、1 个新增、1 个删除，2 个新向量。
- Scope 检索：指定文档范围只返回 DESIGN-001。
- Version diff：ADDED 1、REMOVED 1、MODIFIED 1、UNCHANGED 1。
- 总体状态：PASS。

### Scope benchmark

- corpus_chunks：5,090。
- documents：3。
- versions：3。
- 资产与目录启动：312.507 ms。
- 全部 ACTIVE 检索中位数：7.568 ms。
- 单文档范围检索中位数：2.897 ms。
- repeats：10。
- 不包含查询 Embedding 耗时，不声明生产 QPS。

### Agent 与 RAG 集成

- Agent Core + Reliability：112 passed / 0 failed。
- Agent Safe Business E2E：PASS。
- multi_evidence_draft：true。
- missing_fail_closed：true。
- section_reject：true。
- rejected section 阻断正式输出：true。
- 全部批准后生成 approved.docx：true。
- 真实 Agent HTTP /retrieve 工作流：PASS。
- RAG 调用数：4。
- 唯一 Evidence：14。
- 4 个模板章节完成草稿并进入 REVIEW_REQUIRED。
- 真实集成使用 Safe Integration 合成资产，未调用在线模型。

### Streamlit UI

- UI tests：12 passed / 0 failed。
- 仅有 pytest cache 写权限和 pytest-asyncio future-default 提示，不影响测试。
- AppTest 真实页面控件检索：PASS。
- 返回 Evidence：5。
- 返回文档：safe-demo-12p、safe-project-plan。
- Evidence 版本状态：全部 ACTIVE。
- Streamlit /_stcore/health：200 / ok。
- Streamlit 首页：200，页面识别成功。
- RAG /health：READY。
- Artifact：COMPLETE。
- Live Smoke 后测试服务已关闭。

### 环境与补丁

- RAG pip check：No broken requirements found。
- Agent pip check：No broken requirements found。
- Git 删除集合与 manifest：302 = 302。
- git diff --check：PASS。

## 7. Secret Scan

扫描范围为当前 Git 跟踪文件和非忽略的未跟踪文件，不扫描 .git、虚拟环境、运行时缓存或被 .gitignore 排除的本地私有数据。

- 扫描文本文件：168。
- 跳过二进制文件：13。
- 模式命中：2。
- 人工核对 false positive：2。
- 确认密钥：0。
- 最终状态：PASS_AFTER_REVIEW。

两条命中均位于 Reliability 测试，内容是用于验证密码、Cookie 和 Token 脱敏逻辑的显式伪凭据，不是可用密钥。扫描报告不保存命中正文，只保存文件、行号、规则与行哈希。

## 8. 删除范围外的本地残留

为严格遵守 302 文件 manifest，未删除清单外的忽略文件和空目录：

- src/versioning：仅旧 __pycache__。
- src/evaluation：仅旧 __pycache__。
- candidate_knowledge：仅空目录。
- examples：仅空目录。
- data/rd_v2_prototype：仅空目录。
- data/rd_v2_corpus：正式本地语料和冻结资产。
- 根目录运行情况.txt、env：本地未跟踪文件。

这些内容不属于 Git 业务代码，不会上传 GitHub，也不参与 import、测试或运行。若以后希望清理本机缓存，应单独建立新清单；本轮没有越过已批准删除范围。

## 9. 证据文件

- legacy_removal_manifest.json：批准的 302 文件及逐文件哈希。
- pre_deletion_audit.json：删除前依赖与哈希审计。
- deletion_execution.json：实际删除记录。
- post_cleanup_audit.json：删除后依赖、范围与目录审计。
- secret_scan.json：脱敏 Secret Scan 结果。
- v3_scope_benchmark_post_cleanup.json：删除后范围检索基准。
- v3_versioned_e2e_post_cleanup/e2e_result.json：删除后生命周期 E2E 结果。
- agent_safe_e2e/e2e_result.json：删除后 Agent Safe Business E2E 结果及对应 DOCX。

## 10. 最终验收矩阵

    SINGLE_BUSINESS_SCOPE = YES
    BUSINESS = 企业研发文档知识服务
    FORMAL_RETRIEVAL = DENSE_ONLY + SECTION_PATH
    COMPETITION_RUNTIME = REMOVED
    CANDIDATE_WORKFLOW = REMOVED
    LEGACY_COMPANY_ROUTING = REMOVED
    BM25_PRODUCTION_PATH = REMOVED
    HYBRID_PRODUCTION_PATH = REMOVED
    RERANK_PRODUCTION_PATH = REMOVED
    PROTOTYPE_RUNTIME = REMOVED
    ROOT_EXPERIMENTAL_SCRIPTS = REMOVED
    INGESTION = PASS
    DOCUMENT_LIFECYCLE = PASS
    VERSION_GOVERNANCE = PASS
    INCREMENTAL_UPDATE = PASS
    SCOPE_RETRIEVAL = PASS
    VERSION_DIFF = PASS
    TRUSTED_QA = PASS
    CITATION_MEMBERSHIP = PASS
    ARTIFACT_VALIDATION = PASS
    RAG_TESTS = 34 passed
    AGENT_TESTS = 112 passed
    UI_TESTS = 12 passed
    SAFE_E2E = PASS
    AGENT_RAG_INTEGRATION = PASS
    UI_LIVE_SMOKE = PASS
    SECRET_SCAN_CONFIRMED_SECRETS = 0
    MANIFEST_FILES = 302
    DELETED_FILES = 302
    SKIPPED_REFERENCED_FILES = 0
    GIT_DIFF_CHECK = PASS
    PRODUCTION_READY = NO CLAIM

## 11. 已知边界

- ingestion 从规范化 SectionSnapshot 开始，不包含任意 PDF、扫描件或 Office 文件的通用解析。
- 外部回答生成默认关闭；开启后必须确认数据允许发送至配置的在线模型。
- Scope 是业务检索范围，不替代 ACL、RBAC 或租户隔离。
- 当前规模使用精确向量矩阵刷新；更大规模索引需要单独性能设计。
- 现有 Safe Integration 合成资产用于 UI 与 Agent 集成验证，不是生产业务数据。
- 本轮完成后停止增加功能。
