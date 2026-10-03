# 单项目版本化研发知识 RAG 服务

FastAPI 服务只接受唯一项目 `xbs0325/industrial-inspection` 的固定版本语料，不允许静默回退到旧领域索引。目标提交为 `6d0df954f26b1810910db9f50727ca8bd19afa9f`。

## 当前服务状态

GitHub 未声明内容再分发许可证，逐文件审计为 0 个已批准正文。活动 corpus manifest 是元数据声明，索引为 0 来源、0 片段、`active=false`。服务可以启动并提供状态接口，但 `/health` 报告 `rag_ready=false`；搜索和生成接口返回 `503 PROJECT_CORPUS_INACTIVE_LICENSE_PENDING`，不会请求模型。这个仓库当前没有可用于报告的本项目 RAG/Agent 指标。

只有在取得明确许可、完成逐文件审核并重建语料后，才能开放内容检索。旧 Seeed/Jetson 的 corpus、评测与适配代码不属于当前活动项目，历史结果不能作为本项目成绩。

## API 状态接口

- `GET /health`：进程存活状态、RAG 就绪状态和构建身份。
- `GET /public/workspace`：唯一项目仓库、commit、来源/片段数、许可门禁和评测状态。
- `GET /public/documents`：当前已批准来源目录；语料未激活时返回空目录。
- `POST /public/search`、`POST /public/query`：仅在经验证的项目正文语料激活后工作；不得由客户端指定其他仓库或 namespace。

## 本地启动

从仓库根目录进入服务目录：

```powershell
$env:RAG_PUBLIC_CORPUS_ROOT = "public_corpus_industrial_inspection"
$env:RAG_PUBLIC_RETRIEVAL_CONFIG = "public_corpus_industrial_inspection/public_retrieval_runtime.json"
..\.venv\Scripts\python.exe -m uvicorn src.public_server:app --host 127.0.0.1 --port 8765
```

运行来源审计和 corpus 构建器的命令行帮助：

```powershell
..\.venv\Scripts\python.exe scripts/audit_project_source.py --help
..\.venv\Scripts\python.exe scripts/build_project_corpus.py --help
```

构建器只复制逐文件明确批准的内容；来源哈希、项目仓库、commit、发布者和许可证审核记录必须全部匹配。空语料保持 inactive。

## 发布门禁

Render 模板也指向 `public_corpus_industrial_inspection/`。部署空语料时，服务健康检查只表示进程存活，不代表检索可用。发布核对需分别验证 `/health` 的 `rag_ready`、`/public/workspace` 的项目来源与许可状态，以及本项目自己的冻结评测；其他领域评测不会被引用。
