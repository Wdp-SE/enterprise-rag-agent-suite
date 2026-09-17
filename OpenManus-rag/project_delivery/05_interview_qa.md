# 面试问答（30 题）

以下回答按正常语速设计为约 30–90 秒。面试时可先说结论，再根据追问展开。

## 1. 这个项目解决了什么问题？

OpenManus 已经能调用 Search、Browser 和 Files，但工具可用不等于研究结果可靠。我的工作是把开放式调研拆成固定阶段：发现、选源、获取、抽取、构建结果和输出。每个专业事实先落到可追溯 Evidence，Evidence 能回到原始 HTML/PDF、页码或 section 和双 hash。系统既能输出 Markdown/JSON，也能通过 Adapter 生成 RAG Candidate，因此没有 RAG 时 Workflow 仍然独立有意义。

## 2. 哪些是 OpenManus 原有能力，哪些是你的新增？

BaseAgent、ReAct、ToolCallAgent、Manus、ToolCollection、Browser、WebSearch、Files、Python、MCP、Memory、Logger 和 Docker Sandbox 都是 OpenManus 原有能力。我的新增包括 ResearchProfile、Evidence/RawSource 契约、SourcePolicy、阶段式 Knowledge Research Workflow、ResearchResult、多输出 Adapter、EvidenceBudgetPlanner，以及操作级 Reliability Phase 1A–1D。Sandbox 只做过 Windows socket 兼容修复，不会把原来的容器能力算成二次开发成果。

## 3. 为什么没有直接修改 BaseAgent 的 run/step？

BaseAgent 的循环是框架最核心、影响面最大的行为。如果把调研阶段、行业规则或可靠性策略直接塞进去，会让原 Manus 行为发生隐性变化，也让升级上游版本变得困难。我选择独立 `run_research.py` 和组合式 Workflow，只在业务边界调用原工具。这样禁用 Research 后原 OpenManus 仍能工作，回归范围更清晰，未来要把 Reliability 全局化时也可以基于统一 operation boundary 渐进接入。

## 4. KnowledgeResearchAgent 为什么采用组合而不是继承 Manus？

Manus 的长处是通用 Tool Calling 和 ReAct 决策，但第一版调研有明确的资源约束和审计要求，例如最多 8 个候选、2–3 个来源、必须归档 raw source。用继承重写 think/act 容易把阶段控制交给 LLM。组合方式让 KnowledgeResearchAgent 成为业务外观，内部调用固定的 Workflow 和可注入端口；WebSearch/Browser 仍复用原能力，测试时则替换为 Fake。它在可控性和复用性之间更合适。

## 5. 为什么 SearchResponse 不能先转字符串再解析？

转成字符串会丢失类型边界，后续需要依赖展示格式解析 title、URL、snippet 和 engine。一旦工具输出格式变化，Research 层就会静默出错，也无法稳定去重和排序。我加的是最小 Search Adapter，直接保留结构化字段，Memory 中是否展示字符串不影响业务数据。这样 SourcePolicy 接到的是明确对象，测试也能直接断言 candidate count、URL 去重和 engine 信息。

## 6. SourcePolicy 的 Tier 能证明来源正确吗？

不能。Tier 只表示来源优先级，例如政府监管机构和官方标准机构优先于普通网页。它帮助在有限下载预算下选择更可能有权威信息的来源，但不会验证内容是否过期、页面是否被误读或不同法规是否冲突。因此 Finding 仍必须基于实际 Evidence，报告还要写 limitations。这个边界很重要，否则“来源级别高”会被错误包装成“结论一定正确”。

## 7. 为什么 Raw Source 和 Evidence 要分开？

Raw Source 是原始 HTML/PDF 字节，是可追溯事实载体；Evidence 是解析后可独立理解、带上下文和定位的事实片段。两者生命周期不同：Extractor 可以升级，Evidence 可以重新生成，但原始文件应保持不变。如果只保存 LLM 摘要，就无法验证摘要是否删改了原文；如果整份 PDF 当一个 Evidence，又不利于引用和预算控制。分开后可以验证文件身份、文本身份和生成链路。

