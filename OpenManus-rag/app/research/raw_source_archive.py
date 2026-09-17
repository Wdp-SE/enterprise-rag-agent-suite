"""Safe, content-addressed archive for original offline source files."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from app.research.models import Evidence, StrictModel


class RawSourceArchiveError(ValueError):
    pass


class ArchivedRawSource(StrictModel):
    local_file: str
    raw_file_hash: str
    media_type: str
    reused: bool = False


class RawSourceArchive:
    """Archive original bytes without treating generated Markdown as a source."""

    SUPPORTED_TYPES = {
        ".pdf": "application/pdf",
        ".html": "text/html",
        ".htm": "text/html",
        ".txt": "text/plain",
    }

    def __init__(self, workspace_root: str | Path, package_root: str | Path):
        self.workspace_root = Path(workspace_root).resolve()
        self.package_root = Path(package_root).resolve()
        self.raw_sources_root = self.package_root / "raw_sources"
        self.raw_sources_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source_file:
            for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _source_path(self, relative_path: str) -> Path:
        normalized = relative_path.replace("\\", "/")
        requested = Path(normalized)
        if not normalized or normalized.startswith("/") or requested.is_absolute() or requested.drive:
            raise RawSourceArchiveError("raw source path must be workspace-relative")
        unresolved = self.workspace_root / requested
        current = self.workspace_root
        for part in requested.parts:
            if part == "..":
                raise RawSourceArchiveError("raw source path escapes workspace_root")
            current = current / part
            if current.is_symlink():
                raise RawSourceArchiveError("raw source symlinks are not allowed")
        resolved = unresolved.resolve(strict=False)
        if not resolved.is_relative_to(self.workspace_root):
            raise RawSourceArchiveError("raw source path escapes workspace_root")
        if not resolved.exists() or not resolved.is_file():
            raise RawSourceArchiveError(f"raw source file does not exist: {relative_path}")
        return resolved

    @classmethod
    def _validate_file_type(cls, path: Path) -> tuple[str, str]:
        extension = path.suffix.casefold()
        if extension not in cls.SUPPORTED_TYPES:
            raise RawSourceArchiveError(f"unsupported raw source type: {extension or '<none>'}")
        with path.open("rb") as source_file:
            prefix = source_file.read(4096)
        if extension == ".pdf":
            if not prefix.startswith(b"%PDF-"):
                raise RawSourceArchiveError("raw source has an invalid PDF signature")
        elif extension in {".html", ".htm"}:
            try:
                text = prefix.decode("utf-8-sig").casefold()
            except UnicodeDecodeError as exc:
                raise RawSourceArchiveError("raw HTML source must be UTF-8") from exc
            if "<html" not in text and "<!doctype html" not in text:
                raise RawSourceArchiveError("raw source has an invalid HTML signature")
        else:
            if b"\x00" in prefix:
                raise RawSourceArchiveError("raw TXT source cannot contain NUL bytes")
            try:
                path.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError as exc:
                raise RawSourceArchiveError("raw TXT source must be UTF-8") from exc
        canonical_extension = ".html" if extension == ".htm" else extension
        return canonical_extension, cls.SUPPORTED_TYPES[extension]

    def archive_path(self, relative_path: str) -> ArchivedRawSource:
        source_path = self._source_path(relative_path)
        extension, media_type = self._validate_file_type(source_path)
        raw_file_hash = self._hash_file(source_path)
        target = self.raw_sources_root / f"{raw_file_hash}{extension}"
        if target.exists():
            if target.is_symlink() or not target.is_file():
                raise RawSourceArchiveError("existing raw archive target is not a regular file")
            if self._hash_file(target) != raw_file_hash:
                raise RawSourceArchiveError("existing raw archive target failed hash validation")
            return ArchivedRawSource(
                local_file=f"raw_sources/{target.name}",
                raw_file_hash=raw_file_hash,
                media_type=media_type,
                reused=True,
            )

        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=self.raw_sources_root,
                prefix=".raw-",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
            shutil.copyfile(source_path, temp_path)
            if self._hash_file(temp_path) != raw_file_hash:
                raise RawSourceArchiveError("copied raw source failed hash validation")
            os.replace(temp_path, target)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()
        return ArchivedRawSource(
            local_file=f"raw_sources/{target.name}",
            raw_file_hash=raw_file_hash,
            media_type=media_type,
        )

    def archive(self, evidence: Evidence) -> ArchivedRawSource:
        if evidence.local_file is None:
            raise RawSourceArchiveError("Evidence has no local raw source")
        return self.archive_path(evidence.local_file)
