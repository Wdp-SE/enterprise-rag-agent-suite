# 已知限制

本文件主动记录边界，避免把已验证原型包装成生产级系统。每项都说明未实现原因、对演示的影响和后续方向。

| 限制 | 为什么当前不做 | 对演示/使用的影响 | 后续方向 |
|---|---|---|---|
| Reliability 未全局接管 Agent/Tool | 当前阶段坚持不改 BaseAgent/ReAct/ToolCall 核心语义，先验证独立组件和 Workflow 集成 | 不能宣称所有 OpenManus 操作都受统一 retry/timeout/budget/policy 控制 | 定义统一 Operation boundary，按工具类别渐进接入并保留回归开关 |
| TaskPolicy 在 Research 中仅为 observer | Phase 1D 先验证决策正确性，避免未经充分验证就中止真实流程 | Trace/结果可看到 PolicyDecision，但 STOP 不一定对所有阶段强制生效 | 通过 shadow evaluation 与故障演练后增加 enforce mode |
| Grounding 不是语义蕴含验证 | 当前实现只做确定性的 evidence ID 与集合归属校验，不引入第二模型 | 8/8 grounded 只能说明引用结构完整，不能说明结论一定被证据支持 | 增加独立 entailment verifier、人工抽检与冲突证据处理 |
| 只支持 HTML 与文本 PDF | 第一版聚焦最小真实闭环，避免引入大型 OCR/表格模型 | 扫描 PDF 会标记 `UNSUPPORTED_SCAN_PDF`，部分来源可能被跳过 | 把 OCR、表格和 Office 文档作为独立 extractor plugin |
| 来源策略不验证事实真伪 | Tier 用于有限预算下的来源优先级，不能替代内容审查 | 高 Tier 来源仍可能过期、冲突或被错误解析 | 增加时效、法规状态、交叉来源一致性与人工 review 信号 |
| 真实行业样本规模小 | 资源控制要求一次任务、2–3 来源，不做大规模抓取 | 可证明闭环，不能证明对整个特种设备行业或其他行业的覆盖率 | 使用多 Profile、小批量金标任务做跨行业 eval |
| 没有大规模并发与压力测试 | 当前目标是契约正确性和回归，不是吞吐平台 | 不能给出并发量、吞吐、P95 或长期稳定性指标 | 增加可控 replay、并发预算竞争与 soak test |
| 没有分布式恢复/持久化调度 | Workflow 运行在单机本地目录，未引入队列或状态机服务 | 进程崩溃后的跨机器恢复能力有限 | 设计 checkpoint、持久化 execution state 与幂等任务队列 |
| Evidence relevance 是轻量词法方法 | 预算 Planner 要求确定性、离线且不增加模型调用 | 同义表达或跨语言主题可能排序不佳 | 在保持可审计性的前提下评估 embedding/reranker，可回退到词法模式 |
| 第三方网页不稳定 | 公开站点可能 403、TLS 中断、动态渲染或下线 | 在线演示可能得到 PARTIAL；真实运行已有 1 个下载失败 | 加强合规 Browser fallback、缓存、域级策略和故障记录，不做无限重试 |
| Candidate 只到候选区 | 权限分离要求 Agent 不审批、不写正式索引 | 演示结果是 `accepted=true, ingestion=false`，不会在正式 RAG 中可检索 | 由独立审核工作流负责 approve、version/conflict/health |
| 未实现 Version/Conflict/Knowledge Health | 这些属于知识治理，不是资料发现与候选生成职责 | 无法自动判断新旧法规冲突或候选过期 | 在 RAG/治理侧引入版本、冲突检测、时效与人工审批 |
| 无 Multi-Agent / GraphRAG / 长期 Memory | 当前优先保证单 Workflow 追溯与可靠性，不堆叠复杂能力 | 复杂协同和图关系问题不在演示范围 | 先完成 Reliability 全局化和 eval，再按任务价值引入 |
| Token 估算与 API usage 存在差异 | 调用前只能使用本地估算，供应商 tokenizer/消息包装可能不同 | Planner 的估算不能当成计费值；必须保留安全余量 | 为常用模型接入官方 tokenizer，并持续校准估算误差 |
| `openmanus.exe --help` entrypoint 存在既有打包问题 | setup.py console entrypoint 对顶层 main 的引用不正确，但 `python main.py --help` 正常且不阻断 Workflow | 安装后的可执行命令可能失败；演示统一用 Python 入口 | 独立修复 packaging entrypoint 并增加 wheel 安装 smoke |
| 一份历史 Candidate 目录存在本机 ACL 限制 | 这是当前 Windows 工作区的局部文件权限状态，未安全取得删除/重建授权 | 该机器可能无法直接浏览真实 Candidate 目录；RAG accepted 结果与报告仍保留 | 修复本地 ACL 或从同一 Evidence 重建到新 workspace；演示可用合法 Fixture |
| 真实 run 没有 Phase 1D 完整 trace | 真实研究发生在 Reliability 全阶段落地之前，不能伪造回填 | 可展示真实 Research 工件和 Fixture trace，但不能说真实 run 已有全链 Trace | 下一次经过审批的小规模 run 使用 Reliability enforce/trace 模式 |

## 不应做出的项目声称

- “零幻觉”或“100% 语义正确”；
- “生产级全局可靠性”或“所有工具已被策略接管”；
- “完成整个特种设备行业知识库”；
- “RAG 已正式入库并可检索”；
- “361 项测试等于 361% coverage”或未经测量的覆盖率；
- “OpenManus 的 Browser/Search/ReAct 是本项目从零实现”。
