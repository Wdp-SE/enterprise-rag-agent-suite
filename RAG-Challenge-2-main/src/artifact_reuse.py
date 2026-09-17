"""Strict, auditable reuse decisions for immutable RAG artifacts."""

from __future__ import annotations

from typing import Dict, List, Literal

from pydantic import BaseModel, ConfigDict


class ArtifactBuildConfig(BaseModel):
    """Inputs whose equality is required before an artifact may be reused."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_sha256: str
    embedding_provider: str
    embedding_model: str
    embedding_normalized: bool
    chunk_size: int
    chunk_overlap: int
    metadata_schema_version: str


class ArtifactReuseDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reusable: bool
    reason: Literal["ALL_REUSE_CONDITIONS_MATCH", "CONFIG_MISMATCH"]
    mismatches: List[str]
    compared: Dict[str, Dict[str, object]]


def evaluate_artifact_reuse(
    existing: ArtifactBuildConfig,
    target: ArtifactBuildConfig,
) -> ArtifactReuseDecision:
    """Compare every content-affecting build input, never just a filename."""

    old = existing.model_dump()
    new = target.model_dump()
    mismatches = [field for field in old if old[field] != new[field]]
    return ArtifactReuseDecision(
        reusable=not mismatches,
        reason=(
            "ALL_REUSE_CONDITIONS_MATCH" if not mismatches else "CONFIG_MISMATCH"
        ),
        mismatches=mismatches,
        compared={field: {"existing": old[field], "target": new[field]} for field in old},
    )
