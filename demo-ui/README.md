# 企业研发文档 RAG 与审核工作流界面

Streamlit 页面展示版本化 RAG 知识底座和 Evidence-driven Document Workflow
Agent。UI 不实现业务逻辑；Agent 页面只调用 `DocumentWorkflowFacade`。

## 启动

先启动 RAG API：

```powershell
cd RAG-Challenge-2-main
$env:RD_V2_PROJECT_ROOT = (Get-Location).Path
$env:RD_V2_ARTIFACT_ROOT = (Resolve-Path 'data\rd_v2_corpus\retrieval_artifacts\rd-v2-retrieval-final-v1.0-safe-integration').Path
$env:RD_V2_ALLOW_EXTERNAL_GENERATION = 'false'
.venv\Scripts\python.exe -m uvicorn src.rd_v2_api:app --host 127.0.0.1 --port 8765
```

再启动 UI：

```powershell
cd demo-ui
..\OpenManus-rag\.venv\Scripts\python.exe -m pip install -r requirements.txt
..\OpenManus-rag\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

## Agent 页面

1. 选择 Project。
2. 选择当前文档、指定文档或显式历史版本 Scope。
3. 加载旗舰模板或上传结构化 DOCX。
4. 检查解析出的 SectionTask/FieldTask。
5. 运行范围受控的 Evidence 检索与字段起草。
6. 查看 Query、Evidence、Version、Freshness、Draft 和 Missing。
7. 填写审核人，编辑字段并逐章节批准或驳回。
8. 全部必要章节通过后生成 Approved DOCX。
9. 在历史任务中查看或恢复未完成工作流。

上传和输出位于 `demo-ui/runtime/`，Git 默认忽略。真实未经授权资料不得
发送公网模型。

## Demo 可解释性与边界

- RAG 与 Agent 页面都会展示当前资料范围；恢复工作流时以 Checkpoint 保存的范围为准。该 Scope 是业务检索范围约束，不等同于 ACL/RBAC。
- RAG 与 Agent 的来源统一展示文档名称、版本、章节和页码；内部 ID 收入“技术详情”。Citation / Evidence 提供可追溯性，不等同于自动证明答案事实正确。
- 文档版本更新触发局部刷新时，页面展示真实受影响、复用、重新检索和重新生成章节；没有刷新时不显示该摘要。
- 当前项目是研发文档场景 MVP，正式向量检索后端为 FAISS，采用单审核人工作流；不宣称生产级或零幻觉。

## 测试

```powershell
..\OpenManus-rag\.venv\Scripts\python.exe -m pytest tests -q
```
## V4 工程变更审核工作台

V4 需要在启动 RAG 前增加候选版本库目录：

```powershell
$env:RD_V4_VERSION_STORE_ROOT = (Join-Path $env:TEMP 'rag-agent-v4-demo-store')
```

UI 的第三个页签使用完全合成的 `demo_company_a / PAYMENT` 资料，演示需求 Diff、已确认/疑似影响、Evidence、局部段落 Patch、单审核人确认、冲突检测、Candidate 校验和安全激活。首次载入会通过 RAG HTTP API 初始化合成版本；Agent 不读取 FAISS。详细步骤见 `project_delivery/v4_change_impact_review/demo_script.md`。

该页面只证明 OrganizationProfile 适配边界和单项目业务闭环。`organization_id` 不是租户隔离；语义命中只是 Suggested Impact；原始 DOCX 不会被覆盖。