## 8. content_hash 和 raw_file_hash 为什么必须分开？

`raw_file_hash` 是原始文件字节的 SHA256，HTML 的空格、编码或 PDF 元数据变化都会影响它；`content_hash` 是规范化 Evidence 文本的 SHA256，只描述提取出的事实片段。它们对应不同对象，不能要求相等。CandidateValidator 会分别重算 Evidence 文本和 raw file 字节，避免把“解析内容一致”和“原文件一致”混成一个弱校验。

## 9. Stable ID 是怎样设计的？

Evidence ID 基于 canonical source identity、page/section 定位和 content hash；Candidate ID 与 Document ID 基于规范化的 domain/topic、来源集合和内容身份生成；Sxx 则先按稳定 source identity 排序再编号。因此相同输入重复构建会得到相同身份，Evidence 输入顺序随机打乱也不会改变 S01/S02 映射。这允许第二次构建返回 `REUSED`，同时避免随机 UUID 让同一文档被当成新知识。

## 10. Candidate Package 为什么采用原子发布？

Candidate 包由 document、metadata、sources 和 raw_sources 多部分组成。如果直接写目标目录，中途失败会留下看似存在但不完整的包，RAG 或人工审阅可能读到半成品。Builder 先在隔离位置完成写入和 Validator 校验，再原子发布到稳定目录；如果同一输入已经存在，则验证后返回 `REUSED`，不覆盖第一次产物。这同时解决一致性和幂等性问题。

## 11. 为什么 Agent 不能设置 APPROVED？

Agent 的职责是发现、整理和提出候选知识，不应该同时成为最终审批者。`APPROVED` 意味着进入正式知识治理边界，需要人工或独立系统承担权限和审计责任。因此 metadata 固定 `CANDIDATE`、`requires_review=true`，调用方没有参数可以传入 APPROVED。真实 RAG 联动也只调用 `import_candidate()`，结果为 accepted，但没有 approve、Embedding 或 FAISS 写入。

## 12. 为什么 ResearchResult 要独立于 RAG？

公开资料调研本身应能服务报告、API、其他 Agent 或系统集成，不能被某个向量库目录格式绑死。所以 ResearchResult 表达 topic、summary、findings、evidence_ids、sources、limitations 和 unresolved questions；Markdown、JSON 和 Candidate 都是 Adapter。RAG 接口变化只影响 CandidatePackageAdapter，核心 Workflow 和其他输出不需要重写。这也符合端口与适配器的思路。

## 13. 为什么没有只用 Tenacity 做所有重试？

项目并不是完全不用 Tenacity，OpenManus 原 LLM 层已经有相应重试。新增 Reliability 要解决的是更高一层的操作契约：错误能否重试、谁拥有重试、一次尝试消耗多少预算、是否允许副作用重放、最终结果如何结构化。单纯装饰器很难同时表达 BudgetLedger、idempotency 和 trace。我的实现保留原重试，不冒充原成果，并用 ReliableOperationExecutor 管理明确的 operation-level retry。

## 14. 如何避免双重重试导致指数放大？

关键是明确 retry ownership。OperationSpec 和 RetryPolicy 决定 Reliability 层是否拥有重试；如果下层 SDK 已经重试，上层策略必须知道其边界，不能每层都默认多次。每次 attempt 也要预留并结算预算，超限就停止。测试会覆盖 retryable/non-retryable、最大尝试次数和副作用约束。当前没有宣称已统一接管所有第三方 SDK 重试，这是后续全局集成要继续治理的点。

## 15. 403 和 TLS EOF 为什么处理不同？

403 通常表示访问被拒绝或权限/反爬策略，不是短暂网络抖动；直接重试同一个请求大概率重复失败，还会浪费预算，所以被分类为非重试的 ACCESS_DENIED，并作为 download failure/limitation 保留。TLS EOF 更可能是传输链路瞬时中断，可以在幂等 GET 和预算允许时重试。Fixture 测试验证了 403 不循环重试、TLS EOF 可以重试后成功，分类和执行策略是分离的。

