"""Build a small, commit-pinned Autoware public corpus from local tag checkouts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from src.public_knowledge import build_index
from scripts.build_reviewed_figure_sidecar import build_reviewed_figure_sidecar
from scripts.figure_evidence import preserve_verified_figure_evidence, scan_inventory


REPOSITORY = "autowarefoundation/autoware_universe"
BASELINE_VERSION = "0.51.0"
CURRENT_VERSION = "0.52.0"
DEFAULT_SELECTION = Path(__file__).resolve().parents[1] / "config" / "autoware_source_selection.json"
DEFAULT_POLICY = Path(__file__).resolve().parents[1] / "config" / "autoware_retrieval_policy.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _canonical_text_bytes(content: bytes) -> bytes:
    """Treat Windows checkout CRLF as equivalent to the pinned Git text blob."""
    return content.replace(b"\r\n", b"\n")


def _normalized_repo_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError("invalid allowlisted source path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("source path escapes allowlisted checkout")
    return path.as_posix()


def load_source_selection(path: Path = DEFAULT_SELECTION) -> list[dict]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        if payload.get("repository") != REPOSITORY:
            raise ValueError("source selection repository is not the approved Autoware repository")
        rows = payload.get("sources")
    else:
        rows = payload
    if not isinstance(rows, list) or not rows:
        raise ValueError("source allowlist must contain at least one source")
    result = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("invalid source allowlist row")
        path_value = _normalized_repo_path(row.get("document_path"))
        document_key = row.get("document_key")
        source_type = row.get("source_type")
        language = row.get("language")
        locale = row.get("locale")
        if (
            not isinstance(document_key, str) or not document_key.strip()
            or source_type != "official_documentation"
            or language not in {"en", "zh"}
            or locale not in {"en-US", "zh-CN"}
            or (language == "en") != (locale == "en-US")
            or not path_value.lower().endswith((".md", ".markdown", ".yaml", ".yml"))
        ):
            raise ValueError("invalid allowlisted source metadata")
        identity = (path_value, document_key, language)
        if identity in seen:
            raise ValueError("duplicate source identity in allowlist")
        seen.add(identity)
        result.append({
            "document_path": path_value,
            "document_key": document_key.strip(),
            "source_type": source_type,
            "language": language,
            "locale": locale,
        })
    return result


def _write_manifest_source(output_root: Path, version: str, commit: str, item: dict, content: bytes) -> dict:
    content = _canonical_text_bytes(content)
    local_path = PurePosixPath("sources") / version / item["language"] / PurePosixPath(item["document_path"])
    destination = output_root.joinpath(*local_path.parts)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return {
        "repository": REPOSITORY,
        "version": version,
        "commit": commit,
        "document_key": item["document_key"],
        "source_type": item["source_type"],
        "language": item["language"],
        "locale": item["locale"],
        "document_path": item["document_path"],
        "local_path": local_path.as_posix(),
        "source_url": (
            f"https://github.com/{REPOSITORY}/blob/{commit}/"
            f"{quote(item['document_path'], safe='/-._')}"
        ),
        "license": "Apache-2.0",
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _manifest_from_sources(sources: list[dict], *, current_version: str, baseline_version: str,
                           commits: dict[str, str]) -> dict:
    return {
        "schema_version": 1,
        "workspace": "Autoware",
        "repository": REPOSITORY,
        "baseline_version": baseline_version,
        "current_version": current_version,
        "available_versions": [baseline_version, current_version],
        "languages": sorted({source["locale"] for source in sources}),
        "commits": commits,
        "sources": sources,
    }


def build_pinned_sources(checkouts: dict[str, dict], selection: list[dict], output_root: Path) -> dict:
    versions = (BASELINE_VERSION, CURRENT_VERSION)
    if set(checkouts) != set(versions):
        raise ValueError("exact baseline and current release checkouts are required")
    commits = {}
    roots = {}
    for version in versions:
        checkout = checkouts[version]
        commit = checkout.get("commit")
        root = Path(checkout.get("root", "")).resolve()
        if not isinstance(commit, str) or not SHA_RE.fullmatch(commit):
            raise ValueError(f"release checkout must provide a full pinned commit: {version}")
        if not root.is_dir():
            raise ValueError(f"release checkout is missing: {version}")
        license_path = root / "LICENSE"
        if not license_path.is_file() or "Apache License" not in license_path.read_text(encoding="utf-8", errors="replace"):
            raise ValueError("repository license is not verified as Apache-2.0")
        license_text = license_path.read_text(encoding="utf-8", errors="replace")
        if "Version 2.0" not in license_text:
            raise ValueError("repository license is not Apache-2.0")
        commits[version] = commit
        roots[version] = root

    sources = []
    seen = set()
    for version in versions:
        for item in selection:
            document_path = _normalized_repo_path(item["document_path"])
            identity = (version, item["language"], item["document_key"])
            if identity in seen:
                raise ValueError("duplicate source identity")
            seen.add(identity)
            source_path = (roots[version] / Path(*PurePosixPath(document_path).parts)).resolve()
            if not source_path.is_relative_to(roots[version]):
                raise ValueError("source path escapes allowlisted checkout")
            if not source_path.is_file():
                raise ValueError(f"allowlisted source is missing: {document_path}")
            content = source_path.read_bytes()
            content.decode("utf-8")
            sources.append(_write_manifest_source(Path(output_root), version, commits[version], item, content))

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "LICENSE").write_bytes(
        _canonical_text_bytes((roots[CURRENT_VERSION] / "LICENSE").read_bytes())
    )
    notice = (
        "This corpus contains selected documentation files from Autoware Universe.\n"
        f"Repository: https://github.com/{REPOSITORY}\n"
        f"Baseline release: {BASELINE_VERSION} ({commits[BASELINE_VERSION]})\n"
        f"Current release: {CURRENT_VERSION} ({commits[CURRENT_VERSION]})\n"
        "Source files are retained unchanged and linked to their pinned upstream commits.\n"
    )
    (output_root / "NOTICE").write_text(notice, encoding="utf-8", newline="\n")
    manifest = _manifest_from_sources(
        sources, current_version=CURRENT_VERSION, baseline_version=BASELINE_VERSION,
        commits=commits,
    )
    manifest_path = output_root / "corpus_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return manifest


def _checkout_info(root: Path, expected_tag: str, *, required_files: set[str] | None = None) -> dict:
    root = Path(root).resolve()
    required = {"LICENSE"}
    required.update(_normalized_repo_path(value) for value in (required_files or set()))
    metadata_path = root / ".autoware_source_ref.json"
    if metadata_path.is_file():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if (
            metadata.get("schema_version") != 1
            or metadata.get("repository") != REPOSITORY
            or metadata.get("tag") != expected_tag
            or metadata.get("version") != expected_tag
        ):
            raise ValueError(f"source snapshot must be pinned to official tag {expected_tag}")
        commit = metadata.get("commit")
        hashes = metadata.get("files_sha256")
        if not isinstance(commit, str) or not SHA_RE.fullmatch(commit) or not isinstance(hashes, dict):
            raise ValueError("source snapshot metadata is invalid")
        normalized_hashes = {}
        for relative, digest in hashes.items():
            normalized = _normalized_repo_path(relative)
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError(f"source snapshot hash metadata is invalid: {relative}")
            normalized_hashes[normalized] = digest
        missing_hashes = required - set(normalized_hashes)
        if missing_hashes:
            raise ValueError(f"source snapshot hash metadata is incomplete: {', '.join(sorted(missing_hashes))}")
        for relative, digest in normalized_hashes.items():
            path = root.joinpath(*PurePosixPath(relative).parts).resolve()
            if not path.is_relative_to(root):
                raise ValueError(f"source snapshot path escapes checkout: {relative}")
            actual_sha256 = hashlib.sha256(_canonical_text_bytes(path.read_bytes())).hexdigest() if path.is_file() else None
            if actual_sha256 != digest:
                raise ValueError(f"source snapshot hash mismatch: {relative}")
        license_text = (root / "LICENSE").read_text(encoding="utf-8", errors="replace")
        if "Apache License" not in license_text or "Version 2.0" not in license_text:
            raise ValueError("repository license is not verified as Apache-2.0")
        return {"root": root, "commit": commit}
    actual_tag = subprocess.run(
        ["git", "-C", str(root), "describe", "--exact-match", "--tags", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if actual_tag != expected_tag:
        raise ValueError(f"checkout must be the exact official tag {expected_tag}")
    commit = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    file_hashes = {}
    for relative in required:
        path = root.joinpath(*PurePosixPath(relative).parts).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError(f"allowlisted source is missing from pinned checkout: {relative}")
        try:
            pinned_content = subprocess.run(
                ["git", "-C", str(root), "show", f"{commit}:{relative}"],
                capture_output=True, check=True,
            ).stdout
        except subprocess.CalledProcessError as exc:
            raise ValueError(f"allowlisted source is missing from pinned commit: {relative}") from exc
        pinned_sha256 = hashlib.sha256(_canonical_text_bytes(pinned_content)).hexdigest()
        actual_sha256 = hashlib.sha256(_canonical_text_bytes(path.read_bytes())).hexdigest()
        if actual_sha256 != pinned_sha256:
            raise ValueError(f"source snapshot sha256 mismatch: {relative}")
        file_hashes[relative] = pinned_sha256
    license_text = (root / "LICENSE").read_text(encoding="utf-8", errors="replace")
    if "Apache License" not in license_text or "Version 2.0" not in license_text:
        raise ValueError("repository license is not verified as Apache-2.0")
    return {"root": root, "commit": commit, "files_sha256": file_hashes}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-checkout", type=Path, required=True)
    parser.add_argument("--current-checkout", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--rebuild", action="store_true", required=True)
    args = parser.parse_args(argv)
    selection = load_source_selection(args.selection)
    required_files = {"LICENSE", *(row["document_path"] for row in selection)}
    checkouts = {
        BASELINE_VERSION: _checkout_info(
            args.baseline_checkout, BASELINE_VERSION, required_files=required_files,
        ),
        CURRENT_VERSION: _checkout_info(
            args.current_checkout, CURRENT_VERSION, required_files=required_files,
        ),
    }
    manifest = build_pinned_sources(checkouts, selection, args.root)
    args.root.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DEFAULT_POLICY, args.root / "retrieval_policy.json")
    shutil.copyfile(DEFAULT_POLICY, args.root / "public_retrieval_runtime.json")
    stats = build_index(args.root)
    inventory_path = args.root / "figure_evidence.json"
    try:
        previous_inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        previous_inventory = None
    inventory = preserve_verified_figure_evidence(scan_inventory(args.root), previous_inventory)
    inventory_path.write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n",
    )
    sidecar_summary = build_reviewed_figure_sidecar(args.root)
    print(json.dumps({"workspace": manifest["workspace"], **stats, **sidecar_summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
