"""Safe offline V3 scenarios A-E over the synthetic versioned corpus."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.document_lifecycle import RetrievalScope, SectionSnapshot, VersionLifecycleService


class SyntheticEmbedder:
    def encode(self, texts):
        rows = []
        for text in texts:
            if "并发" in text:
                rows.append([1.0, 0.0, 0.0, 0.0])
            elif "吞吐" in text:
                rows.append([0.0, 1.0, 0.0, 0.0])
            elif "设计" in text:
                rows.append([0.0, 0.0, 1.0, 0.0])
            else:
                rows.append([0.0, 0.0, 0.0, 1.0])
        return np.asarray(rows, dtype=np.float32)


def load_sections(name: str) -> list[SectionSnapshot]:
    path = PROJECT_ROOT / "data" / "synthetic_versioned_corpus" / name
    return [SectionSnapshot.model_validate(item) for item in json.loads(path.read_text(encoding="utf-8"))]


def main() -> int:
    arguments = argparse.ArgumentParser()
    arguments.add_argument("--output", type=Path, default=PROJECT_ROOT / "reports" / "v3_versioned_e2e")
    args = arguments.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f'output already exists: {output}')
    service = VersionLifecycleService(output / "store")
    embedder = SyntheticEmbedder()
    report_v1 = service.ingest_version(
        document_id="REQ-001", project_id="P-001", document_type="requirements",
        title="需求规格说明书", version_id="REQ-001@1.0", version_label="V1.0",
        source_bytes=b"synthetic-requirements-v1", source_name="requirements_v1.json",
        sections=load_sections("requirements_v1.json"), embedder=embedder,
    )
    scenario_a = service.search([1, 0, 0, 0], top_k=1)
    assert scenario_a[0]["version_id"] == "REQ-001@1.0" and "500" in scenario_a[0]["text"]
    service.ingest_version(
        document_id="DESIGN-001", project_id="P-001", document_type="design",
        title="详细设计说明书", version_id="DESIGN-001@1.0", version_label="V1.0",
        source_bytes=b"synthetic-design-v1", source_name="design_v1.json",
        sections=load_sections("design_v1.json"), embedder=embedder,
    )
    report_v2 = service.ingest_version(
        document_id="REQ-001", project_id="P-001", document_type="requirements",
        title="需求规格说明书", version_id="REQ-001@2.0", version_label="V2.0",
        source_bytes=b"synthetic-requirements-v2", source_name="requirements_v2.json",
        sections=load_sections("requirements_v2.json"), embedder=embedder,
    )
    scenario_b = service.search([1, 0, 0, 0], RetrievalScope(document_ids=["REQ-001"]), top_k=1)
    assert scenario_b[0]["version_id"] == "REQ-001@2.0" and "1000" in scenario_b[0]["text"]
    scenario_c = service.search(
        [1, 0, 0, 0], RetrievalScope(version_ids=["REQ-001@1.0"], active_only=False), top_k=1
    )
    assert scenario_c[0]["version_id"] == "REQ-001@1.0" and "500" in scenario_c[0]["text"]
    scenario_d = service.search(
        [0, 0, 1, 0], RetrievalScope(document_ids=["DESIGN-001"]), top_k=5
    )
    assert scenario_d and {item["document_id"] for item in scenario_d} == {"DESIGN-001"}
    scenario_e = service.diff("REQ-001", "REQ-001@1.0", "REQ-001@2.0")
    assert scenario_e.summary == {"ADDED": 1, "REMOVED": 1, "MODIFIED": 1, "UNCHANGED": 1}
    result = {
        "data_policy": "SYNTHETIC_OFFLINE",
        "online_models_called": False,
        "scenario_a": {"version_id": scenario_a[0]["version_id"], "text": scenario_a[0]["text"]},
        "scenario_b": {"version_id": scenario_b[0]["version_id"], "text": scenario_b[0]["text"]},
        "scenario_c": {"version_id": scenario_c[0]["version_id"], "text": scenario_c[0]["text"]},
        "scenario_d_document_ids": sorted({item["document_id"] for item in scenario_d}),
        "scenario_e": scenario_e.model_dump(mode="json"),
        "v1_build": asdict(report_v1),
        "v2_build": asdict(report_v2),
        "status": "PASS",
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "e2e_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


