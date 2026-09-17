"""Safe and atomic storage for a single live research run."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.research.models import ResearchProfile
from app.research.raw_source_archive import ArchivedRawSource, RawSourceArchive


RUN_ID_PATTERN = re.compile(r"^kr_[0-9]{8}T[0-9]{12}Z_[0-9a-f]{8}$")


class ResearchRunStoreError(ValueError):
    pass


def create_run_id(profile: ResearchProfile, now: datetime | None = None) -> str:
    timestamp = now or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ResearchRunStoreError("run timestamp must include a timezone")
    utc = timestamp.astimezone(timezone.utc)
    stamp = utc.strftime("%Y%m%dT%H%M%S%fZ")
    digest = hashlib.sha256(
        f"{profile.profile_id}|{profile.research_topic}|{stamp}".encode("utf-8")
    ).hexdigest()[:8]
    return f"kr_{stamp}_{digest}"


@dataclass(frozen=True)
class ResearchRunContext:
    run_id: str
    workspace_root: Path
    run_root: Path
    incoming_root: Path
    raw_sources_root: Path
    evidence_path: Path
    outputs_root: Path


class ResearchRunStore:
    def __init__(
        self,
        workspace_root: str | Path,
        run_id: str,
        *,
        runs_root: str | Path = "research_runs",
    ):
        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise ResearchRunStoreError("invalid run_id")
        self.workspace_root = Path(workspace_root).resolve()
        relative_runs = Path(runs_root)
        if relative_runs.is_absolute() or ".." in relative_runs.parts:
            raise ResearchRunStoreError("runs_root must be workspace-relative")
        self.runs_root = (self.workspace_root / relative_runs).resolve()
        if not self.runs_root.is_relative_to(self.workspace_root):
            raise ResearchRunStoreError("runs_root escapes workspace_root")
        self.run_root = self.runs_root / run_id
        self.context = ResearchRunContext(
            run_id=run_id,
            workspace_root=self.workspace_root,
            run_root=self.run_root,
            incoming_root=self.run_root / "incoming",
            raw_sources_root=self.run_root / "raw_sources",
            evidence_path=self.run_root / "evidence" / "evidence.json",
            outputs_root=self.run_root / "outputs",
        )
        self.archive: RawSourceArchive | None = None

    def initialize(self) -> ResearchRunContext:
        if self.run_root.exists():
            raise ResearchRunStoreError(f"research run already exists: {self.context.run_id}")
        self.context.incoming_root.mkdir(parents=True, exist_ok=False)
        self.context.outputs_root.mkdir(parents=True, exist_ok=False)
        self.context.evidence_path.parent.mkdir(parents=True, exist_ok=False)
        self.archive = RawSourceArchive(self.workspace_root, self.run_root)
        return self.context

    def open_existing(self) -> ResearchRunContext:
        required = [
            self.run_root,
            self.context.incoming_root,
            self.context.raw_sources_root,
            self.context.evidence_path.parent,
            self.context.outputs_root,
        ]
        if any(path.is_symlink() or not path.is_dir() for path in required):
            raise ResearchRunStoreError("existing research run has an invalid directory layout")
        self.archive = RawSourceArchive(self.workspace_root, self.run_root)
        return self.context

    def _ensure_initialized(self) -> None:
        if self.archive is None or not self.run_root.is_dir():
            raise ResearchRunStoreError("ResearchRunStore is not initialized")

    def relative_to_workspace(self, path: str | Path) -> str:
        resolved = Path(path).resolve()
        if not resolved.is_relative_to(self.workspace_root):
            raise ResearchRunStoreError("path escapes workspace_root")
        return resolved.relative_to(self.workspace_root).as_posix()

    def stage_bytes(self, data: bytes, *, extension: str) -> str:
        self._ensure_initialized()
        normalized_extension = extension.casefold()
        if normalized_extension not in {".pdf", ".html", ".htm"}:
            raise ResearchRunStoreError("unsupported staged source extension")
        digest = hashlib.sha256(data).hexdigest()
        target = self.context.incoming_root / f"{digest}{normalized_extension}"
        if not target.exists():
            temp_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    dir=self.context.incoming_root,
                    prefix=".incoming-",
                    suffix=".tmp",
                    delete=False,
                ) as temp_file:
                    temp_path = Path(temp_file.name)
                    temp_file.write(data)
                    temp_file.flush()
                    os.fsync(temp_file.fileno())
                os.replace(temp_path, target)
            finally:
                if temp_path is not None and temp_path.exists():
                    temp_path.unlink()
        return self.relative_to_workspace(target)

    def archive_staged(self, staged_local_file: str) -> ArchivedRawSource:
        self._ensure_initialized()
        assert self.archive is not None
        archived = self.archive.archive_path(staged_local_file)
        return ArchivedRawSource(
            local_file=self.relative_to_workspace(self.run_root / archived.local_file),
            raw_file_hash=archived.raw_file_hash,
            media_type=archived.media_type,
            reused=archived.reused,
        )

    def write_json(self, relative_path: str | Path, payload) -> str:
        data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        return self.write_text(relative_path, data)

    def write_text(self, relative_path: str | Path, content: str) -> str:
        self._ensure_initialized()
        requested = Path(relative_path)
        if requested.is_absolute() or ".." in requested.parts:
            raise ResearchRunStoreError("output path must be run-relative")
        target = (self.run_root / requested).resolve()
        if not target.is_relative_to(self.run_root):
            raise ResearchRunStoreError("output path escapes run_root")
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                temp_file.write(content)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_path, target)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()
        return self.relative_to_workspace(target)
