from __future__ import annotations

from pathlib import Path


def test_change_impact_adapter_contains_no_case_a_business_literals() -> None:
    source = (Path(__file__).parents[1] / "services/change_impact_client.py").read_text(encoding="utf-8")
    for forbidden in (
        "REQ-023",
        "DES-014",
        "500",
        "1000",
        "PAYMENT",
        "system_design_v1.docx",
        "design-v2",
    ):
        assert forbidden not in source

def test_public_cases_modify_existing_primary_requirements_and_keep_real_additions() -> None:
    import json

    from services.demo_cases import load_demo_cases

    for case in load_demo_cases().values():
        inventory = json.loads(case.inventory_path.read_text(encoding="utf-8"))
        old = {
            item["external_identifier"]: item
            for item in inventory["items"]
            if item["version_id"] == case.requirement_old_version_id
        }
        new = {
            item["external_identifier"]: item
            for item in inventory["items"]
            if item["version_id"] == case.requirement_new_version_id
        }
        primary_id = case.changed_external_identifier
        assert primary_id in old and primary_id in new
        assert old[primary_id]["content_hash"] != new[primary_id]["content_hash"]
        assert set(new) - set(old)

        by_id = {item["item_id"]: item for item in inventory["items"]}
        target_types = {
            by_id[link["target_item_id"]]["item_type"]
            for link in inventory["trace_links"]
            if link["source_item_id"] == new[primary_id]["item_id"]
        }
        assert {"DESIGN", "TEST_CASE"} <= target_types