## 16. Timeout 是怎样设计的？

Timeout 不是到处散落一个常数，而是由 TimeoutResolver 根据 operation 类型和显式配置得出有效值，再由 Executor 执行。超时结果被规范化为结构化错误，进入 RetryPolicy 和 ExecutionResult，而不是只记录一条日志。当前实现是操作级最小能力，不是全局 Deadline Framework；浏览器、模型和整个 Agent 的层级 deadline 还没有统一，所以文档中不会宣称完整超时治理。

## 17. BudgetLedger 为什么是权威状态而 Trace 不是？

预算必须支持原子预留、提交、释放和拒绝，否则并发或失败时容易超卖。BudgetLedger 保存这套状态机，是执行决策的唯一权威；Trace 只是把发生过的事件 best-effort 写出，用于观察和复盘。如果把 Trace 当余额来源，写失败、乱序或裁剪都会破坏执行正确性。这个区分也让 tracing 故障不会影响核心预算安全。

## 18. NoProgressDetector 如何定义“没有进展”？

它不简单看步骤数，而是接收 Workflow 的 ProgressSignal，例如新搜索结果、新成功来源、新 Evidence、新输出等。连续信号如果没有带来可辨识的新状态，才累计 no-progress；达到策略阈值后产生结构化 decision。这样可以避免“工具调用很多但结果没变化”被误判为进展。当前 Detector 与 Executor 不是伪造的单一线性链，它观察 Workflow 层状态变化。

## 19. TaskPolicy 当前能做什么，不能做什么？

TaskPolicy 接收 PolicyContext、执行结果、预算快照和 NoProgressDecision，输出 CONTINUE、STOP、FALLBACK 或 REPLAN，并记录 capability/network/path/side-effect 等约束。Phase 1D 的 Fake Workflow 覆盖了四个分支；在真实 Research Workflow 中目前采用 observer 集成，即记录决策但不对所有阶段强制执行 STOP。这是刻意的安全边界：先验证决策质量，再进入下一阶段的执行接管。

## 20. Structured Trace 记录了什么？

Trace 记录 operation 开始/结束、attempt、error、retry、budget、progress、policy decision/denied 等结构化事件，便于按 run 和 operation 关联。它避免只靠人类日志文本拼接因果链。但当前真实 Research Run 发生在 Reliability 全部接入之前，因此仓库没有把那次运行包装成“已有完整真实 trace”；目前证据来自组件和 Fixture 集成测试。这种时间边界会在报告中明确说明。

## 21. EvidenceBudgetPlanner 为什么不用 Embedding 或第二次 LLM？

第一版目标是稳定、低成本地通过 20K 预检。Planner 用 topic/questions 关键词覆盖、来源等级、偏好类型、多样性、去重、同来源占比、长度和 token 估算做确定性排序。相同输入集合和预算得到相同 ID，顺序打乱也不变。用 LLM 先压缩再 synthesis 会多一次成本，还把“压缩是否忠实”变成新的 grounding 问题；Embedding/Reranker 则会增加依赖和不可重复因素。

## 22. 22 条 Evidence 为什么最后是 6 条？

当时全量 Evidence 估算 35,313 tokens，超过 20K 上下文预检。系统先计算固定 prompt、Profile、问题、schema、completion 与安全余量，将 Evidence 上限确定为 14,345；Planner 在相关性和来源覆盖约束下选出 6 条，估算 9,640，连同 prompt 预估 9,795，留出了充足余量。完整 22 条仍保存在 EvidenceStore，只是没有全部进入这一次模型调用。

## 23. Token 估算和真实 usage 为什么不同？

估算用于调用前安全决策，真实 usage 是 API 返回的计费/上下文统计，两者定义和 tokenizer 可能不同。该次 Planner 报告的 selected evidence estimate 是 9,640，而 API 最终 prompt tokens 是 5,479；系统分别记录，不能把字符数或估算值说成真实 token。保守估算宁可多留余量，避免接近模型上限后因 schema 或系统提示变化而失败。

