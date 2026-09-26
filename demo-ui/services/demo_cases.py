"""Data-driven synthetic cases for the public value prototype."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from config import WORKSPACE_ROOT


REGISTRY_PATH = WORKSPACE_ROOT / "project_delivery/public_value_prototype/demo_cases/cases.json"


@dataclass(frozen=True)
class DemoCase:
    case_id: str
    title: str
    description: str
    organization_id: str
    organization_name: str
    project_id: str
    data_root: Path
    inventory_path: Path
    baseline_documents: tuple[str, ...]
    changed_external_identifier: str
    requirement_old_version_id: str
    requirement_new_version_id: str
    patch_target_external_identifier: str
    patch_document_filename: str
    patch_target_document_id: str
    patch_base_version_id: str
    patch_target_section_id: str
    patch_proposed_content: str
    patch_reason: str
    candidate_version_id: str
    candidate_version_label: str
    candidate_title: str
    config_path: Path

    @classmethod
    def from_file(cls, path: Path) -> "DemoCase":
        payload = json.loads(path.read_text(encoding="utf-8"))
        data_root = (WORKSPACE_ROOT / payload["data_root"]).resolve()
        return cls(
            **{key: payload[key] for key in (
                "case_id", "title", "description", "organization_id",
                "organization_name", "project_id", "changed_external_identifier",
                "requirement_old_version_id", "requirement_new_version_id",
                "patch_target_external_identifier", "patch_document_filename",
                "patch_target_document_id", "patch_base_version_id",
                "patch_target_section_id", "patch_proposed_content", "patch_reason",
                "candidate_version_id", "candidate_version_label", "candidate_title",
            )},
            data_root=data_root,
            inventory_path=data_root / "engineering_inventory.json",
            baseline_documents=tuple(payload["baseline_documents"]),
            config_path=path,
        )


def load_demo_cases(registry_path: Path = REGISTRY_PATH) -> dict[str, DemoCase]:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    result: dict[str, DemoCase] = {}
    for relative in registry["cases"]:
        path = (registry_path.parent / relative).resolve()
        case = DemoCase.from_file(path)
        if case.case_id in result:
            raise ValueError(f"duplicate demo case: {case.case_id}")
        result[case.case_id] = case
    return result
