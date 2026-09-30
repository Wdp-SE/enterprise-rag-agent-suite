# Autoware 双语公开研发资料语料

本目录是用于公开演示的固定语料快照，覆盖 Autoware Documentation 和 Universe Planning 资料。它不是完整 Autoware 镜像，也不是官方认证的中文知识库。

| 检索范围 | 来源内容 | 版本化来源数 |
| --- | --- | ---: |
| `latest`（默认组合范围） | 官方 Documentation `main` 英文 431 页 + 社区中文译文 260 页 + Universe Planning 0.52.0 英文 13 份 | 704 |
| `docs-main` | 官方 Documentation `main` 英文资料 + 社区中文译文 | 691 |
| `1.9.0` | 官方 Documentation 稳定文档发布版英文资料 | 431 |
| `0.52.0` | Autoware Universe Planning 英文历史/当前演示快照 | 13 |
| `0.51.0` | Autoware Universe Planning 英文基线快照 | 13 |

当前总计 1,148 条版本/语言来源、660 个不同资料主题/路径、7,927 个检索片段。两条已人工复核的 Universe 截图 OCR 证据继续作为派生证据保留，不等同于原始文档正文。

默认 `latest` 是**组合检索范围**，由固定的 Documentation `main` 快照与 Universe `0.52.0` 快照组成；这两个仓库版本号含义不同，不代表同一 Autoware 软件发行版。它只表示本仓库选择并固定的最新演示资料组合，不会跟踪上游实时变化。Documentation `1.9.0`、Universe `0.52.0` 与 `0.51.0` 都可以单独检索。

中文资料来自 [Tomato ROS 社区翻译仓库](https://github.com/tomato-ros/autoware-documentation-cn)，固定到 commit `eb089f637534f1e84b8d0c950be1ab302ee22c50`。本次从 HTML 页面提取正文、标题、列表、表格和代码块，保存本地可索引的 Markdown；每页同时记录固定 HTML commit、原始 HTML SHA、社区网页、canonical URL 与路径核验状态。260 页中有 44 页的 canonical 路径匹配到固定的官方 Documentation `main` 快照；216 页找不到同路径英文原文，仍标为独立社区资料，**不推断它们对应当前官方英文版本，也不声称逐句翻译已经审核**。社区网页链接用于阅读，固定 Git commit 与 SHA 才是本语料的来源快照。

官方英文资料来自 [Autoware Documentation](https://github.com/autowarefoundation/autoware-documentation)，`main` 固定到 `f43b9606771ec6badf51d03131d73c0f7b708049`，稳定文档 `1.9.0` 固定到 `664ae9421d39943b7c7e80f64eba184e632a44bb`。Universe Planning 两个快照分别固定到 `0.51.0` 的 `d4d260983d357e1b2b34291d91933f9f4b53bf94` 与 `0.52.0` 的 `6e477c645efec33f7909095eea684474e97f5e3d`。三个来源仓库的公开资料采用 Apache-2.0；详细来源、路径、commit、许可与文件 SHA 记录在 [`corpus_manifest.json`](corpus_manifest.json)，版权文本和归属见 [`LICENSE`](LICENSE) 与 [`NOTICE`](NOTICE)。

图片处理有明确边界：导入器只索引社区 HTML 中可见的图片说明/alt 文本，并标明图像像素未执行 OCR；不会把图形本身的细节伪装成检索事实。两张 Universe 截图的既有人工复核 OCR 仍绑定原图 SHA。需要图片问答时，应增加经人工核对的图像题与图片证据，不能仅凭资料数量推断图像覆盖已经解决。

语料扩展后，检索策略恢复为 BM25 基线；旧 43 题 Autoware V3 评测指纹不匹配此语料，现阶段不代表新双语语料成绩。新的中英文冻结题集与跨资料、错版本、无答案及图像问题评测完成前，不宣称准确率或最优策略。参见 [`evaluation/autoware_bilingual_v1`](../../evaluation/autoware_bilingual_v1/README.md)。

服务启动时校验 manifest、每份本地资料的 SHA、生成的索引和策略指纹；请求时不访问 GitHub，也不抓取最新内容。同步来源需要审核所选 commit 与 Apache-2.0 许可，再运行 `scripts/import_autoware_documentation.py` 重建索引、更新摘要并重新执行双语评测。
