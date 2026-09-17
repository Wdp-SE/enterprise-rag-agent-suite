# Runtime Baseline Verification Report

验证日期：2026-08-28  
验证范围：现有比赛 RAG 的运行时基线，不包含 Confidence Gate、Candidate、Metadata、Version、Knowledge Health、BM25、Agent 或 UI。

## 1. 结论

当前项目已经从“代码级 Reliable Baseline”推进到“真实可运行、结果可追溯的 Runtime Baseline”：完整环境可安装，CLI 可启动，5 份 PDF 已真实解析，旧 FAISS 未被使用，新索引全部由归一化向量重建，15 个问题全部通过真实 DashScope/Qwen 链路运行并留下分数、引用、延迟和 token 记录。

该结论不等于回答质量已经达到生产可信要求。正式运行中 15 题有 4 题未匹配人工核对后的期望值；有答案和无答案问题的向量分数明显重叠，且同一无答案 Boolean 问题在两轮 `temperature=0` 调用中出现过 `False` 与 `N/A` 的差异。下一阶段可以进入 Competition Decoupling，但不能把当前系统描述为生产级可信问答系统。

## 2. 环境恢复

环境检查结果：

- Python 3.11.3，pip 25.2。
- `pip check`：`No broken requirements found`。
- `main.py --help` 可正常加载，5 个 CLI 命令均可发现。
- 完整 pytest：31 passed，1 个 DashScope Assistants API 弃用警告。
- 在线 Provider：DashScope 中国区端点。

关键运行版本：

| 依赖 | 验证版本 | 说明 |
| --- | ---: | --- |
| docling | 2.14.0 | 保持项目原始主版本 |
| docling-core | 2.14.0 | 避免新版移除旧 `BoundingBox` 接口 |
| docling-ibm-models | 3.1.2 | 与 Docling 2.14 兼容 |
| docling-parse | 3.0.0 | 与 Docling 2.14 兼容 |
| torch | 2.4.0+cpu | 官方 Windows CPU wheel；PyPI 自动选中的 wheel 无法加载 `c10.dll` |
| torchvision | 0.19.0+cpu | 与 Torch 2.4.0 配套 |
| faiss-cpu | 1.9.0.post1 | `IndexFlatIP` |
| dashscope | 1.27.2 | 实际在线调用版本 |
| pydantic | 2.9.2 | Structured Output 校验 |

`qwen-turbo-latest` 在当前账号/端点返回 403 AccessDenied，而显式 `qwen-turbo` 返回 200。因此 Answer 和 Rerank 的 DashScope 默认模型改为 `qwen-turbo`；这不是把其他 Provider 移除，OpenAI、Gemini、IBM 的分支仍保留，并继续执行 provider/model 组合校验。

## 3. 测试文档与解析

使用 5 份仓库已有公开年报作为运行时小样本：

| 文档 | 结构化页数 | Chunk 数 | 解析状态 |
| --- | ---: | ---: | --- |
| Holley Inc. | 131 | 462 | 成功 |
| Tradition | 152 | 377 | 成功 |
| TSX_Y | 76 | 264 | 成功；源 PDF 物理页 1 未生成内容页，输出页码为 2–77 |
| Mercia Asset Management PLC | 120 | 376 | OCR 空裁剪失败后，以显式 `do_ocr=False` 文本解析成功 |
| CrossFirst Bank | 120 | 445 | 成功 |

共得到 599 个结构化页面、1,924 个 chunk。所有 chunk 的 `page` 都能在所属文档的 parent pages 中找到，15/15 次实际检索返回的 parent page 文本也与所属页面一致。

Windows 当前工作区包含中文路径，Docling Parse v2 的原生扩展无法直接从该路径加载资源/打开 PDF。本次通过指向同一仓库的 ASCII junction 运行解析；这是环境限制，不是数据被复制或替换。该限制已列入已知问题。

## 4. FAISS 重建与核验

本轮运行目录在建库前不存在 FAISS 文件，仓库内旧的未归一化索引没有被加载或覆盖。

真实建库链路：

```text
PDF → Docling Parsing → Page Merge → Token Chunking
    → DashScope text-embedding-v1 → L2 Normalize
    → FAISS IndexFlatIP
```

