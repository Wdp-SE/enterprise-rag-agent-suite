"""Benchmark the frozen DENSE_ONLY /retrieve API over loopback HTTP."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

from benchmark_utils import read_json, stats, utc_now, write_json


SCRIPT_DIR = Path(__file__).resolve().parent
BENCHMARK_ROOT = SCRIPT_DIR.parent
WORKSPACE = BENCHMARK_ROOT.parents[1]
RAG_ROOT = WORKSPACE / "RAG-Challenge-2-main"
RUNTIME_ROOT = BENCHMARK_ROOT / "runtime" / "rag_retrieval"
OUTPUT = BENCHMARK_ROOT / "rag_retrieval_benchmark.json"
WARMUP_ROUNDS = 5
MEASURED_ROUNDS = 30


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request_json(url: str, *, payload: dict | None = None, timeout: float = 180.0) -> tuple[dict, float]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
        if response.status != 200:
            raise RuntimeError(f"unexpected HTTP status: {response.status}")
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return json.loads(body.decode("utf-8")), elapsed_ms


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT)
            process.wait(timeout=30)
            return
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=30)
            return
        except subprocess.TimeoutExpired:
            pass
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def validate_response(payload: dict, query: str, top_k: int, scope: dict) -> None:
    if payload.get("query") != query or not isinstance(payload.get("results"), list):
        raise AssertionError("malformed /retrieve response")
    results = payload["results"]
    if not results or len(results) > top_k:
        raise AssertionError("/retrieve returned an invalid result count")
    allowed_documents = set(scope.get("document_ids") or [])
    allowed_versions = set(scope.get("version_ids") or [])
    for expected_rank, item in enumerate(results, start=1):
        if item.get("rank") != expected_rank:
            raise AssertionError("rank sequence changed")
        if allowed_documents and item.get("document_id") not in allowed_documents:
            raise AssertionError("document scope was violated")
        if allowed_versions and item.get("version_id") not in allowed_versions:
            raise AssertionError("version scope was violated")
        if scope.get("active_only", True) and item.get("version_status") != "ACTIVE":
            raise AssertionError("active-only retrieval returned a non-ACTIVE version")


def main() -> int:
    query_fixture = read_json(BENCHMARK_ROOT / "fixtures" / "retrieval_queries.json")
    queries = list(query_fixture["queries"])
    top_k = int(query_fixture["top_k"])
    if not 10 <= len(queries) <= 20:
        raise ValueError("query set must contain 10-20 questions")

    sys.path.insert(0, str(RAG_ROOT))
    from src.document_lifecycle import RetrievalScope
    from src.rd_v2_runtime import (
        FINAL_DENSE_REPRESENTATION,
        FINAL_RETRIEVAL_POLICY,
        FrozenArtifactValidator,
        RDV2Settings,
    )

    settings = RDV2Settings.from_env(RAG_ROOT)
    bundle = FrozenArtifactValidator(settings).validate_and_load()
    documents = sorted(bundle.catalog.documents, key=lambda item: item.document_id)
    chunk_counts = {
        document.document_id: sum(
            chunk.get("document_id") == document.document_id for chunk in bundle.chunks
        )
        for document in documents
    }
    single_document = min(chunk_counts, key=chunk_counts.get)
    multi_documents = sorted(chunk_counts, key=chunk_counts.get)[:2]
    scenarios = {
        "all_active": {"active_only": True},
        "single_document": {"active_only": True, "document_ids": [single_document]},
        "multi_document": {"active_only": True, "document_ids": multi_documents},
    }
    candidate_counts = {
        name: sum(
            bundle.catalog.matches(chunk, RetrievalScope.model_validate(scope))
            for chunk in bundle.chunks
        )
        for name, scope in scenarios.items()
    }
    if min(candidate_counts.values()) < top_k:
        raise AssertionError("a benchmark scope has fewer candidates than top_k")

    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    log_path = RUNTIME_ROOT / "uvicorn.log"
    environment = os.environ.copy()
    environment.update(
        {
            "RD_V2_PROJECT_ROOT": str(RAG_ROOT),
            "RD_V2_ALLOW_EXTERNAL_GENERATION": "false",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    start = time.perf_counter()
    log_handle = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "src.rd_v2_api:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=RAG_ROOT,
        env=environment,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        creationflags=creation_flags,
    )
    try:
        deadline = time.monotonic() + 180
        health = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"RAG service exited early with code {process.returncode}")
            try:
                health, _ = request_json(f"{base_url}/health", timeout=2)
                break
            except (OSError, urllib.error.URLError, TimeoutError):
                time.sleep(0.05)
        if health is None:
            raise TimeoutError("RAG service did not become healthy")
        health_ready_ms = (time.perf_counter() - start) * 1000.0
        if (
            health.get("artifact_status") != "COMPLETE"
            or health.get("retrieval_policy") != FINAL_RETRIEVAL_POLICY
            or health.get("dense_representation") != FINAL_DENSE_REPRESENTATION
        ):
            raise AssertionError("RAG health contract changed")

        first_payload = {
            "query": queries[0]["question"],
            "top_k": top_k,
            "scope": scenarios["all_active"],
        }
        first_response, first_retrieve_ms = request_json(
            f"{base_url}/retrieve", payload=first_payload
        )
        validate_response(
            first_response,
            queries[0]["question"],
            top_k,
            scenarios["all_active"],
        )
        first_retrieve_ready_ms = (time.perf_counter() - start) * 1000.0

        warmup_count = defaultdict(int)
        for _ in range(WARMUP_ROUNDS):
            for scenario_name, scope in scenarios.items():
                for query in queries:
                    response, _ = request_json(
                        f"{base_url}/retrieve",
                        payload={"query": query["question"], "top_k": top_k, "scope": scope},
                    )
                    validate_response(response, query["question"], top_k, scope)
                    warmup_count[scenario_name] += 1

        samples: dict[str, list[float]] = defaultdict(list)
        per_query: dict[str, dict[str, list[float]]] = {
            scenario: defaultdict(list) for scenario in scenarios
        }
        result_counts: dict[str, set[int]] = defaultdict(set)
        for _ in range(MEASURED_ROUNDS):
            for scenario_name, scope in scenarios.items():
                for query in queries:
                    response, elapsed_ms = request_json(
                        f"{base_url}/retrieve",
                        payload={"query": query["question"], "top_k": top_k, "scope": scope},
                    )
                    validate_response(response, query["question"], top_k, scope)
                    samples[scenario_name].append(elapsed_ms)
                    per_query[scenario_name][query["id"]].append(elapsed_ms)
                    result_counts[scenario_name].add(len(response["results"]))

        scenario_results = {}
        for name, scope in scenarios.items():
            scenario_results[name] = {
                "scope": scope,
                "candidate_vector_count": candidate_counts[name],
                "warmup_request_count": warmup_count[name],
                "measured_request_count": len(samples[name]),
                "latency_ms": stats(samples[name]),
                "per_query_latency_ms": {
                    query_id: stats(values) for query_id, values in per_query[name].items()
                },
                "observed_result_counts": sorted(result_counts[name]),
                "correctness": "PASS",
            }
        payload = {
            "schema_version": 1,
            "benchmark": "RAG /retrieve absolute latency",
            "captured_at": utc_now(),
            "status": "PASS",
            "data_policy": "approved local frozen corpus; no external transmission",
            "online_models_called": False,
            "transport": "loopback HTTP",
            "retrieval_policy": FINAL_RETRIEVAL_POLICY,
            "dense_representation": FINAL_DENSE_REPRESENTATION,
            "top_k": top_k,
            "query_count": len(queries),
            "query_categories": sorted({query["category"] for query in queries}),
            "warmup_rounds": WARMUP_ROUNDS,
            "measured_rounds": MEASURED_ROUNDS,
            "cold_start": {
                "sample_count": 1,
                "process_start_to_health_ready_ms": round(health_ready_ms, 3),
                "health_ready_to_first_retrieve_ms": round(first_retrieve_ms, 3),
                "process_start_to_first_retrieve_ready_ms": round(first_retrieve_ready_ms, 3),
                "note": "first retrieve includes local embedding worker/model startup",
            },
            "scenarios": scenario_results,
            "historical_version_scope": {
                "status": "NOT_APPLICABLE_TO_FROZEN_CORPUS",
                "reason": "the frozen artifact contains one ACTIVE version per document and no SUPERSEDED version",
            },
            "correctness": {
                "active_default_excludes_superseded": "PASS",
                "single_document_membership": "PASS",
                "multi_document_membership": "PASS",
                "top_k_and_rank_contract": "PASS",
            },
        }
        write_json(OUTPUT, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    finally:
        stop_process(process)
        log_handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
