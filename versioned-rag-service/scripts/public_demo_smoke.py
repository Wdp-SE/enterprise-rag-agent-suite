"""Read-only health and version-aware retrieval smoke for a deployed RAG URL."""

from __future__ import annotations

import argparse
import json

import requests


def run(base_url: str, *, timeout: float = 45.0) -> dict:
    base_url = base_url.rstrip("/")
    health_response = requests.get(f"{base_url}/health", timeout=timeout)
    health_response.raise_for_status()
    health = health_response.json()
    if health.get("service_status") != "READY" or health.get("artifact_status") != "COMPLETE":
        raise RuntimeError("PUBLIC_RAG_NOT_READY")

    payload = {
        "query": "审计日志在线保存周期是多少天",
        "top_k": 5,
        "scope": {"project_ids": ["AUDIT"], "active_only": True},
    }
    retrieval_response = requests.post(
        f"{base_url}/retrieve",
        json=payload,
        timeout=timeout,
    )
    retrieval_response.raise_for_status()
    retrieval = retrieval_response.json()
    results = retrieval.get("results")
    if not results or results[0].get("version_status") != "ACTIVE":
        raise RuntimeError("CURRENT_VERSION_RETRIEVAL_FAILED")
    return {
        "health": {
            "service_status": health["service_status"],
            "artifact_status": health["artifact_status"],
        },
        "retrieval": {
            "result_count": len(results),
            "top_version_id": results[0]["version_id"],
            "top_version_status": results[0]["version_status"],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--timeout", type=float, default=45.0)
    arguments = parser.parse_args()
    print(json.dumps(run(arguments.base_url, timeout=arguments.timeout), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