核验结果：

- 5/5 索引类型为 `IndexFlatIP`，metric 为 inner product。
- 5/5 索引的向量数与 chunk 数一致。
- 文档向量范数范围为 0.99999988–1.00000012，均通过 `atol=1e-4` 检查。
- 15 个真实查询的归一化后范数为 0.99999994–1.0。
- 所有实际检索分数均在 [-1, 1]；本次观察范围为 0.3882–0.8150。
- 最小在线 Embedding 冒烟中，1536 维原始向量范数为 123.969925，入库向量范数为 1.0，自相似分数为 1.0。

因此，本轮新索引中的 inner product 可以解释为 cosine similarity。旧索引仍必须重建，不能通过代码声明直接变成 cosine 索引。

## 5. Structured Output、Rerank 与 Boolean

在线最小冒烟：

- Qwen Structured Output 返回后类型为 Python `dict`，字段 `status=ok`，不是未解析 JSON 字符串；usage 为 93 prompt tokens / 6 completion tokens。
- Qwen Rerank 对“设备资本支出”和“天气”两个文本分别给出 0.7 与 0.1，证明 relevance score 不再固定为 0。
- Boolean N/A 控制探针返回结构化 `final_answer="N/A"`，usage 为 682 / 135 tokens，证明 Schema 与真实 Qwen 调用都能表达 N/A。

15 题正式运行：

- 15/15 无异常。
- 15/15 返回并解析为完整 Answer Schema。
- 14/15 的 Rerank 后页码顺序与向量初排不同。
- 真实最终答案覆盖 `True`、`False`、`N/A`、字符串和数字。
- 首轮审计运行也被保存在 `baseline_queries_run1.json` 和 `baseline_results_run1.json`。首轮暴露了 3 个测试标签/措辞问题，正式问题集在核对解析原文后修正，没有修改任何模型输出。

正式运行的人工对照结果：

| ID | 期望 | 实际 | 结果 | 主要现象 |
| --- | --- | --- | --- | --- |
| Q01 | True | True | PASS | 正常可回答 |
| Q02 | 20,500,000 | N/A | MISS | 正确页 8 未进入 Top-K，属于 retrieval miss |
| Q03 | 12.7 | 11.4 | MISS | 取到了 IDB 子业务 margin，而非集团 margin |
| Q04 | N/A | N/A | PASS | Boolean N/A |
| Q05 | False | False | PASS | Boolean False |
| Q06 | True | True | PASS | Boolean True |
| Q07 | True | True | PASS | 正常可回答 |
| Q08 | False | N/A | MISS | “未宣布”与“上下文不足”的语义边界仍需固定 |
| Q09 | True | True | PASS | 正常可回答 |
| Q10 | Michael J. Maddox | Michael J. Maddox | PASS | 修正了首轮 President/CEO 拆分导致的歧义措辞 |
| Q11 | 36,000,000 | 36,000,000 | PASS | 数字回答 |
| Q12 | False | False | PASS | 文档明确写明 None |
| Q13 | N/A | N/A | PASS | Boolean N/A |
| Q14 | N/A | N/A | PASS | 不存在页面/答案 |
| Q15 | 3 个 2022 收购对象 | N/A | MISS | Top1 分数虽高，但正确页 4 未进入 Top-K |

简单精确匹配为 11/15。该数字只用于本轮小样本诊断，不是比赛分数，也不是正式业务准确率。

## 6. Citation 核验

- 15/15 题的 validated citations 都属于目标 PDF，且页码存在于最终选中的 parent pages。
- Q04、Q08、Q13、Q14、Q15 的模型页码声明为空，最终引用保持为空，没有自动补页。
- 正式运行中模型没有自然产生未检索页码，因此 `filtered_hallucinated_pages` 均为空。
- 独立验证探针传入 `[11, 999]` 时只保留 `[11]`；传入空声明时返回空列表。
- 比赛输出兼容测试确认：内部 1-based 页码仍在 submission 后处理阶段转换为原格式的 0-based `page_index`，字段结构未改变；N/A submission 仍清空引用。

