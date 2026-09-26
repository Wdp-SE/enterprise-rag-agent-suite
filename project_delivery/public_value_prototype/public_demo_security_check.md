# Public Demo 安全检查

## 结论

最终 Secret Scan 扫描 304 个文本文件、跳过 24 个二进制文件，潜在 Secret 命中为 0。扫描覆盖 Git 跟踪文件和本轮新增文件，并在路径级排除两个受保护未跟踪目录。

## 数据与 Secret

- Case A/B 与 Public Artifact 全部为合成数据。
- Ground Truth 只用于 Evaluation 断言，不进入 Agent 提示。
- .env 与 .streamlit/secrets.toml 被忽略。
- 只提交占位示例；DASHSCOPE_API_KEY 由平台环境变量或 Secrets 注入。
- RAG URL 禁止携带 username/password。
- Public Artifact 共 9 个文件、34,035 bytes，最大文件 13,337 bytes，不含绝对本机路径。

## 隔离与完整性

- public API 要求白名单格式 X-Demo-Session-ID。
- Session ID / Case ID 经过格式校验并使用独立目录。
- 两个随机新 Session 的候选目录均为空；跨案例 Evaluation 的新 Session 检查通过。
- Baseline 和 Artifact 只读，Case A/B 源 DOCX SHA-256 前后一致。
- Human Review、Conflict、Idempotency、Candidate Validation 继续 fail-closed。
- 一个 Session 的激活不会改变另一个 Session 或公共 Baseline。

## 滥用与错误

- MAX_LLM_CALLS_PER_SESSION 配置化，超限返回 429/明确提示，不返回伪造结果。
- Retry 有上限，public UI 隐藏 traceback。
- 后端不可用时首页仍能打开。
- 本地 public profile 的只读 Smoke 不调用 /query，不发布或激活 Candidate。

当前不是多租户 SaaS，尚无 Authentication、ACL/RBAC、IP Rate Limit、WAF、持久审计、密钥轮换自动化、生产监控、备份、HA 或真实企业数据合规验证。