## 24. GroundingValidator 能保证模型没有幻觉吗？

不能。当前 Validator 能证明每个 finding 至少引用一个存在、属于 SelectedEvidence 的 ID，并拒绝未知或被排除 Evidence。这解决“引用不存在”或“模型引用未提供材料”的结构问题，但不判断 statement 是否被该 Evidence 语义蕴含，也不验证法规解释是否正确。真实结果是 8/8 ID-level grounded，不应描述成零幻觉或语义准确率 100%。

## 25. 扫描 PDF 为什么不做 OCR？

首版验证的是 Workflow 和数据契约，不是文档智能平台。Docling、EasyOCR、TableFormer 或大型模型会显著增加安装、计算、错误类型和测试成本，也会偏离 2–3 来源的最小真实任务。系统优先解析 text PDF；抽不到足够文本时标记 `UNSUPPORTED_SCAN_PDF`，继续其他来源并写 limitation。未来 OCR 应作为可插拔 extractor，单独有资源和质量治理。

## 26. 下载失败时为什么 Workflow 还能完成？

公开站点常有 403、TLS、跳转或临时不可用。只要剩余来源能形成足够 Evidence，系统可以输出 `PARTIAL` ResearchResult，并明确 download failure、limitations 和 unresolved questions，而不是把整个任务伪装成成功或用常识补齐。真实运行就是 2 success/1 failure，仍形成 22 条 Evidence。若 Evidence 不足，则返回 `INSUFFICIENT_EVIDENCE`，不会生成确定性专业结论。

## 27. Windows Docker Sandbox 修了什么？

Docker SDK 在 Windows named pipe 返回 `NpipeSocket` 类似对象，原代码强制访问内部 `_sock`，但该对象没有这个属性，所以 23 个 sandbox 测试在 create 阶段失败。修复改为依赖 socket-like 对象的公开行为，如 send/recv/close，而不是 Docker SDK 私有实现，同时用兼容测试保持 Unix socket 行为。另一个 stale test 仍断言 Python 3.10，但项目 requirement 和镜像已经是 3.12，因此按真实契约更新了测试。最终 Sandbox 28 项通过。

## 28. 如何证明二次开发没有破坏原 OpenManus？

第一，代码边界上没有修改 BaseAgent、ReActAgent、ToolCallAgent 和 Manus 核心语义，Research 使用独立入口。第二，建立 Python 3.12 和真实依赖环境，Docker daemon 正常后让 Sandbox 测试真正执行，而不是 mock 或 skip。第三，每阶段都跑 Minimal Core、Live Workflow、Reliability、Sandbox 和全项目回归，最终是 361 passed，同时 `main.py --help`、`run_research.py --help`、import smoke 和 pip check 通过。

## 29. 项目离生产级还差什么？

最主要是 Reliability 尚未成为所有 Agent/Tool 的统一执行控制面，TaskPolicy 在 Research 中仍是 observer；没有分布式状态恢复、全局 deadline、跨进程预算、语义 entailment validator、大规模来源和模型矩阵验证，也未支持 OCR 或复杂表格。当前结果更准确地说是“有完整真实闭环和可靠性基元的工程原型”。下一步应先做统一 operation integration 和真实故障演练，而不是马上堆 Multi-Agent 或 GraphRAG。

## 30. 项目中最有价值的一次真实问题定位是什么？

Full Regression 一开始被 Docker 阻断，daemon 启动后仍有 13 failed/10 errors。没有直接 skip，而是逐项归因，发现绝大多数来自 Windows `NpipeSocket` 与 `_sock` 私有属性不兼容，剩余是 Python 3.10/3.12 契约漂移。通过读取 Docker SDK 返回对象并做容器 socket smoke，确认应该依赖公开 socket-like 行为；再根据 pyproject、镜像和测试意图判定正式版本是 3.12。最小修复后 Sandbox 从大量失败到全部通过，也证明问题与 Knowledge Research 新代码无关。
