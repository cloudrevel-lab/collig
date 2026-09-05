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
    Resolve (provider, model) -- config.json first, then env, then defaults.

    Note the precedence is the opposite way round from ``get_api_key``: the
    saved provider is a deliberate user preference, so it wins over a stale
    env var.
    """
    if config is None:
        config = load_config()
    provider = config.get("LLM_PROVIDER") or os.getenv("LLM_PROVIDER") or "openai"
    provider = provider.lower()
    model = config.get("LLM_MODEL") or os.getenv("LLM_MODEL") or DEFAULT_MODELS.get(provider, "gpt-4o")
    return provider, model


def default_model_for(provider: str) -> str:
    """The model to fall back to when a provider is selected without one."""
    return DEFAULT_MODELS.get(provider.lower(), "gpt-4o")


# --------------------------------------------------------------------------
# Model discovery (OpenAI-compatible /models endpoint)
# --------------------------------------------------------------------------

# The OpenAI-compatible base URL for each provider. "custom" is resolved from
# CUSTOM_BASE_URL at call time. Ollama exposes an OpenAI-compatible endpoint
# at /v1 on its local server.
_PROVIDER_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "ollama": "http://localhost:11434/v1",
    "llama": "http://localhost:11434/v1",
}

_DASHSCOPE_ENDPOINTS = {
    "china": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "singapore": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "international": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
}

_PROVIDER_KEY_NAMES = {
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "dashscope": "DASHSCOPE_API_KEY",
    "custom": "CUSTOM_API_KEY",
}


def provider_base_url(provider: str, config: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Return the OpenAI-compatible base URL for provider (None if unknown)."""
    provider = provider.lower()
    if config is None:
        config = load_config()
    if provider == "custom":
        return get_api_key("CUSTOM_BASE_URL", config)
    if provider == "dashscope":
        region = config.get("DASHSCOPE_ENDPOINT", "china")
        return _DASHSCOPE_ENDPOINTS.get(region, _DASHSCOPE_ENDPOINTS["china"])
    return _PROVIDER_BASE_URLS.get(provider)


def fetch_provider_models(provider: Optional[str] = None,
                          config: Optional[Dict[str, Any]] = None) -> List[str]:
    """
    Query the provider OpenAI-compatible GET /models endpoint and return
    a sorted list of model ids.

    Works for any provider that speaks the OpenAI protocol -- including a
    "custom" endpoint (uses CUSTOM_BASE_URL / CUSTOM_API_KEY) and local Ollama.
    Raises RuntimeError with a human-readable message on failure, so callers
    can show it to the user instead of a traceback.
    """
    if config is None:
        config = load_config()
    if provider is None:
        provider, _ = get_provider_model(config)
    provider = provider.lower()

    base_url = provider_base_url(provider, config)
    if not base_url:
        if provider == "custom":
            raise RuntimeError(
                "CUSTOM_BASE_URL is not set. Set it first "
                "(config set CUSTOM_BASE_URL <url>)."
            )
        raise RuntimeError(f"Cannot list models for provider {provider!r}.")

    key_name = _PROVIDER_KEY_NAMES.get(provider)
    api_key = get_api_key(key_name, config) if key_name else None
    if not api_key:
        # Local servers (Ollama, some custom gateways) do not need a real key.
        api_key = "not-needed"

    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(f"openai package not available: {exc}")

    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        response = client.models.list()
        models = sorted({m.id for m in response.data})
    except Exception as exc:
        raise RuntimeError(f"Could not list models from {base_url}: {exc}")

    if not models:
        raise RuntimeError(f"The endpoint at {base_url} returned no models.")
    return models


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
    from skills.builtins import TimeSkill, BrowserSkill, ThinkingToggleSkill
    from skills.filesystem import FileSystemSkill
    from skills.email import EmailSkill
    from skills.system import SystemSkill
    from skills.memory import MemorySkill
    from skills.loader import SkillLoader
    from skills.weather import WeatherSkill
    from skills.bookmark import BookmarkSkill
    from skills.news import NewsSkill
    from skills.profile import ProfileSkill
    from skills.git import GitSkill
    from skills.date_calculator import DateCalculatorSkill
    from skills.cache import CacheSkill
    from skills.lunar_calendar import LunarCalendarSkill
    from skills.menu import MenuSkill
    from skills.survey import SurveySkill
    from skills.diary import DiarySkill
    from skills.web_search import WebSearchSkill
    from skills.jira import JiraSkill

    manager = SkillManager()
    for skill_cls in (
        TimeSkill, BrowserSkill, ThinkingToggleSkill, WeatherSkill,
        FileSystemSkill, EmailSkill, SystemSkill, MemorySkill, BookmarkSkill,
        NewsSkill, ProfileSkill, GitSkill, DateCalculatorSkill, CacheSkill,
        LunarCalendarSkill, MenuSkill, SurveySkill, DiarySkill,
        WebSearchSkill, JiraSkill,
    ):
        manager.register_skill(skill_cls())

    # SkillLoader rediscovers every skill directory, including the ones just
    # registered above, so it is deduplicated by name here. Without this each
    # built-in skill lands in the manager twice and every one of its tools is
    # declared twice to the model.
    known = {skill.name for skill in manager.skills} | SKIP_DISCOVERED_SKILLS
    for skill in SkillLoader(skills_dir=REPO_ROOT / "skills").load_skills():
        if skill.name in known:
            continue
        known.add(skill.name)
        manager.register_skill(skill)

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
