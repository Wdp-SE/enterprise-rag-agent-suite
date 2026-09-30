# Autoware 公共语料

此目录是公网 RAG 运行时使用的固定 Autoware Universe 规划资料快照，不是完整仓库镜像，也不是中英文全量文档。当前收录 13 份不同的英文规划资料，涉及 Planning 概览、Start/Goal Planner、Freespace Planner、Intersection Velocity Planner，以及 Planning Validator、Trajectory Checker 和 Trajectory Validator。

| 版本 | 固定上游 commit | 收录来源 |
| --- | --- | ---: |
| 0.51.0 | `d4d260983d357e1b2b34291d91933f9f4b53bf94` | 13 |
| 0.52.0（默认） | `6e477c645efec33f7909095eea684474e97f5e3d` | 13 |

总计 26 条版本化官方来源（每个版本 13 条，同一文档跨版本重复计数）、13 份不同文档、562 个文本片段。运行时根据 `corpus_manifest.json` 中的 SHA-256 校验每个源文件、索引片段和向量文件；所有来源保留固定版本 GitHub 链接、commit、路径、语言和 Apache-2.0 许可信息。启动服务不会访问上游或重建索引。

当前资料可支持路径生成、自由空间规划、路口速度决策及规划/轨迹验证主题的版本内检索和跨模块影响候选发现；仍未覆盖完整 Autoware Planning 链路。新增语料让冻结评测可以覆盖 Freespace 输入/重规划行为、Intersection 的 RightOfWay/碰撞与遮挡处理，并增加跨来源验证和领域内无答案题。当前 43 道检索题分为 DEV 32、HOLDOUT 11；V3 报告显示 Holdout 必需来源召回为 91.67%、完整来源率为 90%、图片证据命中 2/2、错版本为 0。无答案题仍返回候选，拒答能力没有被证明。评测细节见 [Autoware 检索评测 V3](../../evaluation/autoware_retrieval_v3/README.md)。

默认 `current_version` 是此项目最新一次人工核验并随代码发布的版本，不代表服务会自动追踪 Autoware 的新版本。更新版本时，应先更新 `config/autoware_source_selection.json` 的固定 commit，运行 `scripts/fetch_autoware_sources.py` 与 `scripts/sync_autoware_sources.py`，复核 license、引用和索引差异，然后用新的冻结评测集验证再发布。

KEP 不在该语料中。其提案治理思路只作为 Agent 变更上下文和人工审核流程的设计启发；此项目不宣称兼容 Kubernetes KEP 标准。

图像盘点、哈希校验和人工复核边界见 [`FIGURE_EVIDENCE.md`](FIGURE_EVIDENCE.md)。策略对照、来源覆盖、无答案候选和评测指纹见 [`evaluation/autoware_retrieval_v3`](../../evaluation/autoware_retrieval_v3/README.md)。
