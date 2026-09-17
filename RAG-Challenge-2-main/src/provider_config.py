"""Provider/model configuration shared by answer, embedding and rerank paths."""

from typing import Optional


SUPPORTED_PROVIDERS = {"openai", "dashscope", "gemini", "ibm"}
SUPPORTED_CAPABILITIES = {"answer", "embedding", "rerank"}

DEFAULT_MODELS = {
    "answer": {
        "openai": "gpt-4o-2024-08-06",
        "dashscope": "qwen-turbo",
        "gemini": "gemini-2.0-flash-001",
        "ibm": "meta-llama/llama-3-3-70b-instruct",
    },
    "embedding": {
        "openai": "text-embedding-3-large",
        "dashscope": "text-embedding-v1",
    },
    "rerank": {
        "openai": "gpt-4o-mini-2024-07-18",
        "dashscope": "qwen-turbo",
    },
}


def normalize_provider(provider: str) -> str:
    """Return a normalized provider name or raise a clear configuration error."""
    normalized = (provider or "").strip().lower()
    if normalized not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Unsupported provider '{provider}'. Expected one of: "
            f"{', '.join(sorted(SUPPORTED_PROVIDERS))}."
        )
    return normalized


def _model_matches_provider(provider: str, model: str, capability: str) -> bool:
    model_lower = model.lower()

    if capability == "embedding":
        if provider == "openai":
            return model_lower.startswith(("text-embedding-3", "text-embedding-ada"))
        if provider == "dashscope":
            return model_lower.startswith("text-embedding-v")
        return False

    if capability == "rerank" and provider not in {"openai", "dashscope"}:
        return False

    if provider == "openai":
        return model_lower.startswith(("gpt-", "o1", "o3", "o4"))
    if provider == "dashscope":
        return model_lower.startswith("qwen-")
    if provider == "gemini":
        return capability == "answer" and model_lower.startswith("gemini-")
    if provider == "ibm":
        return capability == "answer" and model_lower.startswith(("meta-llama/", "ibm/"))
    return False


def resolve_provider_model(
    provider: str,
    model: Optional[str],
    capability: str,
) -> tuple[str, str]:
    """Resolve defaults and reject known provider/model mismatches before an API call."""
    provider = normalize_provider(provider)
    capability = (capability or "").strip().lower()
    if capability not in SUPPORTED_CAPABILITIES:
        raise ValueError(
            f"Unsupported capability '{capability}'. Expected one of: "
            f"{', '.join(sorted(SUPPORTED_CAPABILITIES))}."
        )

    provider_defaults = DEFAULT_MODELS[capability]
    if provider not in provider_defaults:
        raise ValueError(f"Provider '{provider}' does not support capability '{capability}'.")

    resolved_model = (model or provider_defaults[provider]).strip()
    if not _model_matches_provider(provider, resolved_model, capability):
        raise ValueError(
            f"Model '{resolved_model}' is not valid for provider '{provider}' "
            f"and capability '{capability}'."
        )
    return provider, resolved_model
