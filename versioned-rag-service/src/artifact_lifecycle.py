"""Small, deterministic artifact build lifecycle with resumable checkpoints.

The lifecycle file deliberately contains metadata only.  Callers must never put
document text, questions, credentials, or exception messages into it.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Mapping, Optional


class ArtifactState(str, Enum):
    PENDING = "PENDING"
    BUILDING = "BUILDING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class ArtifactLifecycleError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _atomic_json_write(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


@dataclass
class ArtifactBuildLifecycle:
    """Manage PENDING/BUILDING/FAILED/COMPLETE without accepting partial data."""

    state_path: Path
    artifact_root: Path

    def read(self) -> dict:
        if not self.state_path.is_file():
            raise ArtifactLifecycleError("ARTIFACT_BUILD_STATE_MISSING")
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def initialize(self, *, input_fingerprint: str, total_batches: int) -> dict:
        if self.state_path.exists():
            raise ArtifactLifecycleError("ARTIFACT_BUILD_STATE_ALREADY_EXISTS")
        if total_batches < 0:
            raise ValueError("total_batches must be non-negative")
        timestamp = _now()
        state = {
            "schema_version": 1,
            "status": ArtifactState.PENDING.value,
            "input_fingerprint": input_fingerprint,
            "completed_batches": 0,
            "total_batches": total_batches,
            "checkpoint_files": {},
            "attempt": 0,
            "created_at": timestamp,
            "updated_at": timestamp,
            "body_text_logged": False,
        }
        _atomic_json_write(self.state_path, state)
        return state

    def start(self, *, input_fingerprint: str, resume: bool = False) -> dict:
        state = self.read()
        if state.get("input_fingerprint") != input_fingerprint:
            raise ArtifactLifecycleError("CHECKPOINT_INPUT_MISMATCH")
        status = ArtifactState(state["status"])
        if status is ArtifactState.COMPLETE:
            raise ArtifactLifecycleError("ARTIFACT_ALREADY_COMPLETE")
        if status in {ArtifactState.BUILDING, ArtifactState.FAILED} and not resume:
            raise ArtifactLifecycleError("RESUME_REQUIRED")
        if resume:
            self.validate_partial(state)
        state["status"] = ArtifactState.BUILDING.value
        state["attempt"] = int(state.get("attempt", 0)) + 1
        state["updated_at"] = _now()
        state.pop("failure_code", None)
        _atomic_json_write(self.state_path, state)
        return state

    def checkpoint(
        self,
        *,
        completed_batches: int,
        files: Mapping[str, Path],
    ) -> dict:
        state = self.read()
        if state.get("status") != ArtifactState.BUILDING.value:
            raise ArtifactLifecycleError("CHECKPOINT_REQUIRES_BUILDING_STATE")
        total = int(state["total_batches"])
        previous = int(state["completed_batches"])
        if not previous <= completed_batches <= total:
            raise ArtifactLifecycleError("CHECKPOINT_PROGRESS_INVALID")
        checkpoints = {}
        for name, raw_path in sorted(files.items()):
            path = Path(raw_path)
            if not path.is_file():
                raise ArtifactLifecycleError("CHECKPOINT_FILE_MISSING")
            try:
                relative = path.resolve().relative_to(self.artifact_root.resolve())
            except ValueError as exc:
                raise ArtifactLifecycleError("CHECKPOINT_OUTSIDE_ARTIFACT_ROOT") from exc
            checkpoints[name] = {
                "path": relative.as_posix(),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        state["completed_batches"] = completed_batches
        state["checkpoint_files"] = checkpoints
        state["updated_at"] = _now()
        _atomic_json_write(self.state_path, state)
        return state

    def validate_partial(self, state: Optional[Mapping[str, object]] = None) -> None:
        current = dict(state or self.read())
        completed = int(current.get("completed_batches", -1))
        total = int(current.get("total_batches", -1))
        if completed < 0 or total < 0 or completed > total:
            raise ArtifactLifecycleError("CHECKPOINT_PROGRESS_INVALID")
        for metadata in dict(current.get("checkpoint_files", {})).values():
            path = self.artifact_root / str(metadata["path"])
            if not path.is_file():
                raise ArtifactLifecycleError("CHECKPOINT_FILE_MISSING")
            if path.stat().st_size != int(metadata["bytes"]):
                raise ArtifactLifecycleError("CHECKPOINT_SIZE_MISMATCH")
            if sha256_file(path) != metadata["sha256"]:
                raise ArtifactLifecycleError("CHECKPOINT_HASH_MISMATCH")

    def fail(self, failure_code: str) -> dict:
        state = self.read()
        if state.get("status") == ArtifactState.COMPLETE.value:
            raise ArtifactLifecycleError("COMPLETE_ARTIFACT_CANNOT_FAIL")
        state["status"] = ArtifactState.FAILED.value
        state["failure_code"] = str(failure_code)
        state["updated_at"] = _now()
        _atomic_json_write(self.state_path, state)
        return state

    def complete(self, *, validator: Callable[[], None]) -> dict:
        state = self.read()
        if state.get("status") != ArtifactState.BUILDING.value:
            raise ArtifactLifecycleError("COMPLETE_REQUIRES_BUILDING_STATE")
        if int(state["completed_batches"]) != int(state["total_batches"]):
            raise ArtifactLifecycleError("PARTIAL_ARTIFACT_CANNOT_COMPLETE")
        self.validate_partial(state)
        validator()
        state["status"] = ArtifactState.COMPLETE.value
        state["completed_at"] = _now()
        state["updated_at"] = state["completed_at"]
        _atomic_json_write(self.state_path, state)
        return state
