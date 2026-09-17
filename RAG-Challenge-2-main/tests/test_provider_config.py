import pytest

from src.api_requests import APIProcessor
from src.provider_config import resolve_provider_model


@pytest.mark.parametrize(
    "provider,model,capability",
    [
        ("dashscope", "gpt-4o-2024-08-06", "answer"),
        ("openai", "qwen-turbo", "answer"),
        ("dashscope", "text-embedding-3-large", "embedding"),
        ("openai", "text-embedding-v1", "embedding"),
    ],
)
def test_provider_model_mismatch_is_rejected(provider, model, capability):
    with pytest.raises(ValueError, match="not valid"):
        resolve_provider_model(provider, model, capability)


def test_invalid_model_is_rejected_before_provider_call(monkeypatch):
    processor = APIProcessor(provider="dashscope")
    called = False

    def fake_provider_call(**kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(processor.processor, "send_message", fake_provider_call)

    with pytest.raises(ValueError, match="not valid"):
        processor.send_message(model="gpt-4o-2024-08-06")
    assert called is False


@pytest.mark.parametrize(
    "provider,model,capability",
    [
        ("dashscope", "qwen-turbo-latest", "answer"),
        ("openai", "gpt-4o-2024-08-06", "answer"),
        ("dashscope", "text-embedding-v1", "embedding"),
        ("openai", "text-embedding-3-large", "embedding"),
    ],
)
def test_valid_provider_model_pairs(provider, model, capability):
    assert resolve_provider_model(provider, model, capability) == (provider, model)

