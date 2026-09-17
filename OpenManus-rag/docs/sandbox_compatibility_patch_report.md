# Sandbox Compatibility Patch Report

报告日期：2026-08-28

## 1. Sandbox Failure Root Cause Matrix

基线为修复前 `13 failed / 10 errors / 2 passed`。A 表示 `NpipeSocket/_sock` 初始化阻断；B 表示 Python 版本旧断言；C 表示解除 A 后真实执行才暴露的其他既有 Sandbox 问题。

| Test name | 基线状态 | 根因 | Affected source file | 是否同一根因 | 建议/实际修复位置 |
| --- | --- | --- | --- | --- | --- |
| `test_client::test_sandbox_creation` | failed | A；潜在 B | `terminal.py`；`test_client.py` | A 同源，B 独立 | connection adapter；3.12 断言 |
| `test_client::test_local_command_execution` | failed | A | `terminal.py` | 是 | `DockerSession` |
| `test_client::test_local_file_operations` | failed | A | `terminal.py` | 是 | `DockerSession` |
| `test_client::test_local_volume_binding` | failed | A | `terminal.py` | 是 | `DockerSession` |
| `test_client::test_local_error_handling` | failed | A | `terminal.py` | 是 | `DockerSession` |
| `test_docker_terminal::test_basic_command_execution` | error | A（fixture setup） | `terminal.py` | 是 | `DockerSession` |
| `test_docker_terminal::test_environment_variables` | error | A（fixture setup） | `terminal.py` | 是 | `DockerSession` |
| `test_docker_terminal::test_working_directory` | error | A（fixture setup） | `terminal.py` | 是 | `DockerSession` |
| `test_docker_terminal::test_command_timeout` | failed | A | `terminal.py` | 是 | `DockerSession` |
| `test_docker_terminal::test_multiple_commands` | error | A；解除后暴露 C1 | `terminal.py` | A 同源，C1 独立 | connection adapter；完整消费控制帧 |
| `test_docker_terminal::test_session_cleanup` | failed | A | `terminal.py` | 是 | `DockerSession` |
| `test_sandbox::test_sandbox_working_directory` | error | A（module fixture） | `terminal.py` 经 `sandbox.py` | 是 | `DockerSession` |
| `test_sandbox::test_sandbox_file_operations` | error | A（module fixture） | 同上 | 是 | `DockerSession` |
| `test_sandbox::test_sandbox_python_execution` | error | A（module fixture） | 同上 | 是 | `DockerSession` |
| `test_sandbox::test_sandbox_file_persistence` | error | A（module fixture） | 同上 | 是 | `DockerSession` |
| `test_sandbox::test_sandbox_python_environment` | error | A；潜在 B | `terminal.py`；`test_sandbox.py` | A 同源，B 独立 | connection adapter；3.12 断言 |
| `test_sandbox::test_sandbox_network_access` | error | A；解除后暴露 C2/C3/C4 | `terminal.py`、`sandbox.py`、`test_sandbox.py` | A 同源，C 独立 | 控制帧、timeout 传播、稳定 HTTPS test |
| `test_sandbox::test_sandbox_cleanup` | failed | A | `terminal.py` 经 `sandbox.py` | 是 | `DockerSession` |
| `test_sandbox_manager::test_create_sandbox` | failed | A | `terminal.py` 经 `manager.py` | 是 | `DockerSession` |
| `test_sandbox_manager::test_max_sandboxes_limit` | failed | A | 同上 | 是 | `DockerSession` |
| `test_sandbox_manager::test_sandbox_cleanup` | failed | A | 同上 | 是 | `DockerSession` |
| `test_sandbox_manager::test_idle_sandbox_cleanup` | failed | A | 同上 | 是 | `DockerSession` |
| `test_sandbox_manager::test_manager_cleanup` | failed | A | 同上 | 是 | `DockerSession` |

基线的 23 项 failed/error 全部首先停在 A，因而第一轮栈中没有 C 类证据。A 修复后，完整执行又依次揭示：

