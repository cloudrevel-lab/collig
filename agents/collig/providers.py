"""
config.json -> ADK model resolution.

Every provider Collig supported under LangChain goes through LiteLLM here, so
adding one is a table entry rather than a new client class. Behaviour is a
straight port of the old ``Agent._init_langchain_agent`` provider block:
same env-then-config key lookup, same DashScope endpoint map, same fallback
to OpenAI for an unknown provider name.
"""
from typing import Any, Dict, Optional, Tuple

from google.adk.models.lite_llm import LiteLlm

from core.runtime import (
    default_model_for,
    get_api_key,
    get_provider_model,
    load_config,
)

# DashScope's OpenAI-compatible endpoints, keyed by the DASHSCOPE_ENDPOINT
# config value. "singapore" and "international" are the same host.
DASHSCOPE_ENDPOINTS = {
    "china": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "singapore": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "international": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
}

DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# Which credential each provider needs. Ollama runs locally and needs none.
PROVIDER_KEY_NAMES = {
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "dashscope": "DASHSCOPE_API_KEY",
    # "custom" is OpenAI-compatible but the key is optional (local servers),
    # so it is handled explicitly in resolve_model rather than requiring a key.
}


class ProviderError(RuntimeError):
    """Raised when a provider is selected but cannot be used (missing key)."""


def dashscope_base_url(config: Optional[Dict[str, Any]] = None) -> str:
    """The DashScope endpoint for the configured region (default: china)."""
    if config is None:
        config = load_config()
    region = config.get("DASHSCOPE_ENDPOINT", "china")
    return DASHSCOPE_ENDPOINTS.get(region, DASHSCOPE_ENDPOINTS["china"])


def resolve_model(provider: Optional[str] = None, model: Optional[str] = None) -> LiteLlm:
    """
    Build the ``LiteLlm`` for a provider/model pair.

    Both arguments default to what config.json says. Raises ``ProviderError``
    when the provider needs a key that is not configured -- the caller decides
    whether that is fatal, because the CLI still wants to start up and let the
    user run ``config set OPENAI_API_KEY``.
    """
    config = load_config()
    cfg_provider, cfg_model = get_provider_model(config)
    provider = (provider or cfg_provider).lower()
    model = model or cfg_model

    if provider == "custom":
        # Generic OpenAI-compatible endpoint. base_url is required; the key is
        # optional (local servers often accept any value).
        base_url = get_api_key("CUSTOM_BASE_URL", config)
        if not base_url:
            raise ProviderError(
                "CUSTOM_BASE_URL not found. Set it with 'config set CUSTOM_BASE_URL <url>'."
            )
        api_key = get_api_key("CUSTOM_API_KEY", config) or "not-needed"
        return LiteLlm(model=f"openai/{model}", api_key=api_key, api_base=base_url)

    if provider not in PROVIDER_KEY_NAMES and provider not in ("ollama", "llama"):
        # Unknown provider: same fallback the LangChain agent used.
        provider = "openai"
        model = default_model_for(provider)

    if provider in ("ollama", "llama"):
        # LiteLLM's ollama_chat/* route uses the /api/chat endpoint, which is
        # the one that supports tool calling; plain ollama/* does not.
        return LiteLlm(model=f"ollama_chat/{model}")

    key_name = PROVIDER_KEY_NAMES[provider]
    api_key = get_api_key(key_name, config)
    if not api_key:
        raise ProviderError(
            f"{key_name} not found. Set it with 'config set {key_name} <key>'."
        )

    if provider == "openai":
        return LiteLlm(model=f"openai/{model}", api_key=api_key)

    if provider == "deepseek":
        # OpenAI-compatible API, so route it through the openai/ prefix with
        # an explicit base rather than LiteLLM's deepseek/ provider, which
        # would insist on reading DEEPSEEK_API_KEY from the environment.
        return LiteLlm(model=f"openai/{model}", api_key=api_key, api_base=DEEPSEEK_BASE_URL)

    # dashscope
    if model in (None, "", "gpt-4o"):
        # A leftover OpenAI model name would 404 against DashScope.
        model = default_model_for("dashscope")
    return LiteLlm(
        model=f"openai/{model}", api_key=api_key, api_base=dashscope_base_url(config)
    )


def describe_provider(provider: Optional[str] = None,
                      model: Optional[str] = None) -> Tuple[str, str]:
    """Return the (provider, model) that ``resolve_model`` would actually use."""
    cfg_provider, cfg_model = get_provider_model()
    provider = (provider or cfg_provider).lower()
    model = model or cfg_model or default_model_for(provider)
    if provider == "custom":
        return provider, (model or "gpt-4o")
    if provider not in PROVIDER_KEY_NAMES and provider not in ("ollama", "llama"):
        provider = "openai"
        model = default_model_for(provider)
    elif provider == "dashscope" and model in (None, "", "gpt-4o"):
        model = default_model_for("dashscope")
    return provider, model


def list_available_models() -> str:
    """Human-readable catalogue of providers and models, for the CLI."""
    output = []

    output.append("[bold cyan]dashscope (阿里云)[/bold cyan]:")
    output.append("  - qwen-plus (recommended)")
    output.append("  - qwen-max")
    output.append("  - qwen-turbo")
    output.append("  - qwen-long")
    output.append("  Endpoint: China (https://dashscope.aliyuncs.com)")
    output.append("  Endpoint: Singapore/International (https://dashscope-intl.aliyuncs.com)")

    output.append("\n[bold cyan]deepseek[/bold cyan]:")
    output.append("  - deepseek-chat (V3)")
    output.append("  - deepseek-reasoner (R1)")

    output.append("\n[bold cyan]openai[/bold cyan]:")
    output.append("  - gpt-4o")
    output.append("  - gpt-4o-mini")
    output.append("  - gpt-3.5-turbo")

    output.append("\n[bold cyan]ollama[/bold cyan]:")
    try:
        import subprocess
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n")[1:]:  # skip header
                parts = line.split()
                if parts:
                    output.append(f"  - {parts[0]}")
        else:
            output.append("  (Error listing Ollama models)")
    except Exception as e:
        output.append(f"  (Ollama not found or error: {e})")

    output.append("\n[bold cyan]llama (alias for ollama)[/bold cyan]:")
    output.append("  (Use 'ollama' provider instead)")

    output.append("\n[bold cyan]custom (OpenAI-compatible endpoint)[/bold cyan]:")
    _cfg = load_config()
    _custom_url = get_api_key("CUSTOM_BASE_URL", _cfg)
    if _custom_url:
        output.append(f"  Endpoint: {_custom_url}")
    else:
        output.append("  Endpoint: (not set - run 'config set CUSTOM_BASE_URL <url>')")
    output.append("  Set the model with LLM_MODEL; API key CUSTOM_API_KEY is optional")

    return "\n".join(output)
