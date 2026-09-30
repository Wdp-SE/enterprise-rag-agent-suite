from __future__ import annotations

import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from src.answer_generation import GenerationProviderError, GenerationResponseError
from src.public_knowledge import PublicKnowledgeIndex
from src.public_server import create_app


QUESTION = "DolphinScheduler 参数优先级从高到低是什么？"
AUTOWARE_CORPUS = Path(__file__).resolve().parents[1] / "public_corpus_autoware"


def _write_empty_figure_sidecar(root: Path, tmp_path: Path) -> tuple[Path, Path]:
    manifest_sha = hashlib.sha256((root / "corpus_manifest.json").read_bytes()).hexdigest()
    sidecar_path = tmp_path / "figure_evidence_reviewed.json"
    sidecar_bytes = (json.dumps({
        "schema_version": 1,
        "corpus_manifest_sha256": manifest_sha,
        "chunks": [],
    }, separators=(",", ":")) + "\n").encode("utf-8")
    sidecar_path.write_bytes(sidecar_bytes)
    lock_path = tmp_path / "figure_evidence_reviewed.lock.json"
    lock_path.write_text(json.dumps({
        "schema_version": 1,
        "sidecar_sha256": hashlib.sha256(sidecar_bytes).hexdigest(),
        "corpus_manifest_sha256": manifest_sha,
    }), encoding="utf-8")
    return sidecar_path, lock_path


def test_autoware_workspace_profile_comes_from_manifest(tmp_path):
    index = PublicKnowledgeIndex(root=AUTOWARE_CORPUS)
    sidecar, lock = _write_empty_figure_sidecar(AUTOWARE_CORPUS, tmp_path)

    with TestClient(create_app(
        index=index,
        retrieval_config_path=AUTOWARE_CORPUS / "public_retrieval_runtime.json",
        figure_sidecar_path=sidecar,
        figure_sidecar_lock_path=lock,
    )) as client:
        workspace = client.get("/public/workspace").json()
        health = client.get("/health").json()

    assert workspace["workspace"] == "Autoware"
    assert workspace["repository"] == "autowarefoundation/autoware_universe"
    assert workspace["current_version"] == "0.52.0"
    assert workspace["baseline_version"] == "0.51.0"
    assert workspace["languages"] == ["en-US"]
    assert workspace["data_origin"] == "Autoware official public materials"
    assert health["workspace"] == "Autoware"
    assert "DolphinScheduler" not in json.dumps(workspace)


def test_autoware_public_deployment_uses_benchmarked_image_policy_and_current_release():
    index = PublicKnowledgeIndex(root=AUTOWARE_CORPUS)
    question = "What two readable labels appear in the Goal Planner image about the drivable area and stopping?"

    with TestClient(create_app(
        index=index,
        retrieval_config_path=AUTOWARE_CORPUS / "public_retrieval_runtime.json",
    )) as client:
        health = client.get("/health").json()
        workspace = client.get("/public/workspace").json()
        response = client.post("/public/search", json={
            "query": question, "version": "current", "language": "en",
        })

    assert health["runtime_retrieval_policy"] == "bm25_figure_ocr"
    assert health["approved_image_chunk_count"] == 2
    assert workspace["retrieval_evaluation_status"] == "autoware_retrieval_v1_validated"
    assert workspace["current_version"] == "0.52.0"
    assert workspace["available_versions"] == ["0.52.0", "0.51.0"]
    assert workspace["retrieval_evaluation"]["holdout"]["image_evidence_hits"] == "2/2"
    assert response.status_code == 200
    assert any(row.get("figure_id") == "32682b345ea86e13" for row in response.json()["results"])


def test_public_server_selects_manifest_corpus_and_runtime_config_from_environment(monkeypatch):
    monkeypatch.setenv("RAG_PUBLIC_CORPUS_ROOT", str(AUTOWARE_CORPUS))
    monkeypatch.setenv(
        "RAG_PUBLIC_RETRIEVAL_CONFIG", str(AUTOWARE_CORPUS / "public_retrieval_runtime.json")
    )

    with TestClient(create_app()) as client:
        health = client.get("/health").json()
        workspace = client.get("/public/workspace").json()

    assert health["workspace"] == workspace["workspace"] == "Autoware"
    assert workspace["current_version"] == "0.52.0"


def test_public_workspace_and_review_support_manifests_without_declared_version_list():
    index = PublicKnowledgeIndex()
    hit = index.search("workflow parameter priority", top_k=1, version="3.4.3", language="en")[0]

    with TestClient(create_app(index=index)) as client:
        workspace = client.get("/public/workspace").json()
        response = client.post("/public/review-advice", json={
            "change_summary": "Review a parameter change.",
            "evidence_chunk_ids": [hit["chunk_id"]],
        })

    assert workspace["available_versions"][0] == "3.4.3"
    assert "3.4.2" in workspace["available_versions"]
    assert response.status_code == 200
    assert response.json()["target_version"] == "3.4.3"


