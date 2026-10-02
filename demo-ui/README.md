# 版本化工程知识与变更审查工作台

Streamlit 工作台只提供一种活动业务演示：基于 Seeed Studio reComputer Industrial / Jetson 中文公开工程资料进行检索，并在变更时整理待核查影响候选。它面向设备研发、集成和运维流程的原型体验，不代表 Seeed 官方产品，也不连接企业内部工单、BOM 或真实设备测试平台。

RAG 检索保留资料快照和原始来源，并可硬过滤设备型号、模组 SKU、载板、JetPack/L4T 软件基线。Agent 根据当前领域 profile 给出变更分类与有限检索计划，输出引用证据和待补信息；没有资料支持时不推断兼容性，最后由人工确认。工作台不写回资料源。

## 当前资料和指标边界

RAG 工作区为 `edge_ai_device`，当前只启用中文资料。资料快照 `wiki-1eadc6584f96` 固定到仓库提交 `1eadc6584f962b6efdbdb3e49b2b4ce30c85be08`。JetPack/L4T 是资料标注的筛选维度，不是额外历史资料快照。当前索引是 18 份来源、394 个片段；图像未进行 OCR 入库。

新语料的离线检索和 Agent 流程评测已冻结并绑定当前语料/代码指纹。检索评测比较 BM25 与分面 RRF；两者 DEV/HOLDOUT 的来源召回与完整来源集率相同，因此默认保留更简单的 BM25。Agent 评测报告分类、证据覆盖、缺口检测和人工审核边界，不把这些代理指标表述成 LLM 最终建议准确率。题集规模有限，不能外推为企业生产效果。

## 本地运行

先启动配置到 `public_corpus_edge_ai` 的 RAG API（详见[根目录说明](../README.md)），再运行：

```powershell
$env:RAG_API_BASE_URL = "http://127.0.0.1:8765"
..\change-review-agent\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8502
```

页面会显示 RAG 后端构建版本、语料指纹和评测状态。若 API 返回的工作区不是 `edge_ai_device`、来源仓库不符或语言不是中文，设置了 `APP_ENV=public_demo` 时工作台会停止检索，避免把错误资料标成当前业务。

审核记录用于原型中的会话流程，不具备登录身份、企业 ACL/RBAC 或集中审批留存能力。公网服务仍需独立发布并核对 Streamlit 与 Render 端版本；仅看 GitHub main 的源码不代表在线站点已部署到相同 SHA。
