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

## 测试

```powershell
..\OpenManus-rag\.venv\Scripts\python.exe -m pytest tests -q
```
