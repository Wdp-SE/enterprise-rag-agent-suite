# Full Regression Gate Report

报告日期：2026-08-28

## 1. 最终结论

**Full Regression Gate = PASS**。

满足判定条件：

- Docker Desktop daemon 正常；
- 原 OpenManus 25 项 Sandbox tests 已真正创建容器并执行到断言；
- Sandbox 原测试与新增兼容测试全部通过；
- Knowledge Research Minimal Core 41 项继续全部通过；
- 全项目 69 项测试全部通过；
- 未发现 Knowledge Research 二次开发引入的回归。

本轮未进入 Knowledge Research Live Workflow，未运行真实 Search、Browser、LLM、RAG 或行业调研。

## 2. Python / pip 环境

- 虚拟环境：项目目录 `.venv/`，与原 Python 3.11 环境隔离。
- Python：CPython 3.12.13。
- pip：25.0.1。
- Docker SDK for Python：7.1.0。
- OpenManus：0.1.0，editable 安装。
- `pip check`：`No broken requirements found.`
- 容器 runtime：`python:3.12-slim`，容器内 Python 3.12.14。

环境恢复阶段安装 204 个项目依赖；唯一依赖约束调整仍是 `chardet>=5.2.0,<6.0.0`，用于同时满足 Crawl4AI 和 requests 的版本范围。

## 3. Docker 状态

最终 `docker info`：成功，exit code 0。

- Server Version：29.4.0
- OS Type：linux
- Architecture：x86_64
- Operating System：Docker Desktop
- Containers：1
- Running：0
- Images：3

唯一容器是本轮开始前已存在的 stopped `hello-world` 容器；Sandbox 测试及诊断容器均已清理。

最终容器 smoke：

```powershell
docker run --rm python:3.12-slim python --version
```

结果：exit code 0，输出 `Python 3.12.14`。

## 4. Sandbox compatibility patch

修复范围严格限定于原 OpenManus Sandbox infrastructure：

1. `DockerSession` 不再访问 Docker transport 的私有 `_sock`；
2. 新增基于公开能力的 exec connection adapter，支持 `recv/sendall` 和 `read/write` 两类公开 I/O 表面；
3. 阻塞 transport I/O 通过 `asyncio.to_thread()` 执行；
4. 命令与唯一完成标记在同一个已解析 shell command list 中执行，避免 stdin-reading 子进程吞掉控制命令；
5. `SandboxSettings.timeout` 传入内部 `AsyncDockerizedTerminal`；
6. 两处 stale Python 3.10 断言对齐正式 Python 3.12 契约；
7. 网络测试继续访问真实 HTTPS 并精确断言 200，但不再在测试期间实时安装 curl。

没有平台名称判断，没有绑定 `NpipeSocket` 类型，没有新增依赖，没有改变 Docker 网络、volume、memory 或 CPU 隔离语义。

详细设计与逐测试矩阵见 `docs/sandbox_compatibility_patch_report.md`。

## 5. 原 OpenManus Sandbox tests

原测试与新增兼容测试同目录执行：

```powershell
.venv\Scripts\python.exe -m pytest tests\sandbox -q --tb=short
```

最终结果：

- collected：28（原测试 25 + 新增兼容测试 3）
- passed：28
- failed：0
- errors：0
- skipped：0
- warnings summary：1
- duration：84.77s

原 25 项测试全部真实执行；没有 mock Docker、skip、删除或弱化测试。

## 6. Knowledge Research Minimal Core tests

```powershell
.venv\Scripts\python.exe -m pytest tests\research -q --tb=short
```

最终结果：

- collected：41
- passed：41
- failed：0
- errors：0
- skipped：0
- warnings summary：3
- duration：0.62s

Offline E2E、`CREATED -> REUSED`、CandidateValidator `accepted=true`、稳定 ID、`content_hash` 与 `raw_file_hash` 独立校验继续通过。

## 7. 全项目 tests

```powershell
.venv\Scripts\python.exe -m pytest tests -q --tb=short
```

最终结果：

- collected：69
- passed：69
- failed：0
- errors：0
- skipped：0
- warnings summary：4
- duration：84.49s

## 8. Import / CLI smoke

关键 import smoke：exit code 0，输出 `IMPORT_SMOKE_OK`。

覆盖：

- BaseAgent / ReActAgent / ToolCallAgent / Manus
- BaseTool / BrowserUseTool / WebSearch / ToolCollection
- DockerSandbox / AsyncDockerizedTerminal
- Evidence / ResearchProfile / CandidateValidator / KnowledgeDraftTool

Script CLI：

```powershell
.venv\Scripts\python.exe main.py --help
```

结果：exit code 0，argparse help 正常显示。

导入 BrowserUse/Daytona 模块时仍会输出其既有初始化日志；未创建 Agent，也未触发真实在线工作流。

## 9. Warnings / failed / errors / skipped

- Sandbox：28 passed，0 failed，0 errors，0 skipped，1 Pydantic summary warning。
- Minimal Core：41 passed，0 failed，0 errors，0 skipped，3 Pydantic summary warnings。
- 全项目：69 passed，0 failed，0 errors，0 skipped，4 Pydantic summary warnings。
- pytest 会话启动仍提示 `asyncio_default_fixture_loop_scope` 未配置；该提示不计入 pytest summary 数字。
- 既有 Pydantic warnings：class-based `Config` 弃用及 `underscore_attrs_are_private` 已移除。
- PowerShell 登录环境仍会输出既有 Conda 初始化噪声，但 Docker/pytest 命令 exit code 与测试结果不受影响。

## 10. 是否存在 Knowledge Research 引入的回归

**未发现。** 依据：

- Minimal Core 41/41 通过；
- 原 Sandbox 25/25 真实执行并通过；
- 全项目 69/69 通过；
- 修复文件仅位于 `app/sandbox` 和 `tests/sandbox`；
- 未修改 `app/research`、Agent Core、Browser、Search、ToolCollection 或 RAG。

当前源码目录没有可用 Git 元数据，因此无法提供基于 commit 的 diff 证明；结论基于文件范围、真实调用栈和完整回归结果。

## 11. Existing Packaging Issue

`openmanus.exe --help` 仍记录为 **Existing Packaging Issue**：console entrypoint 指向顶层 `main:main`，editable/package discovery 下无法导入该模块。

本轮按要求未修改 `setup.py`。因为 `python main.py --help` 已通过，该问题不阻塞后续 Research Workflow。

## 12. 下一阶段判定

环境与回归 Gate 已闭合，可以进入下一阶段：

```text
Knowledge Research Live Workflow
KnowledgeResearchAgent
-> Search
-> SourcePolicy
-> Browser / Download
-> Evidence
-> ResearchResult
-> Output Adapter
-> Candidate Package
-> RAG import_candidate()
```

本报告仅确认具备进入条件；本轮没有实现或启动上述工作流。
