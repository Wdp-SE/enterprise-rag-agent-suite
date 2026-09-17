"""CLI entry point for the human-reviewed document workflow prototype."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.document_workflow.configuration import DocumentWorkflowConfig
from app.document_workflow.rag import DemoRAGClient, HTTPRetrieveClient
from app.document_workflow.workflow import DocumentWorkflow


def main() -> None:
    parser = argparse.ArgumentParser(description="Draft a structured DOCX using RAG evidence")
    parser.add_argument("--template", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", help="Resume a checkpointed workflow ID")
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--rag-url", help="Frozen RAG V2 API base URL")
    group.add_argument("--demo-rag", action="store_true", help="Offline simulated RAG corpus")
    args = parser.parse_args()
    if not args.resume and args.template is None:
        parser.error("--template is required for a new workflow")
    config = DocumentWorkflowConfig.from_env()
    rag_url = args.rag_url or config.rag_base_url
    if not args.demo_rag and not rag_url:
        parser.error("--rag-url or RAG_BASE_URL is required")
    client = DemoRAGClient() if args.demo_rag else HTTPRetrieveClient(
        rag_url, timeout=config.rag_timeout_seconds, retry_limit=config.rag_retry_limit)
    workflow = DocumentWorkflow(client, config=config)
    result = (workflow.resume(args.resume, output=args.output, template=args.template)
              if args.resume else workflow.run(args.template, args.output))
    print(f"draft={result['draft_path']}")
    print(f"workflow_id={result['state'].workflow_id}")
    print(f"workflow_status={result['state'].workflow_status}")
    print(f"rag_calls={result['trace']['total_rag_calls']}")
    print("requires_human_review=true")


if __name__ == "__main__":
    main()
