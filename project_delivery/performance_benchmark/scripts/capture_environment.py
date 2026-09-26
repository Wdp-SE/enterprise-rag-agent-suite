"""Capture benchmark environment facts from the current machine."""

from __future__ import annotations

import ctypes
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from benchmark_utils import read_json, utc_now, write_json


SCRIPT_DIR = Path(__file__).resolve().parent
BENCHMARK_ROOT = SCRIPT_DIR.parent
WORKSPACE = BENCHMARK_ROOT.parents[1]
RAG_ROOT = WORKSPACE / "versioned-rag-service"
AGENT_ROOT = WORKSPACE / "change-review-agent"


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def cpu_name() -> str:
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as key:
                return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        except OSError:
            pass
    return platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", "unknown")


def ram_bytes() -> int | None:
    if os.name == "nt":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("memory_load", ctypes.c_ulong),
                ("total_physical", ctypes.c_ulonglong),
                ("available_physical", ctypes.c_ulonglong),
                ("total_page_file", ctypes.c_ulonglong),
                ("available_page_file", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong),
                ("available_virtual", ctypes.c_ulonglong),
                ("available_extended_virtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.total_physical)
    return None



def windows_os_facts() -> dict:
    if os.name != "nt":
        return {"caption": platform.system(), "version": platform.version(), "build": None}
    command = (
        "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); "
        "Get-CimInstance Win32_OperatingSystem | "
        "Select-Object Caption,Version,BuildNumber | ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
    )
    value = json.loads(completed.stdout.strip())
    return {"caption": value["Caption"], "version": value["Version"], "build": value["BuildNumber"]}


def agent_environment() -> dict:
    executable = AGENT_ROOT / ".venv" / "Scripts" / "python.exe"
    code = (
        "import importlib.metadata,json,sys;"
        "print(json.dumps({'python_version':sys.version,'executable':sys.executable,"
        "'python_docx':importlib.metadata.version('python-docx'),"
        "'pydantic':importlib.metadata.version('pydantic'),"
        "'httpx':importlib.metadata.version('httpx')}))"
    )
    completed = subprocess.run(
        [str(executable), "-c", code],
        cwd=AGENT_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(completed.stdout)


def main() -> int:
    sys.path.insert(0, str(RAG_ROOT))
    from src.rd_v2_runtime import (
        FINAL_DENSE_REPRESENTATION,
        FINAL_RETRIEVAL_POLICY,
        FrozenArtifactValidator,
        RDV2Settings,
        _discover_snapshot,
    )

    settings = RDV2Settings.from_env(RAG_ROOT)
    bundle = FrozenArtifactValidator(settings).validate_and_load()
    snapshot = settings.embedding_snapshot or _discover_snapshot(bundle.manifest)
    fixture = read_json(BENCHMARK_ROOT / "fixtures" / "agent_workflow.json")
    local_now = datetime.now().astimezone()
    os_facts = windows_os_facts()
    payload = {
        "schema_version": 1,
        "captured_at": utc_now(),
        "benchmark_date_local": local_now.date().isoformat(),
        "benchmark_timezone": str(local_now.tzinfo),
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=WORKSPACE, text=True, encoding="utf-8"
        ).strip(),
        "machine": {
            "os_caption": os_facts["caption"],
            "os_version": os_facts["version"],
            "os_build": os_facts["build"],
            "python_platform": platform.platform(),
            "cpu": cpu_name(),
            "logical_cpu_count": os.cpu_count(),
            "ram_bytes": ram_bytes(),
        },
        "rag_environment": {
            "python_version": sys.version,
            "executable": sys.executable,
            "pytorch_version": package_version("torch"),
            "faiss_version": package_version("faiss-cpu") or package_version("faiss"),
            "transformers_version": package_version("transformers"),
            "numpy_version": package_version("numpy"),
            "embedding_model": bundle.manifest["embedding_model"],
            "embedding_model_revision": bundle.manifest["embedding_model_revision"],
            "embedding_model_snapshot": str(snapshot) if snapshot else None,
            "embedding_model_snapshot_exists": bool(snapshot and snapshot.is_dir()),
            "embedding_dimension": int(bundle.manifest["embedding_dimension"]),
            "retrieval_policy": FINAL_RETRIEVAL_POLICY,
            "dense_representation": FINAL_DENSE_REPRESENTATION,
            "corpus_document_count": len(bundle.catalog.documents),
            "corpus_version_count": len(bundle.catalog.versions),
            "corpus_chunk_count": len(bundle.chunks),
            "top_k": settings.final_top_k,
            "dense_top_k": settings.dense_top_k,
            "llm_provider": "dashscope configured but disabled by data policy",
            "online_model_calls": False,
            "local_embedding_model": True,
        },
        "agent_environment": {
            **agent_environment(),
            "template": fixture["template_name"],
            "section_count": len(fixture["sections"]),
            "field_count": len(fixture["sections"]),
            "drafting_mode": "EXTRACTIVE",
            "llm_provider": None,
            "llm_calls": 0,
            "online_model_calls": False,
            "local_model": False,
        },
        "methodology": {
            "latency_warmup_runs": 5,
            "latency_measured_runs": 30,
            "incremental_independent_runs": 5,
            "warm_cache": "reported per benchmark; retrieval uses a warm process/model after explicit warm-up",
            "network": "loopback HTTP only for /retrieve; no external network",
            "data_policy": "synthetic plus approved local frozen corpus",
        },
    }
    write_json(BENCHMARK_ROOT / "benchmark_environment.json", payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
