"""Curated and source-verified retrieval questions for the pinned public corpus."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAG = ROOT.parents[1] / "versioned-rag-service"
sys.path.insert(0, str(RAG))
from src.public_knowledge import _parts  # noqa: E402


# Category, user query, version, locale, document key, exact source substring.
# Every marker is checked against the downloaded, hash-pinned official source.
QUESTIONS = [
    ("zh", "DolphinScheduler 参数优先级从高到低是什么？", "3.4.3", "zh", "guide/parameter/priority", "上游任务传递的参数 > 启动参数"),
    ("zh", "全局参数在哪里配置？", "3.4.3", "zh", "guide/parameter/global", "工作流定义"),
    ("zh", "本地参数的作用范围是什么？", "3.4.3", "zh", "guide/parameter/local", "本地参数"),
    ("zh", "内置参数 system.biz.date 表示什么？", "3.4.3", "zh", "guide/parameter/built-in", "system.biz.date"),
    ("zh", "启动参数在哪里设置？", "3.4.3", "zh", "guide/parameter/startup-parameter", "启动参数"),
    ("zh", "依赖节点可以检查什么？", "3.4.3", "zh", "guide/task/dependent", "依赖节点"),
    ("zh", "Switch 任务如何设置分支条件？", "3.4.3", "zh", "guide/task/switch", "Switch"),
    ("zh", "如何创建工作流定义？", "3.4.3", "zh", "guide/project/workflow-definition", "工作流定义"),
    ("zh", "工作流实例的日志在哪里查看？", "3.4.3", "zh", "guide/project/workflow-instance", "日志"),
    ("zh", "升级 DolphinScheduler 前要备份什么？", "3.4.3", "zh", "guide/upgrade/upgrade", "备份"),
    ("en", "What is the API server health-check endpoint?", "3.4.3", "en", "guide/api/healthcheck", "/dolphinscheduler/actuator/health"),
    ("en", "What is the default dependency check interval?", "3.4.3", "en", "guide/task/dependent", "default is 10s"),
    ("en", "Which parameter source has the highest priority?", "3.4.3", "en", "guide/parameter/priority", "Parameter Context > Startup Parameter"),
    ("en", "What is system.workflow.instance.id?", "3.4.3", "en", "guide/parameter/built-in", "system.workflow.instance.id"),
    ("en", "Where are global parameters configured?", "3.4.3", "en", "guide/parameter/global", "workflow definition page"),
    ("en", "How do I create an Open API token?", "3.4.3", "en", "guide/api/open-api", "Create a Token"),
    ("en", "What does Serial Discard do?", "3.4.3", "en", "guide/project/workflow-definition", "Serial Discard"),
    ("mixed", "worker group 默认是什么？", "3.4.3", "en", "guide/project/workflow-definition", "default is `Default`"),
    ("mixed", "workflow timeout alarm 在哪里配置？", "3.4.3", "en", "guide/project/workflow-definition", "Timeout alarm"),
    ("mixed", "Parameter Context 和 Startup Parameter 哪个优先？", "3.4.3", "en", "guide/parameter/priority", "Parameter Context > Startup Parameter"),
    ("mixed", "Dependent task 的 Check interval 默认多久？", "3.4.3", "en", "guide/task/dependent", "default is 10s"),
    ("mixed", "Open API 的 token 要怎样创建？", "3.4.3", "en", "guide/api/open-api", "Create a Token"),
    ("mixed", "3.4.3 的 missed_fire_policy 对旧 schedule 默认什么？", "3.4.3", "en", "guide/upgrade/incompatible", "FIRE_ALL_MISSED"),
    ("exact", "system.task.definition.code", "3.4.3", "en", "guide/parameter/built-in", "system.task.definition.code"),
    ("exact", "system.biz.curdate", "3.4.3", "en", "guide/parameter/built-in", "system.biz.curdate"),
    ("exact", "/dolphinscheduler/actuator/health", "3.4.3", "en", "guide/api/healthcheck", "/dolphinscheduler/actuator/health"),
    ("exact", "missed_fire_policy", "3.4.3", "en", "guide/upgrade/incompatible", "missed_fire_policy"),
    ("exact", "DSIP-107", "3.4.3", "en", "release-notes", "DSIP-107"),
    ("exact", "DSIP-95", "3.4.2", "en", "release-notes", "DSIP-95"),
    ("version", "3.4.3 新增的调度 misfire policy 对应哪个 DSIP？", "3.4.3", "en", "release-notes", "DSIP-107"),
    ("version", "3.4.3 的 schedules 表新增了什么字段？", "3.4.3", "en", "guide/upgrade/incompatible", "missed_fire_policy"),
    ("version", "3.4.2 的 HTTP TRACE 配置改动对应哪个 DSIP？", "3.4.2", "en", "release-notes", "DSIP-37"),
    ("version", "3.4.2 API complement data 的依赖能力是什么改动？", "3.4.2", "en", "release-notes", "DSIP-95"),
    ("version", "3.4.3 参数优先级文档有哪些更新？", "3.4.3", "en", "release-notes", "parameter priority"),
    ("cross_document", "依赖任务如何把输出参数传给下游，以及参数冲突如何决定优先级？", "3.4.3", "en", "guide/task/dependent", "parameter passing option"),
    ("cross_document", "What is the worker group setting when running a workflow and where is the execution recorded?", "3.4.3", "en", "guide/project/workflow-definition", "Worker group"),
    ("cross_document", "API server health check 与 Open API 调用入口分别是什么？", "3.4.3", "en", "guide/api/healthcheck", "localhost:12345"),
    ("cross_document", "3.4.3 misfire policy 的 release 项与数据库升级字段如何对应？", "3.4.3", "en", "guide/upgrade/incompatible", "missed_fire_policy"),
    ("hard", "全局参数和启动参数同名谁覆盖谁？", "3.4.3", "zh", "guide/parameter/priority", "启动参数 > 本地参数 > 全局参数"),
    ("hard", "task priority 和 process priority 分别影响哪些队列？", "3.4.3", "en", "guide/project/workflow-definition", "Task Priority"),
    ("hard", "workflow definition 和 workflow instance 有何区别？", "3.4.3", "en", "guide/project/workflow-instance", "Workflow Instance"),
    ("hard", "Master-Server 与 Worker-Server 的健康检查端口分别是什么？", "3.4.3", "en", "guide/api/healthcheck", "localhost:5679"),
    ("hard", "上游同名参数中谁最后生效？", "3.4.3", "zh", "guide/parameter/priority", "完成时间最晚"),
    ("no_answer", "DolphinScheduler 3.4.3 的商业许可每年多少钱？", "3.4.3", "", "", ""),
    ("no_answer", "DolphinScheduler 核心开发者的私人手机号是什么？", "3.4.3", "", "", ""),
    ("no_answer", "2029 年 DolphinScheduler 4.9.0 的发布日是哪一天？", "3.4.3", "", "", ""),
]


def write_queries() -> None:
    corpus = RAG / "public_corpus"
    manifest = json.loads((corpus / "corpus_manifest.json").read_text(encoding="utf-8"))
    sources = {(row["version"], row["language"], row["document_key"]): row for row in manifest["sources"]}
    queries = []
    truth = []
    for number, (category, question, version, language, key, marker) in enumerate(QUESTIONS, start=1):
        query_id = f"ds-{number:03d}"
        queries.append({"id": query_id, "query": question, "category": category, "version_scope": version})
        if not key:
            truth.append({"id": query_id, "relevant": [], "answerable_in_corpus": False})
            continue
        source = sources[(version, language, key)]
        sections = _parts((corpus / source["local_path"]).read_text(encoding="utf-8"))
        matches = [(heading, content) for heading, content in sections if marker.casefold() in content.casefold()]
        if not matches:
            raise ValueError(f"unverified marker for {query_id}: {key} {marker}")
        heading, _ = matches[0]
        truth.append({
            "id": query_id, "answerable_in_corpus": True,
            "relevant": [{
                "document_key": key, "heading": heading, "source_url": source["source_url"],
                "version": version, "locale": source["locale"],
                "source_type": source["source_type"], "evidence_marker": marker,
            }],
        })
    cross_evidence = {
        "ds-035": ("guide/parameter/priority", "Parameter Context > Startup Parameter"),
        "ds-036": ("guide/project/workflow-instance", "Project Management -> Workflow -> Workflow Instance"),
        "ds-037": ("guide/api/open-api", "Create token"),
        "ds-038": ("release-notes", "DSIP-107"),
    }
    for row in truth:
        if row["id"] not in cross_evidence:
            continue
        key, marker = cross_evidence[row["id"]]
        source = sources[("3.4.3", "en", key)]
        sections = _parts((corpus / source["local_path"]).read_text(encoding="utf-8"))
        matches = [(heading, content) for heading, content in sections if marker.casefold() in content.casefold()]
        if not matches:
            raise ValueError(f"unverified cross-document marker: {row['id']} {key}")
        row["relevant"].append({
            "document_key": key, "heading": matches[0][0], "source_url": source["source_url"],
            "version": "3.4.3", "locale": source["locale"],
            "source_type": source["source_type"], "evidence_marker": marker,
        })
    for name, rows in (("queries.jsonl", queries), ("ground_truth.jsonl", truth)):
        (ROOT / name).write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
        )
    print(f"verified_queries={len(queries)} answerable={sum(x['answerable_in_corpus'] for x in truth)}")


if __name__ == "__main__":
    write_queries()
