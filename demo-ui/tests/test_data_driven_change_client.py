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
