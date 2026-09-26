"""Offline-only runtime smoke; emits counts/status and never document text."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.rd_v2_runtime import RDV2Settings, create_runtime  # noqa: E402


def main() -> None:
    settings = RDV2Settings.from_env(PROJECT_ROOT)
    if settings.allow_external_generation:
        raise RuntimeError("OFFLINE_SMOKE_REFUSES_EXTERNAL_GENERATION")
    runtime = create_runtime(settings)
    try:
        result = runtime.query("离线运行时自检")
        if result["status"] != "GENERATION_DISABLED_BY_DATA_POLICY":
            raise RuntimeError("OFFLINE_DATA_POLICY_GATE_FAILED")
        if not result["trace"] or any("text" in item for item in result["trace"]):
            raise RuntimeError("SAFE_TRACE_VALIDATION_FAILED")
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "artifact_status": runtime.bundle.manifest["status"],
                    "retrieval_policy": settings.retrieval_policy,
                    "dense_representation": settings.dense_representation,
                    "retrieved_trace_count": len(result["trace"]),
                    "generation_status": result["status"],
                    "online_models_called": False,
                    "body_text_logged": False,
                },
                ensure_ascii=False,
            )
        )
    finally:
        runtime.close()


if __name__ == "__main__":
    main()

