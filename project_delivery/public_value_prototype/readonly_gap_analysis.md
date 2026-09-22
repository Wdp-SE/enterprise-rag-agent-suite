# Public Deployment + Value Validation 只读差距分析

## 基线

- 分支分析起点：`34aba8a feat: finalize RAG agent interview prototype`
- 恢复标签：`backup/pre-public-value-prototype-20260922`
- 受保护目录 `OpenManus-rag/runtime/` 与 `project_delivery/interview_guide/` 只核对 Git 状态，未读取、修改、移动或清理。

## A. 价值验证

1. `REQ-023`、500、1000、`DES-014`、固定 DOCX 和固定 Patch 文案没有进入 RAG/Agent 领域算法，但进入了 `demo-ui/services/change_impact_client.py` 和页面占位文案。该适配器当前只能编排 Case A。
2. 固定值在 DOCX、`engineering_inventory.json`、测试、Smoke 和固定 Evaluation 中属于安全合成数据；`OpenManus-rag/app/document_workflow/rag.py` 中的相同数字属于明确命名的离线 `DemoRAGClient`。领域层没有按编号或数值分支。
3. 当前没有 Case 描述入口；更换案例需要修改 `ChangeImpactClient`，因此尚不能无代码切换第二套案例。
4. 固定 Evaluation 只覆盖 Case A，和 `evaluation_dataset.json` 的 Ground Truth 强绑定。它适合回归，不足以证明跨案例复用。
5. Version Diff、Impact、Quality Gate、Review、Patch Apply、Candidate Build/Activation 均由传入模型与文档驱动；但 Case A 的 PatchCandidate 组装参数由 UI 适配器硬编码。
6. UI 直接显示 PAYMENT、demo_company_a 和 `REQ-023 500→1000`，案例选择未抽象。
7. 已有可复用边界包括 `OrganizationProfile`、EngineeringItem、TraceLink、HTTP Candidate API、Workflow Scope 和 `ChangeImpactReviewFacade`；缺少的只是轻量 DemoCase 描述。
8. 可以在不增加新领域模型的情况下增加 Case B：复用现有五种文档类型、同一 Parser、Diff、Impact、Evidence、Patch、Review 和 Candidate 流程。

## B. 公网部署

9. 本地默认 URL 位于 `demo-ui/config.py` 和 PowerShell 启动脚本；它们适合作为 local 默认值，但尚不接受规范名 `RAG_API_BASE_URL`。
10. 正式 Python 路径主要使用 `pathlib`。PowerShell 脚本是明确的 Windows 本地入口；Python Runtime 没有写死 E:/C:。`RDV2Settings` 在未配置项目根时依赖当前工作目录，应由 Render 显式配置或从代码位置解析。
11. Agent 通过 `HTTPRetrieveClient` 读取 UI 配置中的 RAG URL，保持 HTTP 边界。
12. Qwen Key 只由 `DASHSCOPE_API_KEY` 环境变量读取，没有硬编码。
13. Streamlit 当前把上传、Checkpoint、Patch 和输出写入同一个 `DEMO_RUNTIME_ROOT`；`@st.cache_resource` 还会跨 Session 共享 Agent/ChangeImpact 客户端。
14. 工作流文件与后端 CandidateVersionService 当前全局共享。没有 SQLite；后端文件状态会被不同访问者共同看到，发布 Candidate 会改变全局 ACTIVE。
15. Git 中的合成 DOCX、Inventory、Evaluation Ground Truth 和冻结部署 Artifact 应保持只读。
16. Session 的 Review、Checkpoint、Candidate、临时输出允许在免费服务重启后丢失。
17. 当前安全 Artifact 只有约 143 KB，但位于被忽略目录，未进入 Git。正式启动还要求本机 BGE 快照；Render 无法从仓库直接启动。
18. Linux 主要风险是未跟踪 Artifact、本地模型快照、重型 Torch/Transformers 依赖、Windows 启动脚本，以及没有 `$PORT`/`0.0.0.0` 部署入口。
19. UI 已捕获首页 health/catalog 异常并有 unavailable 回归测试，不会在后端断开时整体崩溃；但提示仍偏本地，没有冷启动说明和重新连接按钮，技术详情也未按 public profile 隐藏。
20. 当前 RAG requirements 混入 Torch、Transformers、pytest 等开发/本地运行依赖，不适合轻量免费 CPU 部署。UI requirements 又缺少它实际导入的 Agent 依赖。

## 最小实施范围

- 增加数据驱动 `DemoCase` 描述与结构不同的 Case B，不改领域算法。
- 将 Case A 适配器硬编码迁入 Case 配置。
- 给 UI 文件状态和 RAG CandidateVersionService 增加 Session 隔离。
- 增加 `APP_ENV`、`RAG_API_BASE_URL`、有限重试、公共提示和 LLM Session Budget。
- 提交一个小型、合成、预构建的 DENSE_ONLY 公网 Artifact，并使用同维度确定性轻量 Embedder；启动只 Load + Validate。
- 增加 Render/Streamlit 配置、只读 Smoke、跨案例评测与 11 份交付材料。

不实施数据库、Redis、认证、复杂限流、新 Retriever、Hybrid、LangGraph 或新的业务领域。