当前 Citation 校验只能证明“页码来自检索集合”，不能证明该页在语义上充分支持结论。Boolean N/A 控制探针曾声明一个存在但不支持结论的页面，这说明未来仍需要 Evidence Confidence，而不是进一步放宽页码校验。

## 7. Latency 与 Token

15 题正式运行统计：

| 指标 | 平均 | 中位数 | 最小 | 最大 | 合计 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Retrieval latency | 174.72 ms | 163.52 ms | 132.59 ms | 303.88 ms | - |
| Rerank latency | 4,840.37 ms | 4,982.16 ms | 2,785.03 ms | 6,434.21 ms | - |
| Generation latency | 2,096.82 ms | 1,933.44 ms | 1,646.82 ms | 2,947.16 ms | - |
| Total latency | 7,117.11 ms | 7,111.96 ms | 4,994.07 ms | 8,687.00 ms | 106,756.64 ms |
| Prompt tokens | 11,800.80 | - | 7,526 | 16,221 | 177,012 |
| Completion tokens | 772.87 | - | 516 | 948 | 11,593 |
| Total tokens | 12,573.67 | - | 8,268 | 17,169 | 188,605 |

Token 合计包含 29 次 Rerank 调用和 15 次 Generation 调用。DashScope Embedding 响应未提供同口径 token usage，因此未计入，JSON 中显式记录 `embedding_usage_included=false`。

## 8. 为 Confidence Gate 保留的分数现象

本轮没有实现或设置阈值，只保存观察值：

| 分组 | 数量 | Top1 最小 | Top1 平均 | Top1 最大 | 最大 Rerank 分平均值 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 期望可回答 | 12 | 0.4336 | 0.6615 | 0.8150 | 0.8083 |
| 期望无答案 | 3 | 0.4943 | 0.5696 | 0.6125 | 0.2333 |

向量 Top1 明显重叠：无答案 Q13/Q14 的 Top1 分别达到 0.6125/0.6020，而可回答 Q03 只有 0.4336。不能仅凭单一 similarity threshold 拍脑袋拒答。Rerank 分对本样本的区分更明显，但 Q07/Q12 等有效问题的最大 rerank 也只有 0.4，仍需后续用更大的固定集设计组合规则。

## 9. 安全检查

- 对所有已配置 Provider secret 与 `artifacts/baseline_runtime` 下文本型产物逐一比对：0 个泄漏文件。
- `baseline_results.json` 只保存检索文本长度和 SHA-256，不保存完整检索页面原文。
- Rerank 缺失结果日志只记录 page、文本长度和 SHA-256 前缀。
- Provider 错误只记录 status/code/message/request_id，不输出 API Key 或完整请求内容。

## 10. 新发现问题

1. Docling 2.14 的依赖范围过宽，必须固定兼容的 core/model/parse 版本。
2. Windows PyPI Torch wheel 在本机无法加载 `c10.dll`，需使用官方 CPU wheel 组合。
3. Docling Parse v2 在中文仓库路径下存在原生路径兼容问题，目前需 ASCII 路径入口。
4. EasyOCR 对 Mercia PDF 的空裁剪崩溃；文本型 PDF 可显式禁用 OCR 降级，默认行为未改变。
5. `qwen-turbo-latest` 对当前 DashScope 账号不可用，显式 `qwen-turbo` 可用。
6. 4/15 题存在检索、粒度匹配或无答案语义问题；尤其 Q15 展示了“高 Top1 分数但错过正确页”。
7. `temperature=0` 不能保证 DashScope 输出完全确定；首轮 Q04/Q13 为 False，正式轮为 N/A。
8. Citation 目前验证来源成员关系，不验证证据是否充分支持答案。
9. 当前 token 统计不包含 Embedding token。

## 11. 是否进入 Competition Decoupling

可以进入，理由是运行环境、索引语义、Provider 调用、Structured Output、Rerank、Parent Page、Citation 过滤和观测数据都已真实跑通并可复核。

进入下一阶段时应冻结本报告与正式 `baseline_results.json`，保持本轮不增加 Confidence Gate 的决定。当前系统适合作为 Competition Decoupling 的可执行基线，但不适合宣称已具备生产级可信拒答或稳定答案准确率。
