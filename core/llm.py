"""
Small, provider-agnostic chat-completion helper for background features.

The main conversation runs through ADK/LiteLlm (``agents/collig/providers.py``).
A few features need a plain "one prompt in, text out" call that is not part of
the agent turn: memory extraction and ``/distill``.  They do not need tools,
sessions or streaming, so going through ``litellm.completion`` directly keeps
them independent of ADK's runner and cheap to call from a worker thread.

Provider/model/key resolution deliberately reuses ``core.runtime`` so these
calls always use exactly the endpoint the user configured, including a custom
OpenAI-compatible server or local Ollama.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# A background call must never hang a turn or a CLI command forever.
DEFAULT_TIMEOUT = 60


class LLMError(RuntimeError):
    """Raised when the configured provider cannot be used or the call fails."""


def _resolve(config: Optional[Dict[str, Any]] = None):
    """Return ``(litellm_model, extra_kwargs)`` for the configured provider."""
    from core.runtime import default_model_for, get_llm_config

    cfg = get_llm_config(config)
    provider = str(cfg.get("provider") or "openai").lower()
    model = str(cfg.get("llm_model") or default_model_for(provider))
    api_key = str(cfg.get("api_key") or "")
    base_url = str(cfg.get("provider_url") or "")

    if provider in ("ollama", "llama"):
        # ollama_chat/* is the route that supports the /api/chat endpoint.
        return f"ollama_chat/{model}", {"api_base": base_url or "http://localhost:11434"}

    if provider == "custom":
        if not base_url:
            raise LLMError(
                "CUSTOM_BASE_URL is not set. Configure the custom endpoint with " "'config set CUSTOM_BASE_URL <url>'."
            )
        return f"openai/{model}", {
            "api_base": base_url,
            "api_key": api_key or "not-needed",
        }

    if provider not in ("openai", "deepseek", "dashscope"):
        # Match providers.resolve_model: an unknown provider falls back to
        # OpenAI rather than failing in a confusing LiteLLM way.
        provider = "openai"
        model = default_model_for(provider)

    if not api_key:
        env_name = {
            "openai": "OPENAI_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "dashscope": "DASHSCOPE_API_KEY",
        }.get(provider, "OPENAI_API_KEY")
        raise LLMError(f"{env_name} is not set. Configure it and try again.")

    kwargs: Dict[str, Any] = {"api_key": api_key}
    if base_url:
        kwargs["api_base"] = base_url
    return f"openai/{model}", kwargs


def is_configured(config: Optional[Dict[str, Any]] = None) -> bool:
    """True when a provider/model/key combination appears usable."""
    try:
        _resolve(config)
        return True
    except Exception:
        return False


def describe(config: Optional[Dict[str, Any]] = None) -> str:
    """Human-readable provider/model label, without secrets."""
    try:
        from core.runtime import get_provider_model

        provider, model = get_provider_model(config)
        return f"{provider}/{model}"
    except Exception:
        return "unknown"


def complete(
    messages: List[Dict[str, str]],
    *,
    temperature: float = 0.3,
    max_tokens: int = 1200,
    timeout: int = DEFAULT_TIMEOUT,
    config: Optional[Dict[str, Any]] = None,
    response_format: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Run one non-streaming chat completion and return the assistant text.

    Raises :class:`LLMError` for a missing key, an unreachable endpoint or an
    empty/malformed response, so callers can degrade gracefully instead of
    surfacing a stack trace to the user.
    """
    if not messages:
        return ""

    model, kwargs = _resolve(config)
    try:
        import litellm
    except ImportError as exc:  # pragma: no cover - litellm ships with google-adk
        raise LLMError("LiteLLM is not installed; cannot run a background LLM call.") from exc

    # Providers disagree on optional parameters (e.g. some reject `timeout`),
    # and LiteLLM's drop_params handles that instead of each call site.
    try:
        litellm.drop_params = True
    except Exception:
        pass

    request = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "timeout": timeout,
    }
    if response_format is not None:
        # Providers that support JSON mode return `content` as JSON instead of
        # spending the whole completion budget on reasoning.  LiteLLM's
        # drop_params removes it for providers that do not support it.
        request["response_format"] = response_format
    request.update(kwargs)

    try:
        response = litellm.completion(**request)
    except Exception as exc:  # LiteLLM raises provider-specific exception types
        # Some endpoints reject JSON mode even with drop_params.  Retry once
        # without it rather than failing the whole /distill.
        if response_format is not None:
            request.pop("response_format", None)
            try:
                response = litellm.completion(**request)
            except Exception as retry_exc:
                logger.debug("Background LLM call failed", exc_info=True)
                raise LLMError(f"{type(retry_exc).__name__}: {retry_exc}") from retry_exc
        else:
            logger.debug("Background LLM call failed", exc_info=True)
            raise LLMError(f"{type(exc).__name__}: {exc}") from exc

    try:
        message = response.choices[0].message
    except Exception as exc:
        raise LLMError("The model returned an empty response.") from exc

    content = getattr(message, "content", None)
    if isinstance(content, list):
        # Some providers return typed content blocks instead of a string.
        content = "".join(str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in content)
    text = str(content or "").strip()
    if not text:
        # Reasoning models occasionally put everything in reasoning_content.
        text = str(getattr(message, "reasoning_content", "") or "").strip()
    if not text:
        raise LLMError("The model returned no text.")
    return text


_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> Any:
    """
    Parse JSON out of a model response, tolerating fences and prose.

    Returns ``None`` when no valid JSON object/array can be found.  Used by the
    memory extractor, where a malformed response must not break a turn.
    """
    import json

    if not text:
        return None
    candidates: List[str] = []
    stripped = text.strip()
    candidates.append(stripped)
    for match in _FENCE_RE.finditer(text):
        candidates.append(match.group(1).strip())

    # Fall back to the widest {...} / [...] span in the response.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            candidates.append(text[start : end + 1].strip())  # noqa: E203

    for candidate in candidates:
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except Exception:
            continue
    return None