def test_generation_prompts_use_active_workspace_identity_not_old_product_brand(tmp_path):
    index = PublicKnowledgeIndex(root=AUTOWARE_CORPUS)
    sidecar, lock = _write_empty_figure_sidecar(AUTOWARE_CORPUS, tmp_path)
    expected = index.search("planning validator trajectory", top_k=1, version="current", language="all")[0]
    prompts = []

    class Generator:
        def generate(self, *, question, context):
            prompts.append(context)
            return {
                "final_answer": "The planning validator checks a planned trajectory.",
                "relevant_sources": [{"document_id": expected["chunk_id"], "page_number": 1}],
            }

        def generate_review(self, *, change_summary, context):
            prompts.append(context)
            return {
                "change_interpretation": "Review the planning validation behavior.",
                "impact_candidates": [{
                    "evidence_chunk_id": expected["chunk_id"],
                    "reason": "The selected source describes planning validation.",
                    "suggested_action": "Manually verify the affected planner behavior.",
                }],
                "evidence_gaps": [], "version_ambiguities": [],
                "reviewer_actions": ["Compare the pinned source version."],
                "review_status": "REQUIRES_HUMAN_REVIEW",
            }

    with TestClient(create_app(
        index=index, generator=Generator(),
        retrieval_config_path=AUTOWARE_CORPUS / "public_retrieval_runtime.json",
        figure_sidecar_path=sidecar, figure_sidecar_lock_path=lock,
    )) as client:
        query = client.post("/public/query", json={
            "query": "planning validator trajectory", "language": "all",
        }).json()
        advice = client.post("/public/review-advice", json={
            "change_summary": "Review planner validation behavior.",
            "evidence_chunk_ids": [expected["chunk_id"]],
        }).json()

    assert query["status"] == advice["status"] == "OK"
    assert len(prompts) == 2
    assert all("Autoware" in prompt for prompt in prompts)
    assert all("DolphinScheduler" not in prompt for prompt in prompts)


def test_stale_v3_release_is_rejected_after_retrieval_policy_changed():
    project = Path(__file__).resolve().parents[2]
    corpus = project / "versioned-rag-service" / "public_corpus"
    release = json.loads((corpus / "retrieval_release.json").read_text(encoding="utf-8"))
    actual_policy_sha = hashlib.sha256((corpus / "retrieval_policy.json").read_bytes()).hexdigest()
    assert release["policy_sha256"] != actual_policy_sha
    with TestClient(create_app(index=PublicKnowledgeIndex())) as client:
        workspace = client.get("/public/workspace").json()
    assert workspace["retrieval_evaluation_status"] == "expanded_corpus_pending_rebenchmark"
    assert "retrieval_evaluation" not in workspace


def test_workspace_reports_latest_source_retrieval_timestamp():
    index = PublicKnowledgeIndex()
    timestamps = [
        datetime.fromisoformat(row["retrieval_timestamp"].replace("Z", "+00:00")).astimezone(timezone.utc)
        for row in index.manifest["sources"] if row.get("retrieval_timestamp")
    ]
    with TestClient(create_app(index=index)) as client:
        workspace = client.get("/public/workspace").json()

    reported_timestamp = datetime.fromisoformat(
        workspace["latest_source_retrieval_timestamp"].replace("Z", "+00:00")
    )
    assert reported_timestamp == max(timestamps)


def test_legacy_default_corpus_routes_remain_available_without_stale_eval_claims():
    index = PublicKnowledgeIndex()
    with TestClient(create_app(index=index)) as client:
        health = client.get("/health").json()
        assert health["alive"] and health["rag_ready"]
        assert health["retrieval_policy"] == "bm25"
        paths = client.get("/openapi.json").json()["paths"]
        assert "/public/search" in paths and "/public/query" in paths
        assert "/public/review-advice" in paths
        assert "/engineering/items/diff" in paths and "/engineering/impacts/discover" in paths
        assert "/retrieve" not in paths and "/query" not in paths
        assert "/public/change/analyze" not in paths
        proposal = next(
            row for row in client.get("/public/documents").json()["documents"]
            if row["document_key"] == "proposals/dsip-107-proposal"
        )
        assert "DSIP-107" in proposal["title"]
        workspace = client.get("/public/workspace").json()
        assert workspace["source_count"] == len(index.manifest["sources"])
        assert workspace["source_count"] > 0
        assert workspace["chunk_count"] == len(index.chunks)
        assert workspace["upstream_writes_enabled"] is False
        assert workspace["retrieval_evaluation_status"] == "expanded_corpus_pending_rebenchmark"
        assert "retrieval_evaluation" not in workspace
        assert "retrieval_experiment" not in workspace
        response = client.post("/public/search", json={"query": QUESTION})
        assert response.status_code == 200
        assert response.json()["results"][0]["source_url"].startswith(
            "https://github.com/apache/dolphinscheduler/blob/"
        )


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"], ids=["lf", "crlf"])
def test_legacy_v4_metrics_are_not_claimed_after_retrieval_runtime_change(monkeypatch, newline):
    index = PublicKnowledgeIndex()
    service = Path(__file__).resolve().parents[1]
    newline_sensitive_files = {
        (index.root / "retrieval_policy.json").resolve(),
        (index.root / "figure_evidence_reviewed.json").resolve(),
        (service / "src" / "retrieval_fusion.py").resolve(),
        (service / "src" / "public_retrieval_runtime.py").resolve(),
    }
    original_read_bytes = Path.read_bytes

    def read_with_line_ending(path):
        data = original_read_bytes(path)
        if path.resolve() in newline_sensitive_files:
            data = data.replace(b"\r\n", b"\n").replace(b"\n", newline)
        return data

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_bytes", read_with_line_ending)
        with TestClient(create_app(index=index)) as client:
            workspace = client.get("/public/workspace").json()

    assert workspace["retrieval_evaluation_status"] != "v4_bm25_validated"
    assert "retrieval_experiment" not in workspace


