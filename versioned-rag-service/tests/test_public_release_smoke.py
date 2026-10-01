import importlib.util
import sys
from pathlib import Path

import httpx
import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "public_release_smoke.py"
spec = importlib.util.spec_from_file_location("public_release_smoke", SCRIPT)
smoke = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = smoke
spec.loader.exec_module(smoke)


EXPECTED_SHA = "a" * 40
CORPUS_HASH = "b" * 64
POLICY_HASH = "c" * 64
EVALUATION_HASH = "d" * 64


def _client(*, wrong_version=False, unhealthy=False, noanswer_status="OUT_OF_SCOPE"):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.url.host == "ui.example":
            return httpx.Response(200, text="Streamlit")
        if path == "/health":
            return httpx.Response(200, json={
                "alive": not unhealthy, "rag_ready": True,
                "build_revision": EXPECTED_SHA,
                "corpus_fingerprint": {"fingerprint_sha256": CORPUS_HASH},
                "retrieval_config_fingerprint": POLICY_HASH,
                "evaluation_fingerprint": EVALUATION_HASH,
            })
        if path == "/public/workspace":
            return httpx.Response(200, json={
                "build_revision": EXPECTED_SHA,
                "corpus_fingerprint": {"fingerprint_sha256": CORPUS_HASH},
                "retrieval_config_fingerprint": POLICY_HASH,
                "evaluation_fingerprint": EVALUATION_HASH,
                "version_scopes": {"latest": {"versions": ["docs-main", "0.52.0"]}},
                "available_versions": ["latest", "docs-main", "0.52.0"],
            })
        if path == "/public/search":
            body = request.read().decode("utf-8")
            request_json = __import__("json").loads(body)
            requested_version = request_json["version"]
            version = "0.51.0" if wrong_version and requested_version == "0.52.0" else (
                "0.52.0" if requested_version == "0.52.0" or (
                    requested_version == "latest" and request_json["language"] == "en"
                ) else "docs-main"
            )
            return httpx.Response(200, json={"status": "OK", "results": [{"version": version}]})
        if path == "/public/query":
            return httpx.Response(200, json={"status": noanswer_status, "evidence": []})
        return httpx.Response(404, json={"detail": "not found"})

    transport = httpx.MockTransport(handler)
    return httpx.Client(transport=transport)


def test_release_smoke_passes_when_ui_api_and_all_public_probes_match():
    with _client() as client:
        result = smoke.run_smoke(
            client, ui_url="https://ui.example", ui_revision=EXPECTED_SHA,
            api_url="https://api.example", expected_sha=EXPECTED_SHA,
        )

    assert result["status"] == "PASS"
    assert result["probes"]["chinese_public_query"]["versions"] == ["docs-main"]
    assert result["probes"]["english_public_query"]["versions"] == ["0.52.0"]
    assert result["probes"]["no_answer_scope"]["status"] == "OUT_OF_SCOPE"
    assert "ui_http_ms" in result["remote_latency_ms"]


def test_release_smoke_rejects_a_ui_revision_mismatch_before_network_calls():
    with _client() as client, pytest.raises(smoke.ReleaseSmokeError, match="UI revision"):
        smoke.run_smoke(
            client, ui_url="https://ui.example", ui_revision="f" * 40,
            api_url="https://api.example", expected_sha=EXPECTED_SHA,
        )


def test_release_smoke_rejects_unknown_revision():
    with _client() as client, pytest.raises(smoke.ReleaseSmokeError, match="40-character"):
        smoke.run_smoke(
            client, ui_url="https://ui.example", ui_revision="unknown",
            api_url="https://api.example", expected_sha="unknown",
        )


def test_release_smoke_rejects_unhealthy_api_and_wrong_version_results():
    with _client(unhealthy=True) as client, pytest.raises(smoke.ReleaseSmokeError, match="unhealthy"):
        smoke.run_smoke(
            client, ui_url="https://ui.example", ui_revision=EXPECTED_SHA,
            api_url="https://api.example", expected_sha=EXPECTED_SHA,
        )
    with _client(wrong_version=True) as client, pytest.raises(smoke.ReleaseSmokeError, match="wrong-version"):
        smoke.run_smoke(
            client, ui_url="https://ui.example", ui_revision=EXPECTED_SHA,
            api_url="https://api.example", expected_sha=EXPECTED_SHA,
        )


def test_release_smoke_rejects_no_answer_query_if_it_is_not_guarded():
    with _client(noanswer_status="OK") as client, pytest.raises(smoke.ReleaseSmokeError, match="no-answer scope"):
        smoke.run_smoke(
            client, ui_url="https://ui.example", ui_revision=EXPECTED_SHA,
            api_url="https://api.example", expected_sha=EXPECTED_SHA,
        )
