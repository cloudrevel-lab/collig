"""
Shared runtime state for Collig.

Both surfaces -- the Rich CLI (via ``core.runner``) and the ADK agent
(``agents/collig``) -- import this module, so they share one ``SkillManager``
and one view of ``config.json``. That matters: toggling a skill in the CLI
has to change which tools the running agent offers, and switching provider in
the admin API has to be visible to the CLI's ``/provider`` command.

Kept deliberately cheap to import. Registering the skills pulls in Playwright,
ChromaDB and the rest, so that only happens on the first
``get_skill_manager()`` call, not at import time.
"""
import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.paths import paths

# Repo root -- SkillLoader used to be handed the relative string "skills",
# which silently loaded nothing unless the process happened to start in the
# repo root. `adk web agents` and the FastAPI server do not guarantee that.
REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_MODELS = {
    "openai": "gpt-4o",
    "deepseek": "deepseek-chat",
    "dashscope": "qwen-plus",
    "ollama": "qwen3:8b",
    "llama": "llama3.1",  # llama3.1 rather than qwen3, since it supports tools
}


# --------------------------------------------------------------------------
# config.json
# --------------------------------------------------------------------------

def load_config() -> Dict[str, Any]:
    """Read ``~/.collig/config.json``, returning {} if it is missing or bad."""
    try:
        with open(paths.global_config_file, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(config: Dict[str, Any]) -> None:
    """Write ``~/.collig/config.json``."""
    os.makedirs(os.path.dirname(paths.global_config_file), exist_ok=True)
    with open(paths.global_config_file, "w") as f:
        json.dump(config, f, indent=2)


def update_config(**values: Any) -> Dict[str, Any]:
    """Merge ``values`` into config.json and return the merged config."""
    config = load_config()
    config.update(values)
    save_config(config)
    return config


def get_api_key(env_var_name: str, config: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """
    Look up a credential: environment first, then config.json.

    Same precedence the LangChain agent used, so a shell export keeps
    overriding a saved key.
    """
    key = os.getenv(env_var_name)
    if key:
        return key
    if config is None:
        config = load_config()
    return config.get(env_var_name)


def get_provider_model(config: Optional[Dict[str, Any]] = None) -> tuple:
    """
    Resolve (provider, model) -- unified: new flat name -> legacy LLM_* -> env -> defaults.

    Precedence is OPPOSITE from ``get_api_key``: saved user choice wins over
    potentially-stale env var.  Delegates fully to ``get_llm_config``.
    """
    cfg = get_llm_config(config)
    return cfg["provider"], cfg["llm_model"]


def default_model_for(provider: str) -> str:
    """The model to fall back to when a provider is selected without one."""
    return DEFAULT_MODELS.get(provider.lower(), "gpt-4o")


# --------------------------------------------------------------------------
# Unified LLM config abstraction (no UI changes)
# --------------------------------------------------------------------------
#
# Maps logical LLM "fields" (provider/provider_url/llm_model/api_key/...) to
# their concrete on-disk LEGACY storage keys (env-var-style names like
# OPENAI_API_KEY / CUSTOM_BASE_URL / DASHSCOPE_ENDPOINT) for each provider.
#
# Writes go to BOTH the legacy storage key AND a new unified flat alias
# (provider / llm_model / provider_url / api_key / available_models) so reads
# from either style work going forward.  Reads prefer new flat aliases first,
# then legacy keys, then env vars, then defaults.

_PROVIDER_KEY_BINDINGS: Dict[str, Dict[str, Optional[str]]] = {
    "openai":    {"api_key": "OPENAI_API_KEY",    "provider_url": None},
    "deepseek":  {"api_key": "DEEPSEEK_API_KEY",  "provider_url": None},
    "ollama":    {"api_key": None,                "provider_url": None},
    "llama":     {"api_key": None,                "provider_url": None},
    "dashscope": {"api_key": "DASHSCOPE_API_KEY", "provider_url": "DASHSCOPE_ENDPOINT"},
    "custom":    {"api_key": "CUSTOM_API_KEY",    "provider_url": "CUSTOM_BASE_URL"},
}


def _bindings_for(provider: str) -> Dict[str, Optional[str]]:
    provider = (provider or "openai").lower()
    if provider in _PROVIDER_KEY_BINDINGS:
        return _PROVIDER_KEY_BINDINGS[provider]
    return {"api_key": None, "provider_url": None}


def get_llm_config(config: Optional[Dict[str, Any]] = None, *,
                   provider_scoped: bool = False) -> Dict[str, Any]:
    """
    Read the LLM section as a unified dict.

    Returns keys:  provider, provider_url, llm_model, api_key, available_models

    Precedence (applied per logical field):
      1. new flat unified alias in config.json (provider / llm_model / ...)
      2. legacy storage key corresponding to the active provider
         (e.g. DASHSCOPE_API_KEY when provider is dashscope)
      3. environment variable of that legacy key
      4. compile-time DEFAULT_MODELS fallback for model, None / [] for rest

    When ``provider_scoped=True`` (used by the /api/config/llm?provider=
    projection endpoint) we skip global fallbacks like ``LLM_MODEL`` /
    ``os.getenv("LLM_MODEL")`` — those are shared across providers and would
    leak the currently active model onto another provider's preview.
    """
    if config is None:
        config = load_config()

    # Provider: new flat alias -> legacy LLM_PROVIDER -> env -> default
    provider = (
        config.get("provider")
        or config.get("LLM_PROVIDER")
        or os.getenv("LLM_PROVIDER")
        or "openai"
    ).lower()

    bindings = _bindings_for(provider)

    # Provider URL
    # When projecting for another provider (provider_scoped=True) we skip the
    # flat unified alias (which holds the *currently active* provider's URL)
    # and instead read only from legacy provider-scoped keys / defaults.
    url_key = bindings["provider_url"]
    per_provider_url_key = f"{provider.upper()}_URL"
    if provider == "dashscope":
        # DASHSCOPE_ENDPOINT is a region ("china"/"singapore"), not a URL.
        if provider_scoped:
            provider_url = config.get(per_provider_url_key) or _dashscope_url(config)
        else:
            provider_url = (
                config.get("provider_url")
                or config.get(per_provider_url_key)
                or _dashscope_url(config)
            )
    elif provider_scoped:
        provider_url = (
            config.get(per_provider_url_key)
            or (config.get(url_key) if url_key else None)
            or (os.getenv(url_key) if url_key else "")
            or _PROVIDER_BASE_URLS.get(provider, "")
        )
    elif url_key is None:
        provider_url = (
            config.get("provider_url")
            or config.get(per_provider_url_key)
            or _PROVIDER_BASE_URLS.get(provider)
            or ""
        )
    else:
        provider_url = (
            config.get("provider_url")
            or config.get(url_key)
            or config.get(per_provider_url_key)
            or os.getenv(url_key)
            or ""
        )

    # Model: when projecting (provider_scoped=True), don't inherit the
    # currently-active provider's model from the flat llm_model / LLM_MODEL
    # globals — use either a stored per-provider key (e.g. OPENAI_MODEL,
    # written by set_llm_field below) or the provider's default. This way
    # switching the provider dropdown in Settings shows sensible per-vendor
    # defaults and doesn't leak openai's model onto deepseek previews etc.
    if provider_scoped:
        per_provider_model_key = f"{provider.upper()}_MODEL"
        llm_model = config.get(per_provider_model_key) or default_model_for(provider)
    else:
        llm_model = (
            config.get("llm_model")
            or config.get("LLM_MODEL")
            or os.getenv("LLM_MODEL")
            or default_model_for(provider)
        )

    # API key: skip flat unified alias when projecting so keys don't leak
    # across providers; otherwise read from flat alias -> legacy key -> env.
    k_key = bindings["api_key"]
    if provider_scoped:
        if k_key is None:
            api_key = ""
        else:
            api_key = config.get(k_key) or os.getenv(k_key) or ""
    elif k_key is None:
        api_key = config.get("api_key") or ""
    else:
        api_key = (
            config.get("api_key")
            or config.get(k_key)
            or os.getenv(k_key)
            or ""
        )

    # Cached available_models list (after last [m] refresh).
    # Per-provider bucket takes priority over the generic shared cache so
    # projections (/api/config/llm?provider=X) show the correct last-seen
    # list for that provider even when the active provider is different.
    per_provider_models_key = f"{provider.upper()}_AVAILABLE_MODELS"
    per_provider = config.get(per_provider_models_key)
    if isinstance(per_provider, list) and per_provider:
        raw_models = per_provider
    elif provider_scoped:
        # In projection mode, don't fall back to the shared cache — it would
        # leak the currently active provider's model list onto the preview.
        raw_models = []
    else:
        raw_models = (
            config.get("available_models")
            or config.get("AVAILABLE_MODELS")
            or []
        )
    if isinstance(raw_models, list):
        available_models = list(raw_models)
    else:
        available_models = []

    return {
        "provider": provider,
        "provider_url": provider_url,
        "llm_model": llm_model,
        "api_key": api_key,
        "available_models": available_models,
    }


def set_llm_field(config: Dict[str, Any], field: str, value: Any) -> Dict[str, Any]:
    """
    Write a logical LLM field into config (dual-write: legacy + new aliases).

    Mirrors api_key / provider_url into os.environ on writes so immediately
    following fetch operations use them without reloading config.
    """
    if config is None:
        raise ValueError("config must be a dict when setting LLM fields")
    field = (field or "").lower()
    if field in ("provider",):
        provider = (value or "openai").lower()
        config["provider"] = provider
        config["LLM_PROVIDER"] = provider
        return config

    if field == "llm_model":
        config["llm_model"] = value or ""
        config["LLM_MODEL"] = value or ""
        # Also remember the last-chosen model per provider so the Settings
        # preview (/api/config/llm?provider=X) can restore it when the user
        # flips the dropdown back to this provider.
        prov = str(config.get("provider") or "openai").lower()
        if prov in _PROVIDER_KEY_BINDINGS:
            config[f"{prov.upper()}_MODEL"] = value or ""
        return config

    if field == "available_models":
        models = list(value or [])
        config["available_models"] = models
        config["AVAILABLE_MODELS"] = models
        # Mirror into the current provider's per-provider cache bucket so
        # projections / Settings dropdowns for this provider still see the
        # list even after switching away and coming back.
        cur_provider = str(get_llm_config(config).get("provider") or "openai").lower()
        if cur_provider in _PROVIDER_KEY_BINDINGS:
            config[f"{cur_provider.upper()}_AVAILABLE_MODELS"] = models
        return config

    # Need current provider for bindings-based routing of url / api_key
    provider = get_llm_config(config)["provider"]
    bindings = _bindings_for(provider)

    if field == "provider_url":
        url_key = bindings["provider_url"]
        per_provider_url_key = f"{provider.upper()}_URL"
        if provider == "dashscope":
            # Keep the legacy key in sync for callers that still write a URL
            # through set_llm_field.  _dashscope_url() accepts either a region
            # name or a full URL, so both storage styles work.
            config[per_provider_url_key] = value or ""
            config["provider_url"] = value or ""
            config["DASHSCOPE_ENDPOINT"] = value or ""
            if value:
                os.environ["DASHSCOPE_ENDPOINT"] = value
            elif "DASHSCOPE_ENDPOINT" in os.environ:
                del os.environ["DASHSCOPE_ENDPOINT"]
            return config

        if value:
            config[per_provider_url_key] = value
            config["provider_url"] = value
        else:
            config[per_provider_url_key] = ""
            config["provider_url"] = _PROVIDER_BASE_URLS.get(provider, "")
        if url_key:
            config[url_key] = value or ""
            # Mirror to env so immediately-following fetches use it
            if value:
                os.environ[url_key] = value
            elif url_key in os.environ:
                del os.environ[url_key]
        return config

    if field == "api_key":
        key_name = bindings["api_key"]
        if key_name is None:
            config["api_key"] = value or ""
        else:
            config[key_name] = value or ""
            config["api_key"] = value or ""
            if value:
                os.environ[key_name] = value
            elif key_name in os.environ:
                del os.environ[key_name]
        return config

    raise ValueError("Unknown LLM config field: %r" % field)


def label_for_llm_field(field: str, provider: Optional[str] = None) -> str:
    """Human-readable label for each LLM config field.

    Labels are intentionally provider-agnostic for Base URL / API Key so the
    Settings page text stays stable when the user flips the provider dropdown.
    """
    field = (field or "").lower()
    if field == "provider":
        return "LLM Provider"
    if field == "provider_url":
        return "Base URL"
    if field == "llm_model":
        return "Model"
    if field == "api_key":
        return "API Key"
    if field == "available_models":
        return "Available Models (cached)"
    return field.title()


def is_llm_field_writable(field: str, provider: str) -> bool:
    """Whether a given LLM field makes sense to edit for this provider.

    * provider_url is ALWAYS writable — the defaults live in _PROVIDER_BASE_URLS
      (openai / deepseek / ollama / ...) but the user may need to override for
      proxies, VPC endpoints, self-hosted mirrors, region-specific deployments,
      or to switch between shim paths (/v1 vs /openai/v1 etc).
    * api_key is writable unless the provider explicitly has no key concept
      (None binding, i.e. local models like ollama).
    """
    provider = (provider or "openai").lower()
    bindings = _bindings_for(provider)
    if field.lower() == "provider_url":
        return True
    if field.lower() == "api_key":
        return bindings["api_key"] is not None
    return True


def cache_available_models(provider: str,
                           models,
                           config: Optional[Dict[str, Any]] = None,
                           persist: bool = True,
                           _just_peek: bool = False):
    """
    Save or peek at the cached available_models list for a provider.

    Performs TWO writes so both the generic "current cache" and a per-provider
    bucket are populated.  This way flipping the provider dropdown in Settings
    immediately restores the last-seen model list for that provider without a
    refresh.

    ``models`` can be either a list[str] (legacy ids) or list[dict] of enriched
    model entries with keys {id, description?, context_length?, owned_by?}.
    Both forms are accepted as input; returned value is always the same shape
    as what was passed in (or what was stored for peeks).

    * Normal path ``_just_peek=False``: stores into ``config["available_models"]``
      (active provider cache) AND ``config["{PROVIDER}_AVAILABLE_MODELS"]``
      (per-provider bucket).
    * Peek mode ``_just_peek=True``, ``models=[]``: returns stored list for
      this provider, using ``{PROVIDER}_AVAILABLE_MODELS`` first (so peeks
      return the right provider's list even when the currently active
      provider is different).  Falls back to global ``available_models`` then
      empty list.
    """
    provider = (provider or "").lower() or "openai"
    per_provider_key = f"{provider.upper()}_AVAILABLE_MODELS"
    if config is None:
        config = load_config()
    if _just_peek:
        per_provider = config.get(per_provider_key)
        if per_provider:
            return list(per_provider) if isinstance(per_provider, list) else []
        existing = get_llm_config(config)["available_models"]
        return list(existing) if existing else []

    # Normalize: allow list[str] or list[dict]; keep shape as passed.
    normalized = []
    for m in list(models or []):
        if isinstance(m, dict):
            if not m.get("id"):
                continue
            normalized.append(dict(m))
        else:
            s = str(m)
            if s:
                normalized.append(s)
    # Per-provider bucket (e.g. CUSTOM_AVAILABLE_MODELS)
    config[per_provider_key] = list(normalized) if normalized else []
    set_llm_field(config, "available_models", normalized)
    if persist:
        save_config(config)
    return normalized


# --------------------------------------------------------------------------
# Model discovery (OpenAI-compatible /models endpoint)
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# Provider presets and URL registry
# --------------------------------------------------------------------------

# The "canonical single default" base URL returned when no user override
# exists. Kept small because _PROVIDER_URL_PRESETS below carries every known
# official/regional URL for each provider, which is what the Settings
# dropdown actually displays to the user.
_PROVIDER_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "ollama": "http://localhost:11434/v1",
    "llama": "http://localhost:11434/v1",
}

# DashScope stores a region name in DASHSCOPE_ENDPOINT; map it to the URL the
# OpenAI-compatible client needs.  Kept here (rather than importing the ADK
# provider module) so runtime stays cheap to import.
_DASHSCOPE_ENDPOINTS = {
    "china": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "singapore": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "international": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
}


def _dashscope_url(config: Dict[str, Any]) -> str:
    raw = str(config.get("DASHSCOPE_ENDPOINT") or "china")
    if raw.startswith("http"):
        return raw
    return _DASHSCOPE_ENDPOINTS.get(raw.lower(), _DASHSCOPE_ENDPOINTS["china"])

# Multi-official / regional / proxy / shim URLs for every provider.
# Each entry: {"url": str, "label": str, "official": bool} — "official" means
# supplied by the vendor and shown with a vendor chip in the UI. Users can
# append their own remembered proxy/self-host URLs via the editable
# combobox and they appear alongside these with a "Custom" chip.
_PROVIDER_URL_PRESETS: Dict[str, List[Dict[str, Any]]] = {
    "openai": [
        {"url": "https://api.openai.com/v1",                  "label": "Global (api.openai.com)",     "official": True},
        {"url": "https://api.openai.com",                     "label": "Global root (no /v1)",         "official": True},
        {"url": "https://oai.azure.com/openai/deployments",   "label": "Azure OpenAI (custom deploy)", "official": True},
    ],
    "deepseek": [
        {"url": "https://api.deepseek.com/v1",                "label": "Official global (api.deepseek.com /v1)", "official": True},
        {"url": "https://api.deepseek.com",                   "label": "Official global (api.deepseek.com, no /v1 — older SDKs)", "official": True},
        {"url": "https://api.deepseek.ai/v1",                 "label": "Mirror (api.deepseek.ai)",    "official": False},
        {"url": "https://api.deepseek.cn/v1",                 "label": "Mainland China compatible",   "official": False},
    ],
    "dashscope": [
        {"url": "https://dashscope.aliyuncs.com/compatible-mode/v1",      "label": "DashScope China (Hangzhou region)", "official": True},
        {"url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "label": "DashScope International (Singapore)", "official": True},
        {"url": "https://dashscope-us.aliyuncs.com/compatible-mode/v1",   "label": "DashScope US region",        "official": True},
    ],
    "ollama": [
        {"url": "http://localhost:11434/v1",                  "label": "Local Ollama (localhost:11434 /v1)", "official": True},
        {"url": "http://localhost:11434",                     "label": "Local Ollama (root path)",    "official": False},
        {"url": "http://127.0.0.1:11434/v1",                  "label": "127.0.0.1 /v1",               "official": False},
        {"url": "http://host.docker.internal:11434/v1",       "label": "Docker host (mac/Win)",       "official": False},
    ],
    "llama": [
        {"url": "http://localhost:11434/v1",                  "label": "Local Llama.cpp via Ollama",  "official": False},
        {"url": "http://localhost:8080/v1",                   "label": "Local llama.cpp server /v1",  "official": True},
        {"url": "http://localhost:8080",                      "label": "Local llama.cpp server (root)", "official": False},
        {"url": "https://api.llama-api.com/v1",               "label": "LlamaAPI cloud",              "official": True},
        {"url": "https://api.groq.com/openai/v1",             "label": "Groq (OpenAI compatible)",    "official": False},
        {"url": "https://api.together.xyz/v1",                "label": "Together (OpenAI compatible)","official": False},
    ],
    "custom": [
        # Custom has NO vendor official URLs — user supplies their own
        # gateway (e.g. AI Gateway NSW, OneAPI, LiteLLM proxy, self-hosted
        # OpenAI-compatible shim). The user-typed URLs are remembered via
        # CUSTOM_URL_HISTORY on Save.
    ],
}

# Per-provider config key for the user's remembered list of base URLs.
# Shape stored: list[str] — the URL strings; deduped. A remembered URL is
# "Custom" unless it also matches a row in _PROVIDER_URL_PRESETS (in which
# case it's marked "official" when displayed by the frontend combobox).
def _url_history_key(provider: str) -> str:
    return f"{(provider or '').upper()}_URL_HISTORY"

_PROVIDER_KEY_NAMES = {
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "dashscope": "DASHSCOPE_API_KEY",
    "custom": "CUSTOM_API_KEY",
}


def get_base_url_choices(provider: str, config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Return the *full list* of URL choices for ``provider`` to show in the
    editable Base URL dropdown.

    Return shape (ordered):
      1. Preset/official URLs from ``_PROVIDER_URL_PRESETS[provider]``
         (``official=True`` rows).
      2. User-remembered URLs stored in ``{PROVIDER}_URL_HISTORY`` from
         prior saves (``official=False``, ``remembered=True``), skipping any
         that are duplicates of presets.

    Each row: ``{"url": str, "label": str, "official": bool, "remembered": bool}``
    """
    cfg = config if config is not None else load_config()
    presets = list(_PROVIDER_URL_PRESETS.get(provider or "", []) or [])
    preset_urls = {row.get("url", "") for row in presets if row.get("url")}

    history_key = _url_history_key(provider)
    history_raw = cfg.get(history_key) or []
    remembered: List[Dict[str, Any]] = []
    for item in history_raw:
        if isinstance(item, str):
            url = item.strip()
            label = url
            row = {"url": url, "label": label, "official": False, "remembered": True}
        elif isinstance(item, dict):
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            label = str(item.get("label") or url)
            row = {"url": url, "label": label,
                   "official": bool(item.get("official", False)),
                   "remembered": True}
        else:
            continue
        if not url or url in preset_urls:
            continue
        # deduplicate within history itself
        if any(existing.get("url") == url for existing in remembered):
            continue
        remembered.append(row)

    # Always show at least the canonical default as a single preset row even
    # if _PROVIDER_URL_PRESETS has no entry, so the dropdown is never empty.
    default_url = _PROVIDER_BASE_URLS.get(provider)
    if not presets and default_url:
        presets.append({"url": default_url, "label": f"Default ({default_url})", "official": True})
    return [*presets, *remembered]


def remember_base_url(provider: str, url: str,
                      config: Optional[Dict[str, Any]] = None,
                      save: bool = False) -> List[Dict[str, Any]]:
    """
    Append ``url`` to the per-provider remembered-URL history.

    * Deduplicates against existing remembered URLs.
    * Keeps only the most recent 24 URLs per provider.
    * If ``save`` is True (called from a Save handler that's already
      persisting), writes ``{PROVIDER}_URL_HISTORY`` into ``config`` and then
      calls ``save_config()``. Otherwise mutates ``config`` in place and the
      caller handles persistence.
    """
    if not provider or not url:
        return []
    url = str(url).strip().rstrip("/")
    if not url:
        return []
    cfg = config if config is not None else load_config()
    history_key = _url_history_key(provider)
    existing = cfg.get(history_key) or []
    # Normalize existing into plain str list first
    existing_urls: List[str] = []
    for item in existing:
        u = item if isinstance(item, str) else str(item.get("url") or "").strip()
        u = u.rstrip("/")
        if u:
            existing_urls.append(u)
    try:
        existing_urls.remove(url)
    except ValueError:
        pass
    existing_urls.insert(0, url)
    existing_urls = existing_urls[:24]
    cfg[history_key] = existing_urls
    if save:
        save_config(cfg)
    return get_base_url_choices(provider, cfg)



def provider_base_url(provider: str, config: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """
    Return the OpenAI-compatible base URL for provider (None if unknown).

    Prefers new unified ``provider_url`` field first (written by set_llm_field),
    then falls back to legacy storage keys, then hardcoded defaults. An
    explicit user override in cfg["provider_url"] always wins over the
    compile-time defaults (needed for proxies, regional shims, etc).
    """
    provider = provider.lower()
    raw = config if config is not None else load_config()
    active = get_llm_config(raw)["provider"]
    # Read the URL scoped to the requested provider.  Using the active flat
    # alias here used to leak, e.g., a custom gateway URL into a DeepSeek
    # model-list request while the active provider was custom.
    if provider == active:
        cfg = get_llm_config(raw)
    else:
        projected = dict(raw)
        projected["provider"] = provider
        cfg = get_llm_config(projected, provider_scoped=True)
    override = cfg.get("provider_url")
    if provider == "custom":
        return override or _PROVIDER_BASE_URLS.get("custom")
    if provider == "dashscope":
        return override or _dashscope_url(raw)
    # openai / deepseek / ollama / llama / unknown — explicit override wins
    return override or _PROVIDER_BASE_URLS.get(provider)


def fetch_provider_models(provider: Optional[str] = None,
                          config: Optional[Dict[str, Any]] = None,
                          refresh: bool = False,
                          *,
                          override_base_url: Optional[str] = None,
                          override_api_key: Optional[str] = None):
    """
    Query the provider OpenAI-compatible GET /models endpoint and return
    a normalized list of enriched model entries (each a ``dict`` with at
    least ``id`` and usually ``description``, ``owned_by``, optionally
    ``context_length``).  When a model discovery endpoint doesn't supply
    descriptions, we synthesize short provider-specific heuristics so the
    Settings UI can still show a hint next to each cached model.

    Semantics (cache-first by default, per config UI [m] spec):
      * ``refresh=False`` (DEFAULT): return cached available_models list if
        present (no network call). Used by ``/provider models`` and any
        passive info display.
      * ``refresh=True``: ignore cache, always hit live endpoint. Used
        only by the explicit ``[m]`` refresh key in config UI.

    Works for any provider that speaks the OpenAI protocol -- including a
    "custom" endpoint (uses CUSTOM_BASE_URL / CUSTOM_API_KEY) and local Ollama.
    Raises RuntimeError with a human-readable message on failure, so callers
    can show it to the user instead of a traceback.

    ``override_base_url`` / ``override_api_key`` are passed by the Settings
    page when the user has edited the form but not yet saved — they take
    priority over persisted config so a draft Custom URL can be tested.
    """
    if config is None:
        config = load_config()
    if provider is None:
        provider, _ = get_provider_model(config)
    provider = provider.lower()

    # -----------------------------
    # Cache-first short-circuit
    # -----------------------------
    if not refresh:
        cached = cache_available_models(provider, [], config,
                                        persist=False, _just_peek=True)
        if cached:
            return cached

    base_url = override_base_url or provider_base_url(provider, config)
    if not base_url:
        if provider == "custom":
            raise RuntimeError(
                "Base URL is not set. Set the Base URL first before refreshing."
            )
        raise RuntimeError("Cannot list models for provider %r." % provider)

    key_name = _PROVIDER_KEY_NAMES.get(provider)
    if override_api_key:
        api_key = override_api_key
    else:
        api_key = get_api_key(key_name, config) if key_name else None
    if not api_key:
        # Local servers (Ollama, some custom gateways) do not need a real key.
        api_key = "not-needed"

    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("openai package not available: %s" % exc)

    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        response = client.models.list()
        raw_models = list(response.data or [])
    except Exception as exc:
        raise RuntimeError("Could not list models from %s: %s" % (base_url, exc))

    if not raw_models:
        raise RuntimeError("The endpoint at %s returned no models." % base_url)

    # Normalize + enrich: build list[dict] with id, description, owned_by, context_length.
    # Use provider-specific heuristics if the /models payload lacks descriptions.
    enriched = []
    for m in raw_models:
        m_id = getattr(m, "id", None) or (isinstance(m, dict) and m.get("id")) or None
        if not m_id:
            continue
        entry = {"id": str(m_id)}

        owned_by = getattr(m, "owned_by", None) or (isinstance(m, dict) and m.get("owned_by"))
        if owned_by:
            entry["owned_by"] = str(owned_by)

        # Pull description from model object if present (many custom providers / Ollama include)
        raw_desc = (
            getattr(m, "description", None)
            or (isinstance(m, dict) and m.get("description"))
            or getattr(m, "summary", None)
            or (isinstance(m, dict) and m.get("summary"))
        )
        if isinstance(raw_desc, str) and raw_desc.strip():
            entry["description"] = raw_desc.strip()

        # context_length: some providers attach to model object in extra fields
        ctx = None
        for attr in ("context_length", "max_tokens", "max_context_length", "window"):
            val = getattr(m, attr, None) or (isinstance(m, dict) and m.get(attr))
            if isinstance(val, int) and val > 0:
                ctx = val
                break
        if ctx:
            entry["context_length"] = int(ctx)

        enriched.append(entry)

    # Sort by id (stable)
    enriched.sort(key=lambda e: e["id"])

    # Synthesize description when missing (once sorted, after dedupe by id)
    enriched = _dedupe_and_describe_models(enriched, provider)
    return enriched


def _dedupe_and_describe_models(models, provider: str):
    """De-dup by id and add a provider-specific short description for entries
    that arrived without one (OpenAI official / DeepSeek etc don't always
    send descriptions in /models)."""
    seen = {}
    for m in models:
        if m["id"] not in seen:
            seen[m["id"]] = m
    results = list(seen.values())

    def add_default(m: dict, desc_parts):
        if not m.get("description"):
            bits = []
            for p in desc_parts:
                if isinstance(p, str) and p:
                    bits.append(p)
                elif callable(p):
                    try:
                        v = p(m)
                        if v:
                            bits.append(str(v))
                    except Exception:
                        pass
            m["description"] = " — ".join(bits) if bits else _generic_model_desc(m, provider)
        return m

    provider_name = provider.capitalize()

    def _generic_model_desc(m, prov):
        ctx = m.get("context_length")
        owned = m.get("owned_by") or prov
        bits = [f"{owner_title(owned)} model"]
        if ctx:
            bits.append(f"{fmt_ctx(ctx)} context")
        return "; ".join(bits)

    def owner_title(name: str) -> str:
        if not name:
            return provider_name
        return (str(name).replace("-", " ").replace("_", " ").strip() or provider_name).title()

    def fmt_ctx(n: int) -> str:
        if n >= 1_000_000:
            return f"{n/1_000_000:.1f}M tokens"
        if n >= 1000:
            return f"{n//1000}K tokens"
        return f"{n} tokens"

    # Apply descriptions based on known-id heuristics if not already present.
    out = []
    for m in results:
        if m.get("description"):
            out.append(m)
            continue
        mid = m["id"].lower()
        parts = []
        # Provider-level heuristics
        if provider == "openai" or "gpt" in mid:
            if "gpt-4o" in mid:
                parts.append("OpenAI flagship multimodal model")
            elif "gpt-5" in mid:
                parts.append("OpenAI next-gen reasoning model")
            elif "gpt-4.1" in mid or "gpt-41" in mid:
                parts.append("OpenAI GPT-4.1 series")
            elif "gpt-4" in mid:
                parts.append("OpenAI GPT-4 large reasoning model")
            elif "gpt-3.5" in mid or "gpt-35" in mid:
                parts.append("OpenAI GPT-3.5 fast general-purpose model")
            elif "o3" in mid or "o1" in mid or "o4" in mid:
                parts.append("OpenAI reasoning / o-series model")
            else:
                parts.append("OpenAI-family model")
        elif provider == "deepseek" or "deepseek" in mid:
            if "r1" in mid or "reasoner" in mid:
                parts.append("DeepSeek reasoning (R1) model")
            elif "chat" in mid or "v3" in mid:
                parts.append("DeepSeek chat / general-purpose model")
            elif "coder" in mid:
                parts.append("DeepSeek code-specialized model")
            else:
                parts.append("DeepSeek-family model")
        elif provider == "dashscope" or "qwen" in mid:
            if "qwen3" in mid:
                parts.append("Aliyun Qwen3 open-weight chat model")
            elif "qwen2.5" in mid or "qwen25" in mid:
                parts.append("Aliyun Qwen2.5 chat model")
            elif "qwen-plus" in mid:
                parts.append("Aliyun Qwen-Plus flagship hosted model")
            elif "qwen-turbo" in mid:
                parts.append("Aliyun Qwen-Turbo fast hosted model")
            elif "qwen-max" in mid or "qwen-long" in mid:
                parts.append("Aliyun Qwen large-context hosted model")
            elif "qwq" in mid:
                parts.append("Aliyun QwQ reasoning model")
            else:
                parts.append("DashScope / Qwen-family model")
        elif provider == "ollama" or provider == "llama":
            size = None
            for token in mid.split(":")[-1:] + mid.split("-"):
                if token.endswith("b") and token[:-1].replace(".", "", 1).isdigit():
                    size = token; break
            parts.append(f"Ollama local model{' (' + size.upper() + ')' if size else ''}")
        elif provider == "custom":
            owned = m.get("owned_by")
            parts.append((owned.title() + " model") if owned else "Custom endpoint model")

        parts.append(lambda m: f"{fmt_ctx(m['context_length'])} context" if m.get("context_length") else None)
        parts.append(lambda m: ("provider: " + owner_title(m["owned_by"])) if m.get("owned_by") else None)
        add_default(m, parts)
        out.append(m)
    return out


# --------------------------------------------------------------------------
# Skills
# --------------------------------------------------------------------------

_skill_manager = None
_skill_manager_lock = threading.Lock()

# Skills whose directories exist but which are deliberately not registered.
# They were commented out of the built-in list and then quietly re-added by
# directory discovery, so the exclusion is made explicit here.
#
# "General Assistant" matters most: its `chat` tool asks an LLM to answer the
# user's question, which is what the agent is already doing -- offering it to
# the model is an invitation to burn a round trip on itself.
SKIP_DISCOVERED_SKILLS = {
    "General Assistant",  # skills/chat -- would recurse into another LLM call
    "Setup Wizard",       # skills/setup -- interactive, superseded by `config set`
    "Map",                # skills/map -- unfinished
    "Python Programmer",  # skills/programming -- executes arbitrary code
}


def _build_skill_manager():
    """Register the built-in skills, load external ones, and configure all."""
    from skills.manager import SkillManager
    from skills.base import LazySkill
    from skills.builtins import TimeSkill, BrowserSkill, ThinkingToggleSkill

    manager = SkillManager()
    for skill_cls in (TimeSkill, BrowserSkill, ThinkingToggleSkill):
        manager.register_skill(skill_cls())

    # Everything else is a LazySkill: only SKILL.md is read at startup.  The
    # real module is imported when the router first selects the skill, so a
    # turn that needs the clock does not pay for Jira, email or Chroma.
    known = {skill.name for skill in manager.skills} | SKIP_DISCOVERED_SKILLS
    skills_root = REPO_ROOT / "skills"

    def register_lazy(path):
        if not path.is_dir() or not (path / "SKILL.md").exists():
            return
        lazy = LazySkill(path)
        if lazy.name in known:
            return
        known.add(lazy.name)
        manager.register_skill(lazy)

    for child in sorted(skills_root.iterdir()):
        if not child.is_dir() or child.name.startswith("__"):
            continue
        if child.name in ("builtins", "imported"):
            continue
        register_lazy(child)

    imported_root = skills_root / "imported"
    if imported_root.exists():
        for child in sorted(imported_root.iterdir()):
            register_lazy(child)

    manager.configure(load_config())
    return manager


def get_skill_manager():
    """The process-wide ``SkillManager``, built on first use."""
    global _skill_manager
    if _skill_manager is None:
        with _skill_manager_lock:
            if _skill_manager is None:
                _skill_manager = _build_skill_manager()
    return _skill_manager


def reconfigure_skills() -> None:
    """Re-push config.json into every skill (after a key or provider change)."""
    if _skill_manager is not None:
        _skill_manager.configure(load_config())


# --------------------------------------------------------------------------
# Token statistics
# --------------------------------------------------------------------------

class TokenStatsManager:
    """Manages token usage statistics for sessions."""

    def __init__(self, sessions_dir: str):
        self.sessions_dir = sessions_dir

    def _get_stats_path(self, session_id: str) -> str:
        """Get the path to the stats file for a session."""
        return os.path.join(self.sessions_dir, f"{session_id}_stats.json")

    def _get_all_stats_files(self) -> List[str]:
        """Get all stats files in the sessions directory."""
        if not os.path.exists(self.sessions_dir):
            return []
        files = []
        for filename in os.listdir(self.sessions_dir):
            if filename.endswith("_stats.json"):
                files.append(os.path.join(self.sessions_dir, filename))
        return files

    def load_stats(self, session_id: str) -> Dict[str, Any]:
        """Load stats for a session, or create new stats if none exist."""
        stats_path = self._get_stats_path(session_id)
        if os.path.exists(stats_path):
            try:
                with open(stats_path, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        # Default empty stats structure
        return {
            "session_id": session_id,
            "created_at": datetime.now().isoformat(),
            "interactions": [],
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_tokens": 0
        }

    def save_stats(self, session_id: str, stats: Dict[str, Any]):
        """Save stats for a session."""
        os.makedirs(self.sessions_dir, exist_ok=True)
        stats_path = self._get_stats_path(session_id)
        with open(stats_path, "w") as f:
            json.dump(stats, f, indent=2)

    def add_interaction(self, session_id: Optional[str], prompt_tokens: int,
                        completion_tokens: int, user_message: Optional[str] = None,
                        timestamp: Optional[str] = None):
        """Add a token usage interaction to the session stats."""
        if session_id is None:
            return

        if timestamp is None:
            timestamp = datetime.now().isoformat()

        stats = self.load_stats(session_id)

        interaction = {
            "timestamp": timestamp,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens
        }
        if user_message:
            # Truncate long messages for storage
            interaction["message_preview"] = user_message[:100] + ("..." if len(user_message) > 100 else "")

        stats["interactions"].append(interaction)
        stats["total_prompt_tokens"] += prompt_tokens
        stats["total_completion_tokens"] += completion_tokens
        stats["total_tokens"] += prompt_tokens + completion_tokens

        self.save_stats(session_id, stats)

    def get_summary(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get a summary of token usage for a session."""
        stats = self.load_stats(session_id)
        if not stats["interactions"]:
            return None

        interaction_count = len(stats["interactions"])
        first_interaction = stats["interactions"][0]["timestamp"]
        last_interaction = stats["interactions"][-1]["timestamp"]

        # Calculate averages
        avg_prompt = stats["total_prompt_tokens"] // interaction_count if interaction_count > 0 else 0
        avg_completion = stats["total_completion_tokens"] // interaction_count if interaction_count > 0 else 0
        avg_total = stats["total_tokens"] // interaction_count if interaction_count > 0 else 0

        return {
            "session_id": session_id,
            "interaction_count": interaction_count,
            "first_interaction": first_interaction,
            "last_interaction": last_interaction,
            "total_prompt_tokens": stats["total_prompt_tokens"],
            "total_completion_tokens": stats["total_completion_tokens"],
            "total_tokens": stats["total_tokens"],
            "avg_prompt_tokens": avg_prompt,
            "avg_completion_tokens": avg_completion,
            "avg_total_tokens": avg_total
        }

    def get_overall_summary(self) -> Optional[Dict[str, Any]]:
        """Get overall token usage statistics across all sessions."""
        stats_files = self._get_all_stats_files()
        if not stats_files:
            return None

        total_sessions = 0
        total_interactions = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_tokens = 0
        first_interaction = None
        last_interaction = None

        for stats_file in stats_files:
            try:
                with open(stats_file, "r") as f:
                    stats = json.load(f)

                if stats.get("interactions"):
                    total_sessions += 1
                    total_interactions += len(stats["interactions"])
                    total_prompt_tokens += stats.get("total_prompt_tokens", 0)
                    total_completion_tokens += stats.get("total_completion_tokens", 0)
                    total_tokens += stats.get("total_tokens", 0)

                    # Track first and last interaction times
                    session_first = stats["interactions"][0]["timestamp"]
                    session_last = stats["interactions"][-1]["timestamp"]

                    if first_interaction is None or session_first < first_interaction:
                        first_interaction = session_first
                    if last_interaction is None or session_last > last_interaction:
                        last_interaction = session_last
            except Exception:
                continue

        if total_sessions == 0:
            return None

        # Calculate averages
        avg_prompt_per_session = total_prompt_tokens // total_sessions if total_sessions > 0 else 0
        avg_completion_per_session = total_completion_tokens // total_sessions if total_sessions > 0 else 0
        avg_total_per_session = total_tokens // total_sessions if total_sessions > 0 else 0

        avg_prompt_per_interaction = total_prompt_tokens // total_interactions if total_interactions > 0 else 0
        avg_completion_per_interaction = total_completion_tokens // total_interactions if total_interactions > 0 else 0
        avg_total_per_interaction = total_tokens // total_interactions if total_interactions > 0 else 0

        return {
            "total_sessions": total_sessions,
            "total_interactions": total_interactions,
            "first_interaction": first_interaction,
            "last_interaction": last_interaction,
            "total_prompt_tokens": total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
            "total_tokens": total_tokens,
            "avg_prompt_per_session": avg_prompt_per_session,
            "avg_completion_per_session": avg_completion_per_session,
            "avg_total_per_session": avg_total_per_session,
            "avg_prompt_per_interaction": avg_prompt_per_interaction,
            "avg_completion_per_interaction": avg_completion_per_interaction,
            "avg_total_per_interaction": avg_total_per_interaction
        }


_token_stats_manager: Optional[TokenStatsManager] = None


def get_token_stats_manager() -> TokenStatsManager:
    """The process-wide ``TokenStatsManager``, over ``~/.collig/sessions``."""
    global _token_stats_manager
    if _token_stats_manager is None:
        _token_stats_manager = TokenStatsManager(paths.sessions_dir)
    return _token_stats_manager