- C1：中间 prompt 被误判为命令完成，下一次命令读到残留 final prompt；
- C2：stdin-reading 子进程可吞掉作为第二条 TTY 输入发送的 `echo $?`；
- C3：`SandboxSettings.timeout=300` 未传给内部 terminal，直接 terminal 调用退回 60 秒；
- C4：网络测试实时执行 `apt install curl`，将 Sandbox 网络契约绑定到 Debian mirror 与 27 个临时包。

最终没有未归类的独立失败。

## 2. NpipeSocket 根因

### 2.1 `_sock` 被用于什么目的

旧实现取得 `exec_start(socket=True)` 返回值后，再访问 `socket_data._sock`，目的是拿到底层标准 socket 并调用：

- `setblocking(False)`；
- `recv()`；
- `sendall()`；
- `shutdown()`；
- `close()`。

### 2.2 是否为 Docker SDK 公开接口

不是。`_sock` 是 Python/urllib3 某些包装对象的内部属性，不属于 Docker SDK `exec_start()` 的公开契约。

Docker SDK 7.1 的公开契约是：`APIClient.exec_start(..., socket=True)` 直接返回可由调用方读写并关闭的 transport connection。SDK 自己已经根据连接 transport 解包到适当层级。

### 2.3 不同平台可能返回什么

- Linux：默认使用 Unix domain socket，通常得到 file-like raw stream，公开 I/O 表面为 `read/write/close`；
- macOS Docker Desktop：默认同样通过 Unix socket，行为与 Unix transport 类似；
- Windows Docker Desktop：named-pipe transport 返回 `docker.transport.npipesocket.NpipeSocket`，公开 I/O 表面为 `recv/sendall/close`；
- 非默认远程 endpoint 还可能通过 HTTPS 或 SSH 返回 TLS socket/channel 类对象。

因此不能假定所有平台返回同一个具体类，也不能假定都存在 `_sock`。

### 2.4 Windows NpipeSocket 为什么没有 `_sock`

`NpipeSocket` 已经是 Docker SDK 为 Windows named pipe 提供的 socket-like endpoint，内部持有 Windows pipe handle（`_handle`），并直接实现 `recv/send/sendall/close/settimeout`。它不是“包着另一个标准 socket 的 wrapper”，所以没有 `_sock`。

实际诊断结果：

```text
type = docker.transport.npipesocket.NpipeSocket
hasattr(_sock) = false
public recv/sendall/close = true
```

直接通过这些公开方法完成了临时容器的写入和回读。

### 2.5 是否有公开 API 获得同等信息

有公开入口，但没有公开 API 保证获得统一的 `socket.socket` 实例。正确入口就是 `exec_start(socket=True)` 的返回连接本身。

因此最终方案消费返回对象的公开能力，而不是继续向下剥离 transport 私有实现。

## 3. 最终兼容方案

### 3.1 Transport capability adapter

新增内部 `_DockerExecConnection`：

- 优先使用 `recv`，否则使用 `read`；
- 优先使用 `sendall`，否则使用 `write` 并处理 partial write；
- file-like writer 如有 `flush` 则调用；
- 始终使用公开 `close`；
- 所有阻塞 I/O 通过 `asyncio.to_thread()` 执行；
- 不检查 `sys.platform`，不导入或识别 `NpipeSocket` 类型，不访问 `_sock`。

### 3.2 命令完成协议

旧协议把用户命令和 `echo $?` 作为两条 TTY 输入发送，存在两个问题：

1. Bash 会在两条命令之间输出 prompt，分块边界可能导致提前结束；
2. `apt/debconf` 等读取 stdin 的子进程可能吞掉排队的 `echo $?`。

新协议：

- 将 UTF-8 命令编码成无换行的十六进制 escape；
- 使用 Bash builtin `printf -v` 还原命令；
- 在当前 shell 中 `eval`，保留 `cd`、环境变量等 session 语义；
- 在同一个已解析 command list 中输出每次 UUID 唯一的状态标记；
- 读取器只在收到唯一状态标记及其后的 final prompt 后结束。

