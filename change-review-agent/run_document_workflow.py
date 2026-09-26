"""CLI for the Evidence-driven Document Workflow Agent."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.document_workflow import DocumentWorkflowFacade


def json_object(value: str) -> dict:
    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise argparse.ArgumentTypeError("value must be a JSON object")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Evidence-driven Document Workflow Agent")
    parser.add_argument("--runtime-root", type=Path, default=Path("runtime"))
    parser.add_argument("--rag-url")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Create and run a workflow")
    run.add_argument("--template", type=Path, required=True)
    run.add_argument("--scope", type=json_object, default={"active_only": True})
    run.add_argument("--demo-rag", action="store_true")

    resume = sub.add_parser("resume", help="Resume a checkpointed workflow")
    resume.add_argument("workflow_id")
    resume.add_argument("--demo-rag", action="store_true")

    sub.add_parser("list", help="List local workflows")

    show = sub.add_parser("show", help="Show a workflow")
    show.add_argument("workflow_id")

    review = sub.add_parser("review", help="Approve or reject one section")
    review.add_argument("workflow_id")
    review.add_argument("section_id")
    review.add_argument("action", choices=("APPROVED", "REJECTED"))
    review.add_argument("--reviewer", required=True)
    review.add_argument("--comment", default="")
    review.add_argument("--edits", type=json_object, default={})

    finalize = sub.add_parser("finalize", help="Generate approved.docx")
    finalize.add_argument("workflow_id")
    args = parser.parse_args()

    facade = DocumentWorkflowFacade(args.runtime_root, rag_base_url=args.rag_url)
    if args.command == "run":
        record = facade.create_workflow(args.template, args.scope)
        result = facade.run_workflow(record, use_demo_rag=args.demo_rag)
    elif args.command == "resume":
        result = facade.resume_workflow(args.workflow_id, use_demo_rag=args.demo_rag)
    elif args.command == "list":
        result = facade.list_workflows()
    elif args.command == "show":
        result = facade.get_workflow(args.workflow_id)
    elif args.command == "review":
        result = facade.review_section(
            args.workflow_id, section_id=args.section_id, action=args.action,
            reviewer=args.reviewer, comment=args.comment, edited_fields=args.edits,
        )
    else:
        result = facade.finalize_document(args.workflow_id)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
