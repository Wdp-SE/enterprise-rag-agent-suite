# 本地运行约束

查询嵌入在 spawn 子进程中执行，避免 PyTorch 与 FAISS 在同一进程共享原生线程运行时。

默认约束：

- RD_V2_TORCH_THREADS=1
- RD_V2_MKLDNN_ENABLED=false
- 向量必须为 float32、二维、有限值且单位归一化
- 模型快照必须为本地目录
- FAISS 在 Windows 上通过字节反序列化加载，避免非 ASCII 路径问题

修改这些约束前必须重新执行工程硬化测试、离线运行时 Smoke 和范围基准。