用户命令仍先经过既有 `_sanitize_command()`；编码只改变 TTY framing，不改变命令内容或安全拒绝规则。

### 3.3 Timeout propagation

`DockerSandbox.create()` 现在将 `self.config.timeout` 传给 `AsyncDockerizedTerminal.default_timeout`。公开 `DockerSandbox.run_command()` 原本已经使用同一配置，因此这项修改只是修复内部配置断层。

## 4. Python 3.10 / 3.12 契约判断

正式预期是 **Python 3.12**，依据一致：

- `setup.py`：`python_requires=">=3.12"`；
- package classifier：Python 3.12；
- `SandboxSettings.image` 默认：`python:3.12-slim`；
- `config.example.toml` / `config.toml` 示例：`python:3.12-slim`；
- `test_client`、`test_docker_terminal`、`test_sandbox` fixture：均使用 `python:3.12-slim`；
- 只有两处 assertion 仍要求 `Python 3.10`。

因此修正的是过期测试断言，而不是为了 green test 改动正式配置。

## 5. 修改文件

生产代码：

- `app/sandbox/core/terminal.py`
- `app/sandbox/core/sandbox.py`

测试：

- `tests/sandbox/test_terminal_connection.py`（新增）
- `tests/sandbox/test_client.py`
- `tests/sandbox/test_sandbox.py`

报告：

- `docs/full_regression_gate_report.md`
- `docs/sandbox_compatibility_patch_report.md`

未修改 Agent Core、Browser、Search、ToolCollection、`app/research` 或 RAG。

## 6. 是否修改测试以及原因

是，修改范围如下：

1. 两处 `Python 3.10` 更新为 `Python 3.12`：正式配置和项目 requirement 已统一为 3.12，旧断言属于 stale contract；
2. 网络测试继续访问相同 HTTPS 站点并严格断言状态码 `200`，但改用镜像自带 Python 标准库：测试意图是 Sandbox outbound HTTPS，不是实时验证 Debian mirror、apt 或 curl 安装；
3. 新增 3 项抽象兼容测试：覆盖无 `_sock` 的 recv/sendall 连接、Unix-like read/write 连接、create/execute/close、连续命令 final prompt 消费以及不支持 I/O 表面的明确拒绝。

没有 skip、mock Docker integration、删除测试或降低 Sandbox 网络成功断言。

## 7. Sandbox tests 最终结果

```text
28 passed, 0 failed, 0 errors, 0 skipped, 1 warning
duration: 84.77s
```

其中原测试 25 项、新增兼容测试 3 项。原测试已创建真实 Docker 容器并执行到断言。

## 8. Minimal Core 最终结果

```text
41 passed, 0 failed, 0 errors, 0 skipped, 3 warnings
duration: 0.62s
```

Knowledge Research 代码未修改。

## 9. 全项目最终结果

```text
69 passed, 0 failed, 0 errors, 0 skipped, 4 warnings
duration: 84.49s
```

Docker container smoke、关键 import smoke 和 `python main.py --help` 均为 exit code 0。

## 10. 是否存在二次开发回归

未发现 Knowledge Research 二次开发引入的回归：

- Minimal Core 41/41 通过；
- 原 Sandbox 25/25 通过；
- 全项目 69/69 通过；
- 本轮没有修改 Knowledge Research 或 Agent Core。

`openmanus.exe --help` 继续记录为 Existing Packaging Issue，本轮未修改 `setup.py`；`python main.py --help` 正常，因此不阻塞 Research Workflow。

## 11. Full Regression Gate

**PASS**。

已满足：Docker 正常、Sandbox tests 真正执行并全部通过、Minimal Core 41 项通过、全项目通过、没有发现 Knowledge Research 回归。

本轮没有进入或实现 Knowledge Research Live Workflow。
