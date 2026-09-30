# Autoware 公共语料

此目录是公网 RAG 运行时使用的固定 Autoware Universe 规划资料快照，不是完整仓库镜像，也不是中英文全量文档。当前仅收录 11 份不同的英文规划资料，涉及 Planning 概览、Start Planner、Goal Planner、Planning Validator、Trajectory Checker 和 Trajectory Validator 的设计/配置说明。

| 版本 | 固定上游 commit | 收录来源 |
| --- | --- | ---: |
| 0.51.0 | `d4d260983d357e1b2b34291d91933f9f4b53bf94` | 11 |
| 0.52.0（默认） | `6e477c645efec33f7909095eea684474e97f5e3d` | 11 |

总计 22 条版本化官方来源（每个版本 11 条，同一文档跨版本重复计数）、11 份不同文档、410 个文本片段。运行时根据 `corpus_manifest.json` 中的 SHA-256 校验每个源文件、索引片段和向量文件；所有来源保留固定版本 GitHub 链接、commit、路径、语言和 Apache-2.0 许可信息。启动服务不会访问上游或重建索引。

当前资料可支持路径生成策略、规划参数及规划/轨迹验证主题的版本内检索和跨模块影响候选发现；未覆盖完整行为路径规划与速度规划链路。后续扩充优先考虑两个固定版本均有的上游资料：`planning/autoware_freespace_planner/README.md`（自由空间规划）和 `planning/behavior_velocity_planner/autoware_behavior_velocity_intersection_module/README.md`（路口行为速度规划）。这两份资料目前尚未入库、未计入评测成绩；导入后必须更新冻结题集和重新评测，不能沿用当前报告指标。

默认 `current_version` 是此项目最新一次人工核验并随代码发布的版本，不代表服务会自动追踪 Autoware 的新版本。更新版本时，应先更新 `config/autoware_source_selection.json` 的固定 commit，运行 `scripts/fetch_autoware_sources.py` 与 `scripts/sync_autoware_sources.py`，复核 license、引用和索引差异，然后用新的冻结评测集验证再发布。

KEP 不在该语料中。其提案治理思路只作为 Agent 变更上下文和人工审核流程的设计启发；此项目不宣称兼容 Kubernetes KEP 标准。

图像盘点、哈希校验和人工复核边界见 [`FIGURE_EVIDENCE.md`](FIGURE_EVIDENCE.md)。本地检索题、策略对照与非劣化门槛见 [`evaluation/autoware_retrieval_v1`](../../evaluation/autoware_retrieval_v1/README.md)。
