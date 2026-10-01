"""Build deterministic, source-checked Autoware V2 evaluation cases.

Questions and answer points below are manually curated from the pinned corpus.
The script checks every source, relation label and figure ID before writing JSONL.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "versioned-rag-service" / "public_corpus_autoware"
HERE = Path(__file__).resolve().parent


TOPICS = {
    "dev": [
        {
            "key": "autoware-documentation/contributing/coding-guidelines/ros-nodes/console-logging",
            "q_en_zh": "Which groups does the Chinese Autoware logging guide say rely on ROS 2 console logs?",
            "point_zh": "开发者用日志调试代码，车辆操作员据此采取风险规避行动，日志分析人员分析 rosbag 中记录的日志。",
            "q_zh_en": "Autoware ROS 2 控制台日志面向哪些使用角色？",
            "point_en": "The guide names developers debugging code, vehicle operators taking risk-avoiding actions, and log analysts reviewing rosbag recordings.",
            "q_fact": "How does the Autoware guide recommend using console logs during development and operation?",
            "point_fact": "Logs support developer debugging, operator risk-avoiding actions, and analysis of rosbag-recorded logs.",
        },
        {
            "key": "autoware-documentation/contributing/coding-guidelines/ros-nodes/coordinate-system",
            "q_en_zh": "Which coordinate frames are listed in the Chinese Autoware ROS-node guide?",
            "point_zh": "列出的坐标系包括世界坐标系、车辆坐标系和传感器坐标系。",
            "q_zh_en": "Autoware 常用的坐标系包括哪些？",
            "point_en": "The guide lists world, vehicle, and sensor coordinate systems.",
            "q_fact": "Which coordinate frames does Autoware commonly use to represent vehicle and sensor state?",
            "point_fact": "The documented frames are world, vehicle, and sensor coordinate systems.",
        },
        {
            "key": "autoware-documentation/contributing/coding-guidelines/ros-nodes/parameters",
            "q_en_zh": "How are declared ROS-node parameter values supplied at startup according to the Chinese guide?",
            "point_zh": "参数值在节点启动期间通过参数文件提供，文件应包含预期参数及对应值。",
            "q_zh_en": "Autoware ROS 节点启动时，声明的参数值从哪里读取？",
            "point_en": "Declared parameter values are supplied in a parameter file during node startup, and expected parameters should be present with values.",
            "q_fact": "When are declared parameter values supplied to an Autoware ROS node?",
            "point_fact": "The parameter file provides declared values during node startup.",
        },
        {
            "key": "autoware-documentation/contributing/coding-guidelines/ros-nodes/message-guidelines",
            "q_en_zh": "Which ROS interface file formats does the Chinese Autoware message guide accept?",
            "point_zh": "文档列出的格式为 .msg、.srv 和 .action。",
            "q_zh_en": "Autoware 消息指南接受哪些 ROS 接口文件格式？",
            "point_en": "The accepted formats are .msg, .srv, and .action.",
            "q_fact": "Which interface file extensions are listed in Autoware's message guidelines?",
            "point_fact": "The guide lists .msg, .srv, and .action.",
        },
        {
            "key": "autoware-documentation/contributing/coding-guidelines/ros-nodes/launch-files",
            "q_en_zh": "Which launch system does the Chinese Autoware guide use to start the software?",
            "point_zh": "Autoware 使用 ROS 2 launch 系统启动软件。",
            "q_zh_en": "Autoware 使用什么启动系统来启动软件？",
            "point_en": "Autoware uses the ROS 2 launch system to start the software.",
            "q_fact": "Which system is documented as the software startup mechanism for Autoware?",
            "point_fact": "The guide identifies the ROS 2 launch system.",
        },
        {
            "key": "autoware-documentation/contributing/coding-guidelines/ros-nodes/topic-namespaces",
            "q_en_zh": "Why does the Chinese Autoware guide recommend namespaces for ROS topics and nodes?",
            "point_zh": "命名空间可避免多个同类节点命名冲突、保持关注点分离并减少根命名空间混乱。",
            "q_zh_en": "ROS 命名空间可以帮助 Autoware 避免哪些问题？",
            "point_en": "Namespaces avoid name clashes between node instances, keep concerns separated, and reduce root-namespace clutter.",
            "q_fact": "What problems do ROS namespaces help prevent in Autoware?",
            "point_fact": "They prevent naming clashes, help separate concerns, and avoid root-namespace clutter.",
        },
        {
            "key": "autoware-documentation/contributing/testing-guidelines/unit-testing",
            "q_en_zh": "Which test frameworks does the Chinese Autoware unit-testing page list for ament_cmake?",
            "point_zh": "页面列出 pytest、gtest 和 gmock。",
            "q_zh_en": "Autoware 的 ament_cmake 单元测试列举了哪些测试框架？",
            "point_en": "The page lists pytest, gtest, and gmock.",
            "q_fact": "Which test frameworks are listed for CMake-based Autoware packages?",
            "point_fact": "The listed frameworks are pytest, gtest, and gmock.",
        },
        {
            "key": "autoware-documentation/contributing/testing-guidelines/integration-testing",
            "q_en_zh": "When does integration testing take place in the Chinese Autoware testing guide?",
            "point_zh": "集成测试在单元测试之后、验证测试之前执行。",
            "q_zh_en": "Autoware 的集成测试位于单元测试和验证测试的什么位置？",
            "point_en": "Integration tests follow unit tests and precede validation tests.",
            "q_fact": "What testing phases come immediately before and after integration testing?",
            "point_fact": "Unit testing comes before integration testing; validation testing comes after it.",
        },
        {
            "key": "autoware-documentation/datasets/data-anonymization",
            "q_en_zh": "What does the Chinese Autoware guide say the rosbag anonymizer can blur?",
            "point_zh": "该工具可模糊 ROS 2 bag 中的对象，例如人脸和车牌，以便在保护隐私的同时分享数据。",
            "q_zh_en": "Autoware 的 rosbag 匿名化工具可以处理哪些隐私对象？",
            "point_en": "The tool can blur objects such as faces and license plates in ROS 2 bag files before sharing.",
            "q_fact": "Which personal details does the documented rosbag anonymizer remove before data sharing?",
            "point_fact": "It can blur objects such as faces and license plates in ROS 2 bag files.",
        },
        {
            "key": "autoware-documentation/design/autoware-concepts",
            "q_en_zh": "How does the Chinese Autoware concepts page describe the Core/Universe architecture?",
            "point_zh": "该架构将软件栈模块化为 Core 和 Universe 子系统。",
            "q_zh_en": "Autoware 的 Core/Universe 架构如何组织软件栈？",
            "point_en": "The architecture modularizes the software stack into Core and Universe subsystems.",
            "q_fact": "What are the two subsystems named in the Autoware Core/Universe architecture?",
            "point_fact": "They are Core and Universe.",
        },
    ],
    "holdout": [
        {
            "key": "autoware-documentation/contributing/documentation-guidelines",
            "q_en_zh": "What does the Chinese Autoware documentation guide recommend before starting a large documentation change?",
            "point_zh": "较大的文档改动应先通过 GitHub Discussions 与社区及维护者讨论。",
            "q_zh_en": "Autoware 文档指南建议大型文档改动先做什么？",
            "point_en": "Large documentation changes should be discussed with the community and maintainers through GitHub Discussions first.",
            "q_fact": "How should a contributor begin a large-scale Autoware documentation change?",
            "point_fact": "Discuss it with the community and maintainers through GitHub Discussions before starting.",
        },
        {
            "key": "autoware-documentation/contributing/license",
            "q_en_zh": "Which license does the Chinese Autoware contribution guide apply to the project?",
            "point_zh": "Autoware 根据 Apache License 2.0 获得许可。",
            "q_zh_en": "Autoware 项目采用什么许可证？",
            "point_en": "Autoware is licensed under Apache License 2.0.",
            "q_fact": "Which license governs Autoware contributions according to the project guide?",
            "point_fact": "The guide identifies Apache License 2.0.",
        },
        {
            "key": "autoware-documentation/datasets",
            "q_en_zh": "Who provides the datasets described by the Chinese Autoware documentation?",
            "point_zh": "Autoware 合作伙伴提供用于测试和开发的数据集。",
            "q_zh_en": "Autoware 文档中的测试和开发数据集由谁提供？",
            "point_en": "Autoware partners provide datasets for testing and development.",
            "q_fact": "Who supplies the datasets that Autoware documents for testing and development?",
            "point_fact": "Autoware partners provide them.",
        },
        {
            "key": "autoware-documentation/installation/autoware/docker-installation",
            "q_en_zh": "What are the two Docker image types named in the Chinese Autoware installation guide?",
            "point_zh": "文档列出 devel 和 runtime 两种映像。",
            "q_zh_en": "Autoware 安装指南中的 Docker 映像分为哪两类？",
            "point_en": "The guide names devel and runtime images.",
            "q_fact": "Which two Docker image types are documented for getting started with Autoware?",
            "point_fact": "The documented types are devel and runtime.",
        },
        {
            "key": "autoware-documentation/installation/autoware/source-installation",
            "q_en_zh": "Which operating system and ROS 2 distribution are listed as source-install prerequisites in Chinese?",
            "point_zh": "先决条件列出 Ubuntu 22.04 和 ROS 2 Humble。",
            "q_zh_en": "从源码安装 Autoware 的先决条件列出了哪个 Ubuntu 和 ROS 2 版本？",
            "point_en": "The listed prerequisites include Ubuntu 22.04 and ROS 2 Humble.",
            "q_fact": "Which Ubuntu and ROS 2 versions does the source-installation guide list?",
            "point_fact": "Ubuntu 22.04 and ROS 2 Humble.",
        },
        {
            "key": "autoware-documentation/installation/additional-settings-for-developers/console-settings",
            "q_en_zh": "How can a user enable colored ROS 2 logger output according to the Chinese guide?",
            "point_zh": "将 RCUTILS_COLORIZED_OUTPUT=1 添加到 ~/.bashrc。",
            "q_zh_en": "如何按 Autoware 指南启用 ROS 2 彩色日志输出？",
            "point_en": "Add RCUTILS_COLORIZED_OUTPUT=1 to ~/.bashrc.",
            "q_fact": "Which environment setting enables colored ROS 2 logger output?",
            "point_fact": "Set RCUTILS_COLORIZED_OUTPUT=1 in ~/.bashrc.",
        },
        {
            "key": "autoware-documentation/installation/additional-settings-for-developers/network-configuration/multiple-computers",
            "q_en_zh": "Which configuration file does the Chinese guide use for CycloneDDS interfaces across computers?",
            "point_zh": "指南使用 ~/cyclonedds.xml 配置多台计算机间通信的接口。",
            "q_zh_en": "多台计算机之间配置 CycloneDDS 接口时，指南提到哪个文件？",
            "point_en": "The guide uses ~/cyclonedds.xml to configure interfaces for communication between computers.",
            "q_fact": "Which file is named for configuring CycloneDDS interfaces across multiple computers?",
            "point_fact": "The guide names ~/cyclonedds.xml.",
        },
        {
            "key": "autoware-documentation/contributing/pull-request-guidelines/code-owners",
            "q_en_zh": "What do CODEOWNERS files specify in the Chinese Autoware pull-request guide?",
            "point_zh": "多个 CODEOWNERS 文件用于指定存储库各部分的负责人。",
            "q_zh_en": "Autoware 的 CODEOWNERS 文件用来指定什么？",
            "point_en": "Multiple CODEOWNERS files specify owners throughout the repository.",
            "q_fact": "What repository information is maintained in Autoware's CODEOWNERS files?",
            "point_fact": "They specify owners for areas throughout the repository.",
        },
        {
            "key": "autoware-documentation/contributing/pull-request-guidelines/review-tips",
            "q_en_zh": "Which keyboard shortcuts toggle review annotations and comments in the Chinese guide?",
            "point_zh": "按 A 可切换 diff 注释，按 I 可切换 review comments。",
            "q_zh_en": "在 Autoware 的 diff 审查页面，A 和 I 分别切换什么？",
            "point_en": "A toggles diff annotations and I toggles review comments.",
            "q_fact": "Which keyboard shortcuts toggle diff annotations and review comments?",
            "point_fact": "A toggles annotations and I toggles review comments.",
        },
        {
            "key": "autoware-documentation/design/autoware-concepts/difference-from-ai-and-auto",
            "q_en_zh": "What product generations does the Chinese guide distinguish from current Autoware Core/Universe?",
            "point_zh": "页面区分当前 Autoware Core/Universe 与早期 Autoware.AI 和 Autoware.Auto。",
            "q_zh_en": "Autoware Core/Universe 与哪两个早期 Autoware 版本相区分？",
            "point_en": "The page distinguishes Autoware Core/Universe from earlier Autoware.AI and Autoware.Auto generations.",
            "q_fact": "Which earlier Autoware generations are compared with Core/Universe?",
            "point_fact": "Autoware.AI and Autoware.Auto.",
        },
    ],
}


VERSION_CASES = {
    "dev": [
        ("autoware-documentation/contributing/ai-contribution-policy", "docs-main", "According to the current Autoware AI contribution policy, which contribution activities are in scope?", "It covers code, documentation, pull requests, issues, discussions, reviews, and review responses across Autoware Foundation repositories."),
        ("autoware-documentation/contributing/pull-request-guidelines/ci-checks", "docs-main", "In the current Autoware CI guide, what does a Required check mean for merging a pull request?", "A Required check must be resolved before the pull request can be merged."),
        ("autoware-documentation/demos/planning-sim/traffic-light", "docs-main", "In the current traffic-light simulation guide, what default state is assumed for mapped traffic lights?", "Mapped traffic lights are treated as green by default."),
        ("autoware-documentation/contributing/coding-guidelines/ros-nodes/parameters", "docs-main", "According to the current ROS-node parameter guide, when and where are declared parameter values supplied?", "Declared parameter values are supplied during node startup in a parameter file."),
        ("planning/overview", "0.52.0", "In the Autoware Universe 0.52.0 Planning overview, what three capabilities are highlighted for planning modules?", "The overview highlights route planning, dynamic obstacle avoidance, and real-time adaptation to traffic conditions."),
    ],
    "holdout": [
        ("autoware-documentation/installation/autoware/docker-installation", "1.9.0", "In the Autoware 1.9.0 Docker guide, what image variants are described for different development and runtime needs?", "The guide distinguishes runtime images, devel images, and CUDA variants."),
        ("autoware-documentation/installation/autoware/source-installation", "1.9.0", "Which Ubuntu version and ROS 2 distribution are listed as prerequisites in the Autoware 1.9.0 source-installation guide?", "The prerequisites list Ubuntu 22.04 and ROS 2 Humble."),
        ("autoware-documentation/community/support/troubleshooting/performance-troubleshooting", "1.9.0", "Which CMake build types does the Autoware 1.9.0 performance guide recommend when checking for slow runtime?", "It recommends Release or RelWithDebInfo builds."),
        ("autoware-documentation/community/support/troubleshooting/runtime-troubleshooting", "1.9.0", "In the Autoware 1.9.0 runtime troubleshooting guide, what maximum automatic DDS participant index is described for ROS 2 Jazzy?", "The guide says rmw_cyclonedds_cpp sets MaxAutoParticipantIndex to 32 on ROS 2 Jazzy."),
        ("autoware-documentation/demos/planning-sim/crosswalk", "1.9.0", "In the Autoware 1.9.0 non-signalized crosswalk scenario, what happens when a pedestrian is on the crosswalk?", "The vehicle slows down and stops once, waits briefly, then continues waiting if a pedestrian or object remains on its planned path; otherwise it resumes."),
    ],
}


CROSS_SOURCE = {
    "dev": [
        ("parameter-startup", "How do the ROS-node parameter guide and launch guide describe configuration at startup?", ["autoware-documentation/contributing/coding-guidelines/ros-nodes/parameters", "autoware-documentation/contributing/coding-guidelines/ros-nodes/launch-files"], ["The node receives declared values from a parameter file at startup.", "Autoware uses the ROS 2 launch system to start software."]),
        ("interface-message", "Which interface file formats are accepted, and how should topic-message handling be selected?", ["autoware-documentation/contributing/coding-guidelines/ros-nodes/message-guidelines", "autoware-documentation/contributing/coding-guidelines/ros-nodes/topic-message-handling"], ["The message guide lists .msg, .srv, and .action formats.", "The topic-message guide describes recommended message-handling approaches, including considerations around take() and intra-process communication."]),
        ("test-sequence", "What sequence do the unit-testing and integration-testing guides define?", ["autoware-documentation/contributing/testing-guidelines/unit-testing", "autoware-documentation/contributing/testing-guidelines/integration-testing"], ["Unit tests validate individual code units.", "Integration tests follow unit tests and precede validation tests."]),
        ("log-debug", "How do the logging and debugging guides distinguish log consumers and debugging tools?", ["autoware-documentation/contributing/coding-guidelines/ros-nodes/console-logging", ("zh", "autoware-documentation/how-to-guides/others/debug-autoware")], ["Logs support developers, vehicle operators, and analysts.", "The Chinese debugging guide documents ROS 2 command-line tools for inspecting a running system."]),
        ("frames-map", "How do the coordinate-system and map-component documents describe spatial reference and map data?", ["autoware-documentation/contributing/coding-guidelines/ros-nodes/coordinate-system", "autoware-documentation/design/autoware-architecture-v1/components/map"], ["The guide distinguishes world, vehicle, and sensor frames.", "The map component provides road semantics and environment geometry."]),
    ],
    "holdout": [
        ("docs-review", "How should large documentation changes be proposed, and what information do CODEOWNERS files identify?", ["autoware-documentation/contributing/documentation-guidelines", "autoware-documentation/contributing/pull-request-guidelines/code-owners"], ["Large documentation changes should first be discussed with the community and maintainers.", "CODEOWNERS files specify repository owners."]),
        ("dataset-prerequisites", "Who provides Autoware datasets for testing and development, and which OS and ROS 2 versions are listed for source installation?", ["autoware-documentation/datasets", "autoware-documentation/installation/autoware/source-installation"], ["Autoware partners provide datasets for testing and development.", "The source-installation prerequisites list Ubuntu 22.04 and ROS 2 Humble."]),
        ("install-methods", "What do the Docker and source-installation guides say about supported setup options?", ["autoware-documentation/installation/autoware/docker-installation", "autoware-documentation/installation/autoware/source-installation"], ["Docker setup offers devel and runtime image types.", "The source-install prerequisites include Ubuntu 22.04 and ROS 2 Humble."]),
        ("dds-network", "Which files and settings do the networking guides identify for ROS 2 communication across machines?", ["autoware-documentation/installation/additional-settings-for-developers/network-configuration/dds-settings", "autoware-documentation/installation/additional-settings-for-developers/network-configuration/multiple-computers"], ["The DDS guide documents localhost-only communication and multicast settings.", "The multi-computer guide configures CycloneDDS interfaces in ~/cyclonedds.xml."]),
        ("review-workflow", "Which shortcuts help reviewers inspect a diff, and how does the repository identify code owners?", ["autoware-documentation/contributing/pull-request-guidelines/review-tips", "autoware-documentation/contributing/pull-request-guidelines/code-owners"], ["A toggles diff annotations and I toggles review comments.", "CODEOWNERS identify responsible owners across the repository."]),
    ],
}


NO_ANSWER = {
    "dev": [
        "What is the private access token for Autoware's internal Jira workspace?",
        "Which exact torque value does a specific production vehicle require for its brake actuator?",
        "What unpublished lidar-to-camera calibration matrix is used by a customer fleet?",
        "Which employee approved the latest private safety-case change request?",
        "What is the internal endpoint for changing a company's proprietary vehicle configuration?",
    ],
    "holdout": [
        "What password is used for an organization's private Autoware deployment registry?",
        "Which customer-specific braking threshold is approved in the private vehicle safety file?",
        "What exact internal approval timestamp is recorded for an unreleased vehicle change?",
        "Which confidential hardware serial number is paired with a fleet's calibration dataset?",
        "What internal Jira reviewer list is configured for a company's release workflow?",
    ],
}


IMAGE_QUESTIONS = {
    "32682b345ea86e13": [
        "Which visible labels appear in the Goal Planner figure for the outside-drivable area and obstacle stop?",
        "What two readable labels identify the drivable-area boundary and obstacle stopping in the Goal Planner diagram?",
        "In the reviewed Goal Planner image, what labels are printed for the outside drivable area and the stop?",
    ],
    "876db03219da6219": [
        "Which planner-priority and distance-priority labels appear in the Start Planner search diagram?",
        "What candidate planner types are named in the reviewed Start Planner priority figure?",
        "Which priority labels and pull-out planner names are readable in the Start Planner diagram?",
    ],
}


def _portable_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _jsonl_bytes(rows: list[dict]) -> bytes:
    return ("".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for row in rows)).encode("utf-8")


def _family_id(source_id: str) -> str:
    version, _language, document_key = source_id.split(":", 2)
    component = "universe" if document_key.startswith("planning/") else "documentation"
    return f"{component}:{document_key}"


def curate() -> dict:
    manifest = json.loads((CORPUS / "corpus_manifest.json").read_text(encoding="utf-8"))
    sources = {
        f"{row['version']}:{row['language']}:{row['document_key']}": row
        for row in manifest["sources"]
    }
    relation_registry = json.loads((CORPUS / "document_relations.json").read_text(encoding="utf-8"))
    relation_status = {}
    for relation in relation_registry.get("relations", []):
        relation_status.setdefault(relation["source_document_id"], set()).add(relation["verification_status"])
        relation_status.setdefault(relation["target_document_id"], set()).add(relation["verification_status"])
    sidecar = json.loads((CORPUS / "figure_evidence_reviewed.json").read_text(encoding="utf-8"))
    reviewed_figures = {
        row["figure_id"]: row for row in sidecar.get("chunks", [])
        if row.get("review_status") == "approved"
    }

    rag_rows: list[dict] = []
    relation_rows: list[dict] = []

    def add(case_id: str, split: str, category: str, query: str, query_language: str,
            required_sources: list[str], points: list[str], *, version: str = "latest",
            language: str = "all", relation_state: str = "none", answerable: bool = True) -> dict:
        component_versions = (
            {"universe": version} if version in {"0.51.0", "0.52.0"}
            else {"documentation": version} if version in {"docs-main", "1.9.0"}
            else {"documentation": "docs-main", "universe": "0.52.0"}
        )
        family = (
            _family_id(required_sources[0]) if len(required_sources) == 1
            else "set:" + "+".join(sorted(_family_id(item) for item in required_sources))
            if required_sources else f"negative:{split}:{case_id}"
        )
        row = {
            "case_id": case_id, "family_id": family, "split": split,
            "category": category, "query": query, "query_language": query_language,
            "version": version, "expected_component_versions": component_versions,
            "language": language, "required_sources": required_sources,
            "required_answer_points": points if answerable else [],
            "expected_image_ids": [], "answerable": answerable,
            "expected_relation_state": relation_state,
        }
        rag_rows.append(row)
        return row

    source_en_zh = {}
    for split, topics in TOPICS.items():
        for topic in topics:
            key = topic["key"]
            en_id, zh_id = f"docs-main:en:{key}", f"docs-main:zh:{key}"
            if en_id not in sources or zh_id not in sources:
                raise ValueError(f"curated bilingual source pair is missing: {key}")
            source_en_zh[key] = (en_id, zh_id)
            state_set = relation_status.get(en_id, set()) | relation_status.get(zh_id, set())
            state = "candidate" if "candidate" in state_set else "verified" if "verified" in state_set else "unknown" if "unknown" in state_set else "none"
            if state not in {"candidate", "verified", "unknown"}:
                raise ValueError(f"bilingual pair has no explicit relation state: {key}")
            add(f"{split}-en-question-zh-evidence-{len([x for x in rag_rows if x['split']==split and x['category']=='en_query_zh_evidence'])+1:02d}", split,
                "en_query_zh_evidence", topic["q_en_zh"], "en", [zh_id], [topic["point_zh"]],
                relation_state=state)
            add(f"{split}-zh-question-en-evidence-{len([x for x in rag_rows if x['split']==split and x['category']=='zh_query_en_evidence'])+1:02d}", split,
                "zh_query_en_evidence", topic["q_zh_en"], "zh", [en_id], [topic["point_en"]],
                relation_state=state)

        # Five relation-state questions per split are grounded in explicit registry rows.
        for index, topic in enumerate(topics[:5], 1):
            en_id, zh_id = source_en_zh[topic["key"]]
            state_set = relation_status.get(en_id, set()) | relation_status.get(zh_id, set())
            state = "candidate" if "candidate" in state_set else "verified" if "verified" in state_set else "unknown"
            relation_rows.append(add(
                f"{split}-translation-registry-{index:02d}", split, "translation_relation_state",
                f"Does the registry confirm that the Chinese page at {topic['key'].split('/')[-1]} is an equivalent translation of the English page?",
                "en", [en_id, zh_id],
                [f"The registry marks the relation as {state}; content equivalence has not been established by that label alone."],
                version="docs-main", language="all", relation_state=state,
            ))

        # Five new single-fact cases in a family-isolated split.
        for index, topic in enumerate(topics[:5], 1):
            evidence_id = source_en_zh[topic["key"]][0]
            add(f"{split}-single-fact-{index:02d}", split, "single_fact", topic["q_fact"], "en",
                [evidence_id], [topic["point_fact"]], version="docs-main", language="en",
                relation_state="candidate")

        for index, (slug, query, keys, points) in enumerate(CROSS_SOURCE[split], 1):
            required = []
            for key in keys:
                language, document_key = key if isinstance(key, tuple) else ("en", key)
                required.append(f"docs-main:{language}:{document_key}")
            for source_id in required:
                if source_id not in sources:
                    raise ValueError(f"cross-source case references absent document: {source_id}")
            add(f"{split}-cross-source-{slug}", split, "cross_source", query, "en", required, points,
                version="docs-main", language="all", relation_state="candidate")

        for index, (key, version, query, point) in enumerate(VERSION_CASES[split], 1):
            source_id = f"{version}:en:{key}"
            if source_id not in sources:
                raise ValueError(f"version case references absent snapshot: {source_id}")
            add(f"{split}-explicit-version-{index:02d}", split, "explicit_version", query, "en",
                [source_id], [point], version=version, language="en", relation_state="none")

        for index, query in enumerate(NO_ANSWER[split], 1):
            add(f"{split}-unanswerable-{index:02d}", split, "unanswerable_scope", query, "en", [], [],
                language="all", relation_state="none", answerable=False)

    image_rows = []
    for figure_id, queries in IMAGE_QUESTIONS.items():
        image = reviewed_figures.get(figure_id)
        if image is None:
            raise ValueError(f"image case is not approved in reviewed sidecar: {figure_id}")
        source_id = f"{image['version']}:{image['language']}:{image['document_key']}"
        if source_id not in sources:
            raise ValueError(f"reviewed image source is absent from manifest: {source_id}")
        for index, query in enumerate(queries, 1):
            family = _family_id(source_id)
            image_rows.append({
                "case_id": f"image-{figure_id}-{index:02d}", "family_id": family,
                "split": "regression", "category": "image_evidence", "query": query,
                "query_language": "en", "version": image["version"],
                "expected_component_versions": {"universe": image["version"]},
                "language": image["language"], "required_sources": [source_id],
                "required_answer_points": [image["content"]], "expected_image_ids": [figure_id],
                "answerable": True, "expected_relation_state": "none",
            })

    rag_rows.sort(key=lambda row: row["case_id"])
    image_rows.sort(key=lambda row: row["case_id"])
    image_bytes = _jsonl_bytes(image_rows)
    rag_bytes = _jsonl_bytes(rag_rows)
    v1_cases_path = ROOT / "evaluation" / "autoware_quality_v1" / "cases.jsonl"
    v1_cases = [json.loads(line) for line in v1_cases_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    v1_holdout_source_families = {
        _family_id(source_id) for case in v1_cases if case.get("split") == "holdout"
        for source_id in case.get("required_sources", [])
    }
    if any(case["split"] == "holdout" and _family_id(source_id) in v1_holdout_source_families
           for case in rag_rows for source_id in case["required_sources"]):
        overlap = sorted({
            _family_id(source_id) for case in rag_rows if case["split"] == "holdout"
            for source_id in case["required_sources"] if _family_id(source_id) in v1_holdout_source_families
        })
        raise ValueError(f"V2 HOLDOUT overlaps V1 HOLDOUT source families: {overlap}")

    (HERE / "rag_cases.jsonl").write_bytes(rag_bytes)
    (HERE / "image_regression_cases.jsonl").write_bytes(image_bytes)
    split_lock = {
        "schema_version": 1,
        "created_by": "curate_cases.py",
        "rag_cases_sha256": hashlib.sha256(rag_bytes).hexdigest(),
        "image_regression_cases_sha256": hashlib.sha256(image_bytes).hexdigest(),
        "corpus_manifest_sha256": _portable_sha256(CORPUS / "corpus_manifest.json"),
        "relation_registry_sha256": _portable_sha256(CORPUS / "document_relations.json"),
        "reviewed_figure_sidecar_sha256": _portable_sha256(CORPUS / "figure_evidence_reviewed.json"),
        "reviewed_figure_lock_sha256": _portable_sha256(CORPUS / "figure_evidence_reviewed.lock.json"),
        "rag_case_count": len(rag_rows), "image_case_count": len(image_rows),
        "rag_split_counts": dict(sorted(Counter(row["split"] for row in rag_rows).items())),
        "rag_category_counts": dict(sorted(Counter(row["category"] for row in rag_rows).items())),
        "image_probe_scope": "two manually reviewed figure IDs; regression only, excluded from promotion split",
    }
    (HERE / "split_lock.json").write_text(json.dumps(split_lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return {"rag": split_lock, "images": image_rows}


if __name__ == "__main__":
    report = curate()
    print(json.dumps(report["rag"], ensure_ascii=False, indent=2))
