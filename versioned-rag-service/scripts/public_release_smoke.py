"""Read-only verification of the deployed UI, RAG build and public search path."""

from __future__ import annotations

import argparse
import json
import math
import re
import time
from urllib.parse import urlsplit

import httpx


_REVISION = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
_NO_ANSWER_QUERY = "Can this public corpus show our company's Jira access-approval audit trail?"
_SEARCH_PROBES = (
    {
        "name": "chinese_current_snapshot_query",
        "query": "如何启动 Autoware 并通过命令行参数启用或禁用模块？",
        "version": "latest", "language": "zh",
    },
    {
        "name": "chinese_historical_snapshot_query",
        "query": "Autoware ROS 节点如何声明和读取参数？",
        "version": "community-zh-2026-01", "language": "zh",
    },
)


class ReleaseSmokeError(RuntimeError):
    pass


def _validate_base_url(value: str, label: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise ReleaseSmokeError(f"{label} URL must be an HTTP(S) URL without embedded credentials")
    if parsed.query or parsed.fragment:
        raise ReleaseSmokeError(f"{label} URL must not contain a query string or fragment")
    return value.rstrip("/")


def _request(client: httpx.Client, method: str, url: str, *, json_body: dict | None = None) -> tuple[dict | None, float, int]:
    started = time.perf_counter()
    try:
        response = client.request(method, url, json=json_body)
    except httpx.HTTPError as exc:
        raise ReleaseSmokeError(f"remote request failed ({type(exc).__name__})") from None
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    if response.status_code < 200 or response.status_code >= 300:
        raise ReleaseSmokeError(f"remote endpoint returned HTTP {response.status_code}")
    if not response.content:
        return None, elapsed_ms, response.status_code
    try:
        payload = response.json()
    except ValueError:
        return None, elapsed_ms, response.status_code
    return payload if isinstance(payload, dict) else None, elapsed_ms, response.status_code


def _require_fingerprint(payload: dict, key: str, *, nested: bool = False) -> str:
    value = payload.get(key)
    if nested and isinstance(value, dict):
        value = value.get("fingerprint_sha256")
    if not isinstance(value, str) or not _FINGERPRINT.fullmatch(value):
        raise ReleaseSmokeError(f"{key} fingerprint is unknown or invalid")
    return value.casefold()


def _probe_search(client: httpx.Client, api_url: str, workspace: dict, probe: dict) -> tuple[dict, float]:
    payload, elapsed_ms, _ = _request(
        client, "POST", f"{api_url}/public/search",
        json_body={
            "query": probe["query"], "version": probe["version"],
            "language": probe["language"], "top_k": 5,
        },
    )
    if not payload or not isinstance(payload.get("results"), list):
        raise ReleaseSmokeError(f"{probe['name']} returned an invalid response")
    rows = payload["results"]
    if not rows:
        raise ReleaseSmokeError(f"{probe['name']} returned no public evidence")
    if any(row.get("language") != "zh" or row.get("locale") != "zh-CN" for row in rows):
        raise ReleaseSmokeError(f"{probe['name']} returned non-Chinese evidence")
    scope = workspace.get("version_scopes", {}).get(probe["version"])
    members = scope.get("versions") if isinstance(scope, dict) else scope
    permitted_versions = {
        value for value in members
        if isinstance(value, str) and value.strip()
    } if isinstance(members, list) else set()
    if not permitted_versions:
        permitted_versions = {probe["version"]}
    wrong_version_rows = [row for row in rows if row.get("version") not in permitted_versions]
    if wrong_version_rows:
        raise ReleaseSmokeError(f"{probe['name']} returned wrong-version evidence")
    return {"status": "PASS", "evidence_count": len(rows), "versions": sorted({row.get("version") for row in rows if row.get("version")})}, elapsed_ms


def run_smoke(
    client: httpx.Client, *, ui_url: str, ui_revision: str,
    api_url: str, expected_sha: str,
) -> dict:
    """Run smoke checks against the public stack without invoking model generation except a pre-search scope refusal."""
    if not _REVISION.fullmatch(expected_sha or ""):
        raise ReleaseSmokeError("expected SHA must be a verified 40-character commit")
    if not _REVISION.fullmatch(ui_revision or ""):
        raise ReleaseSmokeError("UI revision must be a verified 40-character commit")
    expected_sha, ui_revision = expected_sha.casefold(), ui_revision.casefold()
    if ui_revision != expected_sha:
        raise ReleaseSmokeError("UI revision does not match the expected release SHA")
    ui_url = _validate_base_url(ui_url, "UI")
    api_url = _validate_base_url(api_url, "RAG API")

    _, ui_http_ms, _ = _request(client, "GET", ui_url)
    health, health_ms, _ = _request(client, "GET", f"{api_url}/health")
    if not health or health.get("alive") is not True or health.get("rag_ready") is not True:
        raise ReleaseSmokeError("RAG API is unhealthy or corpus is not ready")
    api_revision = health.get("build_revision")
    if not isinstance(api_revision, str) or not _REVISION.fullmatch(api_revision):
        raise ReleaseSmokeError("RAG API build revision is unknown")
    if api_revision.casefold() != expected_sha:
        raise ReleaseSmokeError("RAG API revision does not match the expected release SHA")

    workspace, workspace_ms, _ = _request(client, "GET", f"{api_url}/public/workspace")
    if not workspace:
        raise ReleaseSmokeError("RAG workspace profile is unavailable")
    if (
        workspace.get("repository") != "tomato-ros/autoware-documentation-cn"
        or workspace.get("languages") != ["zh-CN"]
        or workspace.get("current_version") != "latest"
    ):
        raise ReleaseSmokeError("RAG workspace is not the pinned Chinese-only Autoware corpus")
    if workspace.get("build_revision", "unknown").casefold() != api_revision.casefold():
        raise ReleaseSmokeError("RAG health and workspace revisions differ")
    fingerprint_keys = {
        "corpus_fingerprint": True,
        "retrieval_config_fingerprint": False,
        "evaluation_fingerprint": False,
    }
    fingerprints = {}
    for key, nested in fingerprint_keys.items():
        from_health = _require_fingerprint(health, key, nested=nested)
        from_workspace = _require_fingerprint(workspace, key, nested=nested)
        if from_health != from_workspace:
            raise ReleaseSmokeError(f"RAG health and workspace {key} values differ")
        fingerprints[key] = from_health

    probes: dict[str, dict] = {}
    probe_latencies = []
    for probe in _SEARCH_PROBES:
        result, elapsed_ms = _probe_search(client, api_url, workspace, probe)
        probes[probe["name"]] = result
        probe_latencies.append(elapsed_ms)

    # This exact out-of-scope probe must be refused before RAG retrieval or a paid model call.
    no_answer, no_answer_ms, _ = _request(
        client, "POST", f"{api_url}/public/query",
        json_body={"query": _NO_ANSWER_QUERY, "version": "latest", "language": "zh"},
    )
    if not no_answer or no_answer.get("status") != "OUT_OF_SCOPE" or no_answer.get("evidence") != []:
        raise ReleaseSmokeError("no-answer scope guard failed or returned evidence")
    probes["no_answer_scope"] = {"status": "OUT_OF_SCOPE", "evidence_count": 0}
    probe_latencies.append(no_answer_ms)

    sorted_latencies = sorted(probe_latencies)
    p95_index = max(0, math.ceil(0.95 * len(sorted_latencies)) - 1)
    return {
        "status": "PASS", "expected_sha": expected_sha, "ui_revision": ui_revision,
        "api_revision": api_revision.casefold(), "fingerprints": fingerprints,
        "probes": probes,
        "remote_latency_ms": {
            "ui_http_ms": ui_http_ms, "api_health_ms": health_ms,
            "workspace_ms": workspace_ms, "probe_p95_ms": sorted_latencies[p95_index],
            "probe_count": len(probe_latencies),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ui-url", required=True)
    parser.add_argument("--ui-revision", required=True, help="40-character SHA shown by the UI under System Information")
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--expected-sha", required=True, help="expected GitHub main release SHA")
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 60:
        parser.error("--timeout must be between 1 and 60 seconds")
    try:
        with httpx.Client(timeout=args.timeout, follow_redirects=True) as client:
            result = run_smoke(
                client, ui_url=args.ui_url, ui_revision=args.ui_revision,
                api_url=args.api_url, expected_sha=args.expected_sha,
            )
    except ReleaseSmokeError as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
