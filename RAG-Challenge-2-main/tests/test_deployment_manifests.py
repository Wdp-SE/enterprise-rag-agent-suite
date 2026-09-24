from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_deployment_manifests_use_public_profile_and_lightweight_dependencies() -> None:
    render = (ROOT / "render.yaml").read_text(encoding="utf-8")
    assert "RAG-Challenge-2-main" in render
    assert "uvicorn src.public_server:app --host 0.0.0.0 --port $PORT" in render
    assert "APP_ENV" in render and "public_demo" in render
    requirements = (
        ROOT / "RAG-Challenge-2-main/requirements-render.txt"
    ).read_text(encoding="utf-8").casefold()
    for forbidden in ("torch", "transformers", "pytest", "notebook"):
        assert forbidden not in requirements
    ui_requirements = (ROOT / "demo-ui/requirements.txt").read_text(encoding="utf-8")
    for required in ("streamlit", "requests", "pydantic", "httpx", "python-docx"):
        assert required in ui_requirements


def test_public_smoke_is_read_only_and_example_secrets_are_placeholders() -> None:
    smoke = (
        ROOT / "RAG-Challenge-2-main/scripts/public_demo_smoke.py"
    ).read_text(encoding="utf-8")
    assert "/health" in smoke
    assert "/retrieve" in smoke
    for forbidden in ("/query", "/engineering/candidates", "activate", "publish"):
        assert forbidden not in smoke
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "RAG_API_BASE_URL=https://<render-service>" in example
    assert "DASHSCOPE_API_KEY=<set-in-platform-secret-store>" in example
