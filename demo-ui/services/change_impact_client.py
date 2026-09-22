"""UI adapter for the synthetic V4 engineering change review workflow."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from docx import Document

from config import AGENT_ROOT, WORKSPACE_ROOT, DemoConfig
from services.rag_client import ServiceError


DEMO_ROOT = WORKSPACE_ROOT / "project_delivery" / "v4_change_impact_review" / "demo_data"
INVENTORY_PATH = DEMO_ROOT / "engineering_inventory.json"


class ChangeImpactClient:
    def __init__(self, config: DemoConfig):
        self.config = config
        if str(AGENT_ROOT) not in sys.path:
            sys.path.insert(0, str(AGENT_ROOT))
        from app.change_impact_review import ChangeImpactReviewFacade
        from app.document_workflow.rag import HTTPRetrieveClient

        self.rag = HTTPRetrieveClient(
            config.rag_base_url,
            timeout=config.request_timeout_seconds,
            retry_limit=0,
        )
        self.facade = ChangeImpactReviewFacade(
            config.runtime_root / "v4",
            active_version_for_document=self._active_version,
            version_client=self.rag,
        )

    def status(self) -> dict[str, Any]:
        return {
            "ready": INVENTORY_PATH.is_file(),
            "profile": "demo_company_a",
            "project": "PAYMENT",
            "classification": "FULLY_SYNTHETIC",
        }

    def _inventory(self) -> dict:
        try:
            payload = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ServiceError("V4 合成资料清单不可用。", str(exc), "V4_FIXTURE_MISSING") from exc
        if payload.get("schema_version") != "v4-engineering-inventory-v1":
            raise ServiceError("V4 合成资料清单版本不匹配。", "schema mismatch", "V4_FIXTURE_INVALID")
        return payload

    def _version_documents(self) -> list[dict]:
        return self.rag.candidate_version_documents()["documents"]

    def _active_version(self, document_id: str) -> str | None:
        for document in self._version_documents():
            if document.get("document_id") == document_id:
                active = document.get("active_version") or {}
                return active.get("version_id")
        return None

    def _ensure_seeded(self, inventory: dict) -> None:
        try:
            catalog = self._version_documents()
        except Exception as exc:
            raise ServiceError(
                "V4 版本服务未启用，请按启动文档设置 RD_V4_VERSION_STORE_ROOT 后重启 RAG。",
                str(exc),
                "V4_VERSION_SERVICE_UNAVAILABLE",
            ) from exc
        known_versions = {
            version["version_id"]
            for document in catalog
            for version in document.get("versions", [])
        }
        profile = inventory["profile"]
        for record in inventory["documents"]:
            version_id = record["version_id"]
            if version_id in known_versions:
                continue
            source = DEMO_ROOT / record["filename"]
            built = self.rag.build_candidate_version(
                document_id=record["document_id"],
                project_id="PAYMENT",
                document_type=record["document_type"],
                title=record["title"],
                version_id=version_id,
                version_label=record["version_label"],
                source_bytes=source.read_bytes(),
                source_name=record["filename"],
                profile=profile,
                expected_contents=[],
            )
            if built.get("status") == "FAILED":
                raise ServiceError(
                    "合成文档版本构建失败，旧有效版本保持不变。",
                    str(built.get("failure_reason")),
                    "V4_SEED_BUILD_FAILED",
                )
            if built.get("status") == "VALIDATED":
                activated = self.rag.activate_candidate_version(str(built["candidate_id"]))
                if activated.get("status") != "ACTIVE":
                    raise ServiceError(
                        "合成文档版本激活失败，旧有效版本保持不变。",
                        str(activated.get("failure_reason")),
                        "V4_SEED_ACTIVATION_FAILED",
                    )
            known_versions.add(version_id)

    @staticmethod
    def _scope_fingerprint(scope: dict) -> str:
        canonical = json.dumps(scope, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def prepare_demo(self) -> dict[str, Any]:
        from app.change_impact_review import PatchCandidate, PatchOperation
        from app.document_workflow.configuration import DocumentWorkflowConfig
        from app.document_workflow.evidence_models import Evidence
        from app.document_workflow.evidence_selection import (
            EvidenceSelectionPolicy,
            EvidenceSelector,
        )
        from app.document_workflow.scope import WorkflowScope

        inventory = self._inventory()
        self._ensure_seeded(inventory)
        items = inventory["items"]
        old_items = [item for item in items if item["version_id"] == "requirements-v1"]
        new_items = [item for item in items if item["version_id"] == "requirements-v2"]
        changes = self.rag.diff_engineering_items(old_items, new_items)["changes"]
        changed = next(
            item for item in new_items if item["external_identifier"] == inventory["changed_external_identifier"]
        )
        active_items = [item for item in items if item["version_id"] != "requirements-v1"]
        scope = {"project_ids": ["PAYMENT"], "active_only": True}
        dense = self.rag.search_candidate_versions(changed["content"], scope, top_k=20)["results"]
        by_location = {
            (item["document_id"], item["version_id"], item["section_id"]): item
            for item in active_items
        }
        dense_ids: list[str] = []
        evidence_by_item: dict[str, list[str]] = {}
        evidence_objects: dict[str, Evidence] = {}
        for row in dense:
            item = by_location.get((row["document_id"], row["version_id"], row["section_id"]))
            if (
                item is None
                or item["item_id"] == changed["item_id"]
                or item["document_id"] == changed["document_id"]
            ):
                continue
            if item["item_id"] not in dense_ids:
                dense_ids.append(item["item_id"])
            evidence = Evidence(
                title=row.get("document_title") or row["document_id"],
                content=row["text"],
                organization="星海软件科技有限公司（虚构）",
                source_type="RAG",
                document_id=row["document_id"],
                project_id=row["project_id"],
                document_type=row["document_type"],
                version_id=row["version_id"],
                version_label=row["version_label"],
                version_status=row["version_status"],
                chunk_id=row["chunk_id"],
                query=changed["content"],
                section=row["section_id"],
                section_path=row["section_path"],
                page_number=row["page_number"],
                retrieved_at=datetime.now(timezone.utc),
            )
            assert evidence.evidence_id
            evidence_objects[evidence.evidence_id] = evidence
            evidence_by_item.setdefault(item["item_id"], []).append(evidence.evidence_id)
        impacts = self.rag.discover_engineering_impacts(
            changed["item_id"],
            active_items,
            inventory["trace_links"],
            dense_item_ids=dense_ids,
            evidence_by_item=evidence_by_item,
        )["impacts"]
        requirement_evidence = Evidence(
            title="需求规格说明书",
            content=changed["content"],
            organization="星海软件科技有限公司（虚构）",
            source_type="RAG",
            document_id=changed["document_id"],
            project_id=changed["project_id"],
            document_type=changed["item_type"],
            version_id=changed["version_id"],
            version_label="V2.0",
            version_status="ACTIVE",
            chunk_id=f"{changed['version_id']}:{changed['section_id']}:{changed['item_id']}",
            query=changed["external_identifier"],
            section=changed["section_id"],
            section_path=changed["metadata"]["section_path"],
            page_number=1,
            retrieved_at=datetime.now(timezone.utc),
        )
        assert requirement_evidence.evidence_id and requirement_evidence.content_hash
        evidence_objects[requirement_evidence.evidence_id] = requirement_evidence
        selection = EvidenceSelector(
            EvidenceSelectionPolicy(
                DocumentWorkflowConfig.from_env().max_evidence_count
            )
        ).select(
            list(evidence_objects.values()),
            WorkflowScope.from_dict(scope),
            required_evidence_ids=(requirement_evidence.evidence_id,),
        )
        selected_evidence_ids = {item.evidence_id for item in selection.selected}
        if requirement_evidence.evidence_id not in selected_evidence_ids:
            raise RuntimeError("critical requirement Evidence was not selected")
        design_source = DEMO_ROOT / "system_design_v1.docx"
        design_document = Document(design_source)
        paragraph_index = next(
            index for index, paragraph in enumerate(design_document.paragraphs)
            if "DES-014" in paragraph.text
        )
        original = design_document.paragraphs[paragraph_index].text
        proposed = (
            "DES-014 面向 REQ-023：批处理服务按最大并发 1000 配置连接池，"
            "支持 200 MB/s 吞吐目标，并通过异步任务状态返回结果。"
        )
        patch = PatchCandidate.create(
            target_document_id="system_design",
            base_version_id="design-v1",
            target_section_id="DESIGN",
            target_anchor=f"paragraph:{paragraph_index}",
            operation=PatchOperation.REPLACE_PARAGRAPH,
            original_content=original,
            proposed_content=proposed,
            reason="REQ-023 的并发、吞吐量和接口模式发生变化",
            evidence_ids=[requirement_evidence.evidence_id],
            evidence_content_hashes={requirement_evidence.evidence_id: requirement_evidence.content_hash},
            scope_fingerprint=self._scope_fingerprint(scope),
        )
        state = self.facade.create_task(
            organization_id="demo_company_a",
            project_id="PAYMENT",
            scope=scope,
            base_document_id="system_design",
            base_version_id="design-v1",
            source=design_source,
            impacts=impacts,
            patches=[patch],
            evidence=list(evidence_objects.values()),
            rag_calls=3,
        )
        return {
            "state": state.model_dump(mode="json"),
            "changes": changes,
            "items": {item["item_id"]: item for item in active_items},
            "evidence": {
                evidence_id: item.model_dump(mode="json")
                for evidence_id, item in evidence_objects.items()
            },
            "evidence_selection": {
                **selection.stats.model_dump(),
                "max_evidence_count": DocumentWorkflowConfig.from_env().max_evidence_count,
                "selected_evidence_ids": sorted(
                    item for item in selected_evidence_ids if item is not None
                ),
            },
        }

    def review_patch(
        self,
        task_id: str,
        patch_id: str,
        *,
        action: str,
        reviewer: str,
        comment: str = "",
        edited_content: str | None = None,
    ) -> dict:
        from app.change_impact_review import PatchReviewAction

        state = self.facade.review_patch(
            task_id,
            patch_id,
            action=PatchReviewAction(action),
            reviewer=reviewer,
            comment=comment,
            edited_content=edited_content,
        )
        return state.model_dump(mode="json")

    def apply(self, task_id: str) -> dict:
        current_version_id = self._active_version("system_design") or ""
        state, results = self.facade.apply_reviewed_patches(
            task_id, current_version_id=current_version_id
        )
        return {
            "state": state.model_dump(mode="json"),
            "apply_results": [item.model_dump(mode="json") for item in results],
        }

    def publish(self, task_id: str) -> dict:
        inventory = self._inventory()
        document_type = "系统设计说明书"
        for row in self._version_documents():
            if row.get("document_id") == "system_design":
                document_type = str(row.get("document_type") or document_type)
                break
        state = self.facade.finalize_candidate_version(
            task_id,
            version_id="design-v2",
            version_label="V2.0",
            document_type=document_type,
            title="系统设计说明书",
            profile=inventory["profile"],
        )
        return state.model_dump(mode="json")
