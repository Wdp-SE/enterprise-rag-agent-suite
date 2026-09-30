# 图片证据复核记录

`figure_evidence.json` 从 22 份固定提交的 Markdown 来源中登记了 74 个图像引用。图片内容默认不从 alt text 推断。服务仅索引两张经下载哈希校验、内容复核并绑定来源段落的图中文字；其余图保持不可检索，避免把装饰图、流程连线或 OCR 噪声误当事实。

| 版本 | 文档段落 | 图片 | 图片 SHA-256 | 复核内容 |
| --- | --- | --- | --- | --- |
| 0.52.0 | `planning/start_planner/design` · Start Planner search priority | `priority_order.drawio.svg` | `b32a65495249827b66d41acb69bb4547b9b81ad567217793368dc9d489460955` | 复核 Draw.io 内嵌标签：`planner_priority`、`distance_priority`、`high priority`、`low priority`、`shift_pull_out`、`geometric_pull_out`；只保留明示标签，不推断箭头语义或安全行为。 |
| 0.52.0 | `planning/goal_planner/design` · Goal Search | `goal_priority_object_to_avoid_rviz.png` | `f196a0d87c1954bf2712fb3f0f22abbc37e10bc5f784ec0c3db6253666bef5a7` | 人工确认仅将清楚可读的 “outside drivable area” 与 “obstacle stop” 两个标签转成检索文本；不解释颜色、几何或运行结果。 |

派生记录包含上游 commit、原始图 URL、源文档/段落、原图哈希、复核说明和审核文本，见 `figure_evidence.json` 与 `figure_evidence_reviewed.json`。启动时 `figure_evidence_reviewed.lock.json` 校验 sidecar，检索时再按语料清单和版本核验引用关系。图片策略命中至少两个来自审核图中文字的词，并优先替换同一来源的重复文字片段；如果 Top-5 已包含五个不同来源，就不为插图挤掉任一独立来源。

Tesseract/OCR 只用于离线候选，自动输出默认不入索引；人工复核是进入 sidecar 的前提。SVG 的 Draw.io 数据只提取显式文本，没有将位置、连线或布局转换成逻辑事实。图片不在用户请求中联网获取，也不调用在线视觉模型。当前只有两张图通过复核，因此评测中的 2/2 图片命中是一个很小的功能性回归集，不代表 Autoware 全量图片召回率。