def test_workspace_hides_v4_release_for_mismatched_runtime_policy_or_manifest(monkeypatch):
    index = PublicKnowledgeIndex()
    with TestClient(create_app(index=index)) as client:
        index.policy["default_policy"] = "dense"
        changed_policy = client.get("/public/workspace").json()
        assert changed_policy["retrieval_evaluation_status"] != "v4_bm25_validated"
        assert "retrieval_evaluation" not in changed_policy

        index.policy["default_policy"] = "bm25"
        index.manifest["current_version"] = "3.5.0"
        changed_manifest = client.get("/public/workspace").json()
        assert changed_manifest["retrieval_evaluation_status"] != "v4_bm25_validated"
        assert "retrieval_evaluation" not in changed_manifest

        index.manifest["current_version"] = "3.4.3"
        original_read_bytes = Path.read_bytes

        def code_changed(path):
            return b"changed retrieval implementation" if path.name == "public_knowledge.py" else original_read_bytes(path)

        with monkeypatch.context() as patch:
            patch.setattr(Path, "read_bytes", code_changed)
            changed_code = client.get("/public/workspace").json()
        assert changed_code["retrieval_evaluation_status"] != "v4_bm25_validated"
        assert "retrieval_evaluation" not in changed_code


def test_workspace_degrades_if_v4_experiment_summary_is_incomplete(monkeypatch):
    index = PublicKnowledgeIndex()
    release_path = Path(__file__).resolve().parents[1] / "config" / "retrieval_experiment_v4.json"
    release = json.loads(release_path.read_text(encoding="utf-8"))
    del release["dev_bm25"]["question_count"]
    original_read_text = Path.read_text

    def incomplete_release(path, *args, **kwargs):
        return json.dumps(release) if path == release_path else original_read_text(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_text", incomplete_release)
        with TestClient(create_app(index=index)) as client:
            workspace = client.get("/public/workspace").json()

    assert workspace["retrieval_evaluation_status"] != "v4_bm25_validated"
    assert "retrieval_evaluation" not in workspace


def test_public_query_without_generator_returns_evidence_not_fake_answer():
    with TestClient(create_app(index=PublicKnowledgeIndex())) as client:
        payload = client.post("/public/query", json={"query": QUESTION}).json()
        assert payload["status"] == "GENERATION_NOT_CONFIGURED"
        assert payload["answer"] == "N/A"
        assert payload["sources"] == []
        assert payload["evidence"]


def test_api_server_health_example_retrieves_the_exact_endpoint_evidence():
    index = PublicKnowledgeIndex()
    hits = index.search(
        "What is the API-Server health endpoint?",
        version="current", language="zh_preferred", top_k=5,
    )

    assert hits[0]["document_key"] == "guide/api/healthcheck"
    assert hits[0]["heading"] == "API-Server"
    assert "/dolphinscheduler/actuator/health" in hits[0]["content"]


def test_public_search_matches_hyphenated_user_terms_to_official_compounds():
    with TestClient(create_app(index=PublicKnowledgeIndex())) as client:
        response = client.post(
            "/public/search",
            json={"query": "What is the API server health-check endpoint?"},
        )

    assert response.status_code == 200
    results = response.json()["results"]
    endpoint_evidence = [
        row for row in results
        if row["document_key"] == "guide/api/healthcheck" and row["heading"] == "API-Server"
    ]
    assert endpoint_evidence
    assert "/dolphinscheduler/actuator/health" in endpoint_evidence[0]["content"]


def test_abstention_reports_missing_question_terms_instead_of_infrastructure_failure():
    class AbstainingGenerator:
        provider = "deepseek"
        model = "test-model"

        def generate(self, *, question, context):
            return {"final_answer": "N/A", "relevant_sources": []}

    query = "What is the API server health-check endpoint?"
    with TestClient(create_app(index=PublicKnowledgeIndex(), generator=AbstainingGenerator())) as client:
        payload = client.post("/public/query", json={"query": query}).json()

    assert payload["status"] == "ABSTAINED"
    diagnostic = payload["generation"]
    assert diagnostic["failure_reason"] == "MODEL_NO_SUPPORTED_ANSWER"
    assert diagnostic["candidate_count"] == len(payload["evidence"]) == 5
    assert {"api", "server", "health", "check"}.issubset(
        set(diagnostic["evidence_coverage"]["matched_terms"])
    )
    assert diagnostic["evidence_coverage"]["missing_terms"] == []


def test_answer_with_no_valid_evidence_citation_reports_citation_failure():
    class UncitedGenerator:
        provider = "deepseek"
        model = "test-model"

        def generate(self, *, question, context):
            return {
                "final_answer": "The endpoint is /example.",
                "relevant_sources": [{"document_id": "not-in-evidence", "page_number": 1}],
            }

    with TestClient(create_app(index=PublicKnowledgeIndex(), generator=UncitedGenerator())) as client:
        payload = client.post("/public/query", json={"query": QUESTION}).json()

    assert payload["status"] == "ABSTAINED"
    assert payload["answer"] == "N/A"
    diagnostic = payload["generation"]
    assert diagnostic["failure_reason"] == "NO_VALID_EVIDENCE_CITATIONS"
    assert diagnostic["claimed_citation_count"] == 1
    assert diagnostic["valid_citation_count"] == 0


def test_oov_bm25_does_not_send_zero_score_candidates_to_paid_generator():
    class Generator:
        def generate(self, *, question, context):
            raise AssertionError("No positive retrieval evidence: paid generator must not be called")

    index = PublicKnowledgeIndex()
    with TestClient(create_app(index=index, generator=Generator())) as client:
        question = "qzxwneverpresenttokenforbm25"
        search = client.post("/public/search", json={"query": question}).json()
        answer = client.post("/public/query", json={"query": question}).json()

    assert search["results"] == []
    assert answer["status"] == "NO_EVIDENCE"
    assert answer["evidence"] == []
    assert answer["sources"] == []


def test_search_version_validation_uses_published_manifest_instead_of_fixed_literal():
    index = PublicKnowledgeIndex()
    future = dict(index.manifest["sources"][0], version="3.5.0")
    index.manifest["sources"].append(future)
    index.manifest["current_version"] = "3.5.0"
    with TestClient(create_app(index=index)) as client:
        assert client.post("/public/search", json={"query": QUESTION, "version": "3.5.0"}).status_code == 200
        assert client.post("/public/search", json={"query": QUESTION, "version": "current"}).status_code == 200
        assert client.post("/public/query", json={"query": QUESTION, "version": "3.4.1"}).status_code == 422


def test_generation_enabled_without_api_key_stays_in_evidence_only_mode(monkeypatch):
    monkeypatch.setenv("RD_V2_ALLOW_EXTERNAL_GENERATION", "true")
    monkeypatch.setenv("RD_V2_GENERATION_PROVIDER", "dashscope")
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    with TestClient(create_app(index=PublicKnowledgeIndex())) as client:
        response = client.post(
            "/public/query", json={"query": QUESTION},
            headers={"X-Demo-Session-ID": "publictestsession"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "GENERATION_NOT_CONFIGURED"
    assert payload["answer"] == "N/A"
    assert payload["sources"] == []
    assert payload["evidence"]


def test_health_reports_generation_configuration_without_exposing_a_secret(monkeypatch):
    monkeypatch.setenv("RD_V2_ALLOW_EXTERNAL_GENERATION", "true")
    monkeypatch.setenv("RD_V2_GENERATION_PROVIDER", "deepseek")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "wrong-provider-secret")

    with TestClient(create_app(index=PublicKnowledgeIndex())) as client:
        health = client.get("/health").json()

    assert health["rag_ready"] is True
    assert health["generation"]["status"] == "API_KEY_MISSING"
    assert health["generation"]["provider"] == "deepseek"
    assert health["generation"]["model"] == "deepseek-v4-flash"
    assert "wrong-provider-secret" not in str(health)


def test_public_search_does_not_allow_request_to_choose_experimental_policy():
    with TestClient(create_app(index=PublicKnowledgeIndex())) as client:
        response = client.post("/public/search", json={"query": QUESTION, "policy": "hybrid"})

    assert response.status_code == 422


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"], ids=["lf", "crlf"])
def test_reviewed_figure_sidecar_lock_is_stable_across_platform_line_endings(tmp_path, newline):
    index = PublicKnowledgeIndex()
    original = (index.root / "figure_evidence_reviewed.json").read_bytes()
    normalized = original.replace(b"\r\n", b"\n")
    sidecar_path = tmp_path / "figure-evidence.json"
    sidecar_path.write_bytes(normalized.replace(b"\n", newline))

    with TestClient(create_app(index=index, figure_sidecar_path=sidecar_path)) as client:
        response = client.get("/health")

    assert response.status_code == 200


def test_public_server_rejects_changed_reviewed_ocr_text_even_if_image_hash_is_unchanged(tmp_path):
    index = PublicKnowledgeIndex()
    sidecar_path = tmp_path / "tampered-figure-evidence.json"
    sidecar = json.loads((index.root / "figure_evidence_reviewed.json").read_text(encoding="utf-8"))
    image_chunk = next(row for row in sidecar["chunks"] if row["figure_id"] == "db6baeb0b9b5364a")
    original_image_hash = image_chunk["sha256"]
    image_chunk["content"] = "ATTACKER-CHANGED OCR CONTENT"
    image_chunk["sha256"] = original_image_hash
    sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")

    with pytest.raises(ValueError, match="figure evidence sidecar integrity"):
        with TestClient(create_app(index=index, figure_sidecar_path=sidecar_path)):
            pass


def test_configured_runtime_policy_returns_reviewed_image_evidence(tmp_path):
    config = json.loads((Path(__file__).resolve().parents[1] / "config" / "public_retrieval_runtime.json").read_text(encoding="utf-8"))
    config["default_policy"] = "bm25_figure_ocr"
    config_path = tmp_path / "runtime.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with TestClient(create_app(index=PublicKnowledgeIndex(), retrieval_config_path=config_path)) as client:
        workspace = client.get("/public/workspace").json()
        response = client.post("/public/search", json={
            "query": "processExitValue=0", "version": "3.4.3", "language": "en", "top_k": 20,
        })

    assert workspace["retrieval_policy"] == "bm25_figure_ocr"
    assert workspace["base_retrieval_policy"] == "bm25"
    assert workspace["approved_image_chunk_count"] == 30
    assert response.status_code == 200
    hits = response.json()["results"]
    image = next(row for row in hits if row.get("figure_id") == "db6baeb0b9b5364a")
    assert image["modality"] == "image_ocr"
    assert image["review_status"] == "approved"
    assert image["sha256"]
    assert image["raw_url"].startswith("https://raw.githubusercontent.com/apache/dolphinscheduler/")


def test_non_v3_runtime_policy_does_not_publish_bm25_v3_metrics(tmp_path):
    config = json.loads((Path(__file__).resolve().parents[1] / "config" / "public_retrieval_runtime.json").read_text(encoding="utf-8"))
    config["default_policy"] = "bm25_figure_ocr"
    config_path = tmp_path / "runtime.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with TestClient(create_app(index=PublicKnowledgeIndex(), retrieval_config_path=config_path)) as client:
        workspace = client.get("/public/workspace").json()

    assert workspace["retrieval_policy"] == "bm25_figure_ocr"
    assert workspace["retrieval_evaluation_status"] != "v4_bm25_validated"
    assert "retrieval_evaluation" not in workspace


def test_health_reports_injected_generator_as_configured_but_unverified(monkeypatch):
    monkeypatch.setenv("RD_V2_ALLOW_EXTERNAL_GENERATION", "false")

    class Generator:
        provider = "deepseek"
        model = "deepseek-v4-flash"

    with TestClient(create_app(index=PublicKnowledgeIndex(), generator=Generator())) as client:
        health = client.get("/health").json()

    assert health["generation"] == {
        "status": "CONFIGURED_UNVERIFIED",
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
    }


def test_public_query_returns_provider_diagnostics_without_changing_answer_contract():
    index = PublicKnowledgeIndex()
    cited_chunk = index.search(QUESTION)[0]["chunk_id"]

    class Generator:
        provider = "deepseek"
        model = "deepseek-v4-flash"

        def generate_with_diagnostics(self, *, question, context):
            return ({
                "final_answer": "证据支持的回答。",
                "relevant_sources": [{"document_id": cited_chunk, "page_number": 1}],
            }, {
                "provider": "deepseek", "requested_model": "deepseek-v4-flash",
                "returned_model": "deepseek-v4-flash", "finish_reason": "stop",
                "usage": {"input_tokens": 80, "output_tokens": 20, "total_tokens": 100},
            })

    with TestClient(create_app(index=index, generator=Generator())) as client:
        payload = client.post("/public/query", json={"query": QUESTION}).json()

    assert payload["status"] == "OK"
    assert payload["sources"][0]["chunk_id"] == cited_chunk
    assert payload["generation"]["returned_model"] == "deepseek-v4-flash"
    assert payload["generation"]["usage"]["total_tokens"] == 100
    assert len(payload["generation"]["request_id"]) == 32


def test_public_query_keeps_evidence_for_safe_provider_error_categories():
    class Generator:
        def generate(self, *, question, context):
            raise GenerationProviderError("GENERATION_RATE_LIMITED")

    with TestClient(create_app(index=PublicKnowledgeIndex(), generator=Generator())) as client:
        payload = client.post("/public/query", json={"query": QUESTION}).json()

    assert payload["status"] == "GENERATION_RATE_LIMITED"
    assert payload["answer"] == "N/A"
    assert payload["sources"] == []
    assert payload["evidence"]
    assert payload["generation"]["request_id"]


def test_public_query_reports_truncation_with_safe_metadata_and_evidence():
    class Generator:
        def generate_with_diagnostics(self, *, question, context):
            raise GenerationResponseError("GENERATION_RESPONSE_TRUNCATED", {
                "provider": "deepseek", "requested_model": "deepseek-v4-flash",
                "returned_model": "deepseek-v4-flash", "finish_reason": "length",
                "usage": {"total_tokens": 1094},
            })

    with TestClient(create_app(index=PublicKnowledgeIndex(), generator=Generator())) as client:
        payload = client.post("/public/query", json={"query": QUESTION}).json()

    assert payload["status"] == "GENERATION_RESPONSE_TRUNCATED"
    assert payload["evidence"]
    assert payload["generation"]["finish_reason"] == "length"
    assert payload["generation"]["usage"]["total_tokens"] == 1094


def test_deepseek_provider_without_deepseek_key_stays_in_evidence_only_mode(monkeypatch):
    monkeypatch.setenv("RD_V2_ALLOW_EXTERNAL_GENERATION", "true")
    monkeypatch.setenv("RD_V2_GENERATION_PROVIDER", "deepseek")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "must-not-be-used-for-deepseek")

    with TestClient(create_app(index=PublicKnowledgeIndex())) as client:
        response = client.post(
            "/public/query", json={"query": QUESTION},
            headers={"X-Demo-Session-ID": "publictestsession"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "GENERATION_NOT_CONFIGURED"
    assert payload["answer"] == "N/A"
    assert payload["sources"] == []
    assert payload["evidence"]


def test_generation_enabled_with_api_key_wires_qwen_provider(monkeypatch):
    monkeypatch.setenv("RD_V2_ALLOW_EXTERNAL_GENERATION", "true")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "unit-test-placeholder")
    index = PublicKnowledgeIndex()
    cited_chunk = index.search(QUESTION)[0]["chunk_id"]
    constructed = {}

    class ConfiguredGenerator:
        def __init__(self, *, provider: str, model: str):
            constructed["provider"] = provider
            constructed["model"] = model

        def generate(self, *, question: str, context: str) -> dict:
            return {
                "final_answer": "由检索证据支持的测试回答。",
                "relevant_sources": [{"document_id": cited_chunk, "page_number": 1}],
            }

    monkeypatch.setattr("src.public_server.StructuredAnswerGenerator", ConfiguredGenerator)
    with TestClient(create_app(index=index)) as client:
        response = client.post(
            "/public/query", json={"query": QUESTION},
            headers={"X-Demo-Session-ID": "publictestsession"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert constructed == {"provider": "dashscope", "model": "qwen-turbo"}
    assert payload["status"] == "OK"
    assert payload["answer"] == "由检索证据支持的测试回答。"
    assert payload["sources"][0]["chunk_id"] == cited_chunk


def test_generation_enabled_with_deepseek_key_wires_deepseek_provider(monkeypatch):
    monkeypatch.setenv("RD_V2_ALLOW_EXTERNAL_GENERATION", "true")
    monkeypatch.setenv("RD_V2_GENERATION_PROVIDER", "deepseek")
    monkeypatch.delenv("RD_V2_GENERATION_MODEL", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-placeholder")
    index = PublicKnowledgeIndex()
    cited_chunk = index.search(QUESTION)[0]["chunk_id"]
    constructed = {}

    class ConfiguredGenerator:
        def __init__(self, *, provider: str, model: str):
            constructed["provider"] = provider
            constructed["model"] = model

        def generate(self, *, question: str, context: str) -> dict:
            return {
                "final_answer": "由检索证据支持的 DeepSeek 测试回答。",
                "relevant_sources": [{"document_id": cited_chunk, "page_number": 1}],
            }

    monkeypatch.setattr("src.public_server.StructuredAnswerGenerator", ConfiguredGenerator)
    with TestClient(create_app(index=index)) as client:
        response = client.post(
            "/public/query", json={"query": QUESTION},
            headers={"X-Demo-Session-ID": "publictestsession"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert constructed == {"provider": "deepseek", "model": "deepseek-v4-flash"}
    assert payload["status"] == "OK"
    assert payload["answer"] == "由检索证据支持的 DeepSeek 测试回答。"
    assert payload["sources"][0]["chunk_id"] == cited_chunk


def test_public_query_checks_citation_membership_without_call_budget(monkeypatch):
    class Generator:
        def __init__(self, citation_id):
            self.citation_id = citation_id

        def generate(self, *, question, context):
            return {
                "final_answer": "上游传递参数优先。",
                "relevant_sources": [{"document_id": self.citation_id, "page_number": 1}],
            }

    index = PublicKnowledgeIndex()
    top = index.search(QUESTION)[0]
    monkeypatch.setenv("MAX_LLM_CALLS_PER_SESSION", "1")
    with TestClient(create_app(index=index, generator=Generator(top["chunk_id"]))) as client:
        headers = {"X-Demo-Session-ID": "publictestsession"}
        first = client.post("/public/query", json={"query": QUESTION}, headers=headers)
        assert first.status_code == 200
        assert first.json()["status"] == "OK"
        assert first.json()["sources"][0]["chunk_id"] == top["chunk_id"]
        repeated = client.post("/public/query", json={"query": QUESTION}, headers=headers)
        assert repeated.status_code == 200
        assert repeated.json()["status"] == "OK"
    with TestClient(create_app(index=index, generator=Generator("invented-chunk"))) as client:
        result = client.post(
            "/public/query", json={"query": QUESTION},
            headers={"X-Demo-Session-ID": "anotherpublicsession"},
        ).json()
        assert result["status"] == "ABSTAINED"
        assert result["sources"] == []


def test_public_generation_has_no_application_call_limit(monkeypatch):
    class Generator:
        def __init__(self, citation_id):
            self.citation_id = citation_id

        def generate(self, *, question, context):
            return {
                "final_answer": "supported answer",
                "relevant_sources": [{"document_id": self.citation_id, "page_number": 1}],
            }

    # Old deployment variables must not silently reintroduce the retired cap.
    monkeypatch.setenv("MAX_LLM_CALLS_PER_SESSION", "10")
    monkeypatch.setenv("MAX_LLM_CALLS_PER_PROCESS", "30")
    index = PublicKnowledgeIndex()
    generator = Generator(index.search(QUESTION)[0]["chunk_id"])
    with TestClient(create_app(index=index, generator=generator)) as client:
        responses = [
            client.post(
                "/public/query", json={"query": QUESTION},
                headers={"X-Demo-Session-ID": "publictestsession"},
            )
            for _ in range(35)
        ]
    assert [response.status_code for response in responses] == [200] * 35
def test_public_query_does_not_enforce_a_process_budget(monkeypatch):
    class Generator:
        def __init__(self, citation_id):
            self.citation_id = citation_id
            self.calls = 0

        def generate(self, *, question, context):
            self.calls += 1
            return {
                "final_answer": "supported answer",
                "relevant_sources": [{"document_id": self.citation_id, "page_number": 1}],
            }

    index = PublicKnowledgeIndex()
    generator = Generator(index.search(QUESTION)[0]["chunk_id"])
    monkeypatch.setenv("MAX_LLM_CALLS_PER_SESSION", "1")
    monkeypatch.setenv("MAX_LLM_CALLS_PER_PROCESS", "2")
    with TestClient(create_app(index=index, generator=generator)) as client:
        responses = [
            client.post(
                "/public/query", json={"query": QUESTION},
                headers={"X-Demo-Session-ID": f"session_{number:08d}"},
            )
            for number in range(35)
        ]
    assert [response.status_code for response in responses] == [200] * 35
    assert generator.calls == 35


def test_provider_connection_error_fails_closed_with_actionable_status():
    class Generator:
        def generate(self, *, question, context):
            raise ConnectionError("provider is unreachable")

    with TestClient(create_app(index=PublicKnowledgeIndex(), generator=Generator())) as client:
        response = client.post(
            "/public/query", json={"query": QUESTION},
            headers={"X-Demo-Session-ID": "connectiontestsession"},
        )

    payload = response.json()
    assert response.status_code == 200
    assert payload["status"] == "GENERATION_PROVIDER_UNAVAILABLE"
    assert payload["answer"] == "N/A"
    assert payload["sources"] == []
    assert payload["evidence"]


def test_provider_rejection_returns_actionable_status_without_provider_details():
    class Generator:
        def generate(self, *, question, context):
            raise RuntimeError("provider rejected request; never expose this detail")

    with TestClient(create_app(index=PublicKnowledgeIndex(), generator=Generator())) as client:
        response = client.post("/public/query", json={"query": QUESTION})

    payload = response.json()
    assert payload["status"] == "GENERATION_PROVIDER_REJECTED"
    assert "never expose" not in str(payload)
    assert payload["answer"] == "N/A"
    assert payload["sources"] == []
    assert payload["evidence"]


def test_invalid_structured_generation_returns_evidence_only_status():
    class Generator:
        def generate(self, *, question, context):
            raise ValueError("invalid model response")

    with TestClient(create_app(index=PublicKnowledgeIndex(), generator=Generator())) as client:
        response = client.post("/public/query", json={"query": QUESTION})

    payload = response.json()
    assert payload["status"] == "GENERATION_RESPONSE_INVALID"
    assert payload["answer"] == "N/A"
    assert payload["sources"] == []
    assert payload["evidence"]


def test_public_review_advice_is_limited_to_submitted_current_evidence():
    index = PublicKnowledgeIndex()
    allowed = index.search(QUESTION, top_k=2, version="3.4.3", language="all")
    constructed = {}

    class Generator:
        def generate_review(self, *, change_summary, context):
            constructed["change_summary"] = change_summary
            constructed["context"] = context
            return {
                "change_interpretation": "假设将启动参数优先级提升。",
                "impact_candidates": [{
                    "evidence_chunk_id": allowed[0]["chunk_id"],
                    "reason": "该片段说明参数优先级。",
                    "suggested_action": "检查下游配置说明是否同步。",
                }],
                "evidence_gaps": ["尚未检查英文说明。"],
                "version_ambiguities": [],
                "reviewer_actions": ["逐版本核对相关说明。"],
                "review_status": "REQUIRES_HUMAN_REVIEW",
            }

    with TestClient(create_app(index=index, generator=Generator())) as client:
        response = client.post("/public/review-advice", json={
            "change_summary": "将启动参数调整为最高优先级",
            "evidence_chunk_ids": [row["chunk_id"] for row in allowed],
        })

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "OK"
    assert payload["review"]["change_interpretation"].startswith("假设将启动参数")
    assert payload["review"]["impact_candidates"][0]["reason"] == "该片段说明参数优先级。"
    assert payload["review"]["review_status"] == "REQUIRES_HUMAN_REVIEW"
    assert [row["chunk_id"] for row in payload["sources"]] == [allowed[0]["chunk_id"]]
    assert {row["chunk_id"] for row in payload["evidence"]} == {row["chunk_id"] for row in allowed}
    assert "将启动参数调整为最高优先级" in constructed["change_summary"]
    assert all(row["chunk_id"] in constructed["context"] for row in allowed)


def test_public_review_advice_rejects_model_citations_outside_submitted_evidence():
    index = PublicKnowledgeIndex()
    allowed = index.search(QUESTION, top_k=1, version="3.4.3", language="all")[0]

    class Generator:
        def generate_review(self, *, change_summary, context):
            return {
                "change_interpretation": "需核对相关资料。",
                "impact_candidates": [{
                    "evidence_chunk_id": "invented-chunk",
                    "reason": "模型编造的证据。", "suggested_action": "不要采纳。",
                }],
                "evidence_gaps": [], "version_ambiguities": [],
                "reviewer_actions": ["人工复核。"],
                "review_status": "REQUIRES_HUMAN_REVIEW",
            }

    with TestClient(create_app(index=index, generator=Generator())) as client:
        payload = client.post("/public/review-advice", json={
            "change_summary": "假设变更", "evidence_chunk_ids": [allowed["chunk_id"]],
        }).json()

    assert payload["status"] == "GENERATION_RESPONSE_INVALID"
    assert payload["review"] is None
    assert payload["sources"] == []
    assert payload["evidence"][0]["chunk_id"] == allowed["chunk_id"]


def test_public_review_abstention_keeps_validated_evidence_gaps_without_impact():
    index = PublicKnowledgeIndex()
    hit = index.search(QUESTION, top_k=1, version="3.4.3", language="all")[0]

    class Generator:
        def generate_review(self, *, change_summary, context):
            return {
                "change_interpretation": "该变更需要更多资料才能判断影响。",
                "impact_candidates": [],
                "evidence_gaps": ["缺少下游节点恢复行为说明。"],
                "version_ambiguities": ["尚未核对历史版本。"],
                "reviewer_actions": ["补充恢复策略来源后重新审查。"],
                "review_status": "REQUIRES_HUMAN_REVIEW",
            }

    with TestClient(create_app(index=index, generator=Generator())) as client:
        payload = client.post("/public/review-advice", json={
            "change_summary": "调整故障恢复策略", "evidence_chunk_ids": [hit["chunk_id"]],
        }).json()

    assert payload["status"] == "ABSTAINED"
    assert payload["answer"] == "N/A"
    assert payload["sources"] == []
    assert payload["evidence"][0]["chunk_id"] == hit["chunk_id"]
    assert payload["review"]["impact_candidates"] == []
    assert payload["review"]["evidence_gaps"] == ["缺少下游节点恢复行为说明。"]
    assert payload["review"]["version_ambiguities"] == ["尚未核对历史版本。"]
    assert payload["review"]["reviewer_actions"] == ["补充恢复策略来源后重新审查。"]


def test_public_review_advice_provider_failure_keeps_retrieved_evidence():
    index = PublicKnowledgeIndex()
    hit = index.search(QUESTION, top_k=1, version="3.4.3", language="all")[0]

    class Generator:
        def generate_review(self, *, change_summary, context):
            raise ConnectionError("provider is unreachable")

    with TestClient(create_app(index=index, generator=Generator())) as client:
        payload = client.post("/public/review-advice", json={
            "change_summary": "假设变更", "evidence_chunk_ids": [hit["chunk_id"]],
        }).json()

    assert payload["status"] == "GENERATION_PROVIDER_UNAVAILABLE"
    assert payload["review"] is None
    assert payload["sources"] == []
    assert payload["evidence"][0]["chunk_id"] == hit["chunk_id"]


def test_public_review_diagnostics_preserve_selected_evidence_and_review_contract():
    index = PublicKnowledgeIndex()
    hit = index.search(QUESTION, top_k=1, version="3.4.3", language="all")[0]

    class Generator:
        provider = "deepseek"
        model = "deepseek-v4-flash"

        def generate_review_with_diagnostics(self, *, change_summary, context):
            return ({
                "change_interpretation": "需要人工核对参数顺序。",
                "impact_candidates": [{
                    "evidence_chunk_id": hit["chunk_id"],
                    "reason": "该段定义当前行为。", "suggested_action": "核对变更前后说明。",
                }],
                "evidence_gaps": [], "version_ambiguities": [],
                "reviewer_actions": ["人工确认。"],
                "review_status": "REQUIRES_HUMAN_REVIEW",
            }, {
                "provider": "deepseek", "requested_model": "deepseek-v4-flash",
                "returned_model": "deepseek-v4-flash", "finish_reason": "stop",
                "usage": {"input_tokens": 40, "output_tokens": 30, "total_tokens": 70},
            })

    with TestClient(create_app(index=index, generator=Generator())) as client:
        payload = client.post("/public/review-advice", json={
            "change_summary": "调整参数顺序", "evidence_chunk_ids": [hit["chunk_id"]],
        }).json()

    assert payload["status"] == "OK"
    assert payload["review"]["review_status"] == "REQUIRES_HUMAN_REVIEW"
    assert payload["sources"][0]["chunk_id"] == hit["chunk_id"]
    assert payload["generation"]["usage"]["total_tokens"] == 70


def test_public_review_billing_failure_is_distinct_and_keeps_evidence():
    index = PublicKnowledgeIndex()
    hit = index.search(QUESTION, top_k=1, version="3.4.3", language="all")[0]

    class Generator:
        def generate_review(self, *, change_summary, context):
            raise GenerationProviderError("GENERATION_BILLING_REQUIRED")

    with TestClient(create_app(index=index, generator=Generator())) as client:
        payload = client.post("/public/review-advice", json={
            "change_summary": "调整参数顺序", "evidence_chunk_ids": [hit["chunk_id"]],
        }).json()

    assert payload["status"] == "GENERATION_BILLING_REQUIRED"
    assert payload["review"] is None
    assert payload["evidence"][0]["chunk_id"] == hit["chunk_id"]
    assert payload["generation"]["request_id"]


def test_public_review_advice_rejects_unknown_or_historical_evidence():
    index = PublicKnowledgeIndex()
    historical = index.search(QUESTION, top_k=1, version="3.4.2", language="all")[0]
    with TestClient(create_app(index=index, generator=object())) as client:
        unknown = client.post("/public/review-advice", json={
            "change_summary": "假设变更", "evidence_chunk_ids": ["invented-chunk"],
        })
        old_version = client.post("/public/review-advice", json={
            "change_summary": "假设变更", "evidence_chunk_ids": [historical["chunk_id"]],
        })

    assert unknown.status_code == 422
    assert old_version.status_code == 422


def test_public_review_advice_allows_explicit_historical_version_bound_to_evidence(tmp_path):
    index = PublicKnowledgeIndex(root=AUTOWARE_CORPUS)
    hit = index.search("planning validator trajectory", top_k=1, version="0.51.0", language="all")[0]
    captured = []
    sidecar, lock = _write_empty_figure_sidecar(AUTOWARE_CORPUS, tmp_path)

    class Generator:
        def generate_review(self, *, change_summary, context):
            captured.append(context)
            return {
                "change_interpretation": "Review the historical planner behavior.",
                "impact_candidates": [{
                    "evidence_chunk_id": hit["chunk_id"], "reason": "Historical evidence.",
                    "suggested_action": "Compare against the current release.",
                }],
                "evidence_gaps": [], "version_ambiguities": [],
                "reviewer_actions": ["Confirm the intended target version."],
                "review_status": "REQUIRES_HUMAN_REVIEW",
            }

    with TestClient(create_app(
        index=index, generator=Generator(),
        retrieval_config_path=AUTOWARE_CORPUS / "public_retrieval_runtime.json",
        figure_sidecar_path=sidecar, figure_sidecar_lock_path=lock,
    )) as client:
        response = client.post("/public/review-advice", json={
            "change_summary": "Review historical validator behavior.",
            "evidence_chunk_ids": [hit["chunk_id"]], "version": "0.51.0",
        })

    assert response.status_code == 200
    assert response.json()["status"] == "OK"
    assert response.json()["evidence"][0]["version"] == "0.51.0"
    assert "0.51.0" in captured[0]


def test_public_review_advice_without_generator_returns_evidence_only():
    index = PublicKnowledgeIndex()
    hit = index.search(QUESTION, top_k=1, version="3.4.3", language="all")[0]
    with TestClient(create_app(index=index)) as client:
        response = client.post("/public/review-advice", json={
            "change_summary": "假设变更", "evidence_chunk_ids": [hit["chunk_id"]],
        })

    assert response.status_code == 200
    assert response.json()["status"] == "GENERATION_NOT_CONFIGURED"
    assert response.json()["answer"] == "N/A"
    assert response.json()["sources"] == []
    assert response.json()["evidence"][0]["chunk_id"] == hit["chunk_id"]
