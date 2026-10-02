# 版本化研发知识 RAG 与证据约束变更审查 Agent

这是面向 AI 应用开发岗位的工程原型，聚焦一个可说明、可验证的业务：边缘 AI 设备研发人员需要查清设备规格、软件基线、刷写部署和运维资料；发生变更时，系统从同一组有来源记录的资料中找出可能相关内容、列出证据缺口，由工程师审核。

- RAG 提供按资料快照、设备型号、模组 SKU、载板和 JetPack/L4T 基线过滤的中文工程资料检索，并为证据保留原始来源。
- Agent 按软件基线、设备/接口配置、AI 部署/运维等变更类型规划有限查询，将证据组织成待核对候选；缺少设备或基线信息时明确提示，不推断兼容性。
- 人工保留最终决定权。Agent 不修改源文档、BOM、设备配置或上游仓库。

## 当前演示范围

唯一活动语料为 Seeed Studio Wiki 的 reComputer Industrial / Jetson 中文公开工程资料。当前固定语料快照来自 `Seeed-Studio/wiki-documents` 提交 `1eadc6584f962b6efdbdb3e49b2b4ce30c85be08`，索引包含 18 份来源和 394 个检索片段。它是经过许可与内容哈希审核的精选快照，不是完整产品资料库，也不代表任何企业内部资料、硬件实测、认证结论或兼容性验证。资料正文中的 334 个图片引用没有 OCR 入库，不能声称系统可以检索图内文字。

软件基线（JetPack/L4T）是文档适用范围筛选条件，`wiki-1eadc6584f96` 是资料来源快照；两者不是同一类版本。当前只有一个资料快照，历史快照比较尚未提供。中英文对照、企业 Jira/工单、BOM、真实设备测试和生产权限控制也不在演示范围内。

## 方案与质量口径

当前使用 BM25 作为可解释检索基线，并支持 UI 选择 Top-K 与设备/软件过滤。新语料的冻结题集和指纹绑定评测尚未完成，因此不公布当前语料的召回率、答案准确率、幻觉率或最优策略。任何其他领域、旧语料或仓库离线实验的数字都不能当作这里的成绩。下一步先建立按来源文档族隔离的 DEV/HOLDOUT 问题集，再比较基线、候选扩展和重排；Agent 查询覆盖、证据完整率及人工判断质量单独报告。

Agent 每项审查最多拆为 4 次 RAG 查询，最多把 8 条证据交给生成分析；候选引用按当前语料来源登记表校验。没有有效证据时保留缺口并停止肯定结论。当前审查与审核决定保留在会话/演示运行环境中，不是带身份和集中审计的企业审批系统。

## 技术组成

- `versioned-rag-service/`：FastAPI、Pydantic、BM25 知识索引和公开检索 API。
- `change-review-agent/`：基于领域 profile 的变更分类、有限查询规划、证据核验和人工审核流程。
- `demo-ui/`：Streamlit 检索与变更审查工作台。
- `versioned-rag-service/public_corpus_edge_ai/`：许可审计后的固定资料、索引清单和检索配置。
- `evaluation/edge_ai_retrieval_v1/` 与 `evaluation/edge_ai_change_review_v1/`：后续冻结检索和审查评测所在目录；只有实际运行并绑定指纹后才发布指标。

## 本地运行

安装 Python 3.12 环境和项目依赖后，先启动 RAG 服务，再启动 Streamlit。RAG 服务进程要使用新语料配置：

```powershell
$env:RAG_PUBLIC_CORPUS_ROOT = "public_corpus_edge_ai"
$env:RAG_PUBLIC_RETRIEVAL_CONFIG = "public_corpus_edge_ai/public_retrieval_runtime.json"
Set-Location versioned-rag-service
..\.venv\Scripts\python.exe -m uvicorn src.public_server:app --host 127.0.0.1 --port 8765
```

另开 PowerShell 窗口启动工作台：

```powershell
$env:RAG_API_BASE_URL = "http://127.0.0.1:8765"
Set-Location demo-ui
..\change-review-agent\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8502
```

模型密钥只配置在 RAG 后端进程。没有密钥时仍可检索和运行不依赖生成的审查步骤；在线模型可用性仍受服务商账户、限流和网络影响。请勿把密钥写入前端 Secrets 或仓库。

## 发布说明

源码工作区、RAG 后端语料、Streamlit 前端和公网部署需要分别核对构建 SHA 与语料指纹。当前任务只准备源码与 main 分支；在公网部署完成并核实两端指纹前，现有在线链接可能仍展示旧业务版本，不应作为新版本效果证明。

- [GitHub 源码](https://github.com/Wdp-SE/enterprise-rag-agent-suite)
- [RAG API 文档](https://version-aware-rag-public-demo.onrender.com/docs)（以托管服务实际部署版本为准）

## 相关说明

- [RAG 服务](versioned-rag-service/README.md)
- [Streamlit 工作台](demo-ui/README.md)
- [Seeed 语料许可与归属审计](versioned-rag-service/public_corpus_edge_ai/SOURCE_AUDIT.md)
- [完整迁移实施计划](docs/superpowers/plans/2026-10-03-edge-ai-public-corpus-migration.md)
