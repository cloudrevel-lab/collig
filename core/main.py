from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from pydantic import BaseModel, field_validator
from dotenv import load_dotenv
import json as _json
import os
import sys
import datetime
from typing import Any, Dict, List, Optional

# Add parent directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

load_dotenv()

from core.paths import paths
from core.runtime import (
    DEFAULT_MODELS,
    _PROVIDER_KEY_BINDINGS,
    _PROVIDER_KEY_NAMES,
    default_model_for,
    load_config,
    save_config,
    get_llm_config,
    set_llm_field,
    label_for_llm_field,
    is_llm_field_writable,
    fetch_provider_models,
    cache_available_models,
    provider_base_url,
    get_provider_model,
    reconfigure_skills,
    get_skill_manager,
    get_base_url_choices,
    remember_base_url,
)
from core.trace_manager import get_trace_manager
from core.session import SessionManager
from core.runner import get_agent

# ---------------------------------------------------------------------------
# Lightweight helpers that never require the full AgentService / ADK DB
# ---------------------------------------------------------------------------

_json_session_manager = SessionManager()


def _try_get_agent():
    """Return AgentService or None if the ADK DB can't be initialised."""
    try:
        return get_agent()
    except Exception:
        return None


def _compute_overall_token_stats() -> Dict[str, Any]:
    """Read *_stats.json files directly and return overall totals + averages."""
    sessions_dir = paths.sessions_dir
    total_sessions_with_stats = 0
    total_interactions = 0
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_tokens = 0
    first_interaction = None
    last_interaction = None

    if not os.path.isdir(sessions_dir):
        pass
    else:
        for fname in sorted(os.listdir(sessions_dir)):
            if not fname.endswith("_stats.json"):
                continue
            try:
                with open(os.path.join(sessions_dir, fname), "r") as f:
                    stats = _json.load(f)
            except Exception:
                continue
            interactions = stats.get("interactions") or []
            if not interactions:
                continue
            total_sessions_with_stats += 1
            total_interactions += len(interactions)
            total_prompt_tokens += int(stats.get("total_prompt_tokens", 0) or 0)
            total_completion_tokens += int(stats.get("total_completion_tokens", 0) or 0)
            total_tokens += int(stats.get("total_tokens", 0) or 0)
            session_first = interactions[0].get("timestamp")
            session_last = interactions[-1].get("timestamp")
            if session_first and (first_interaction is None or session_first < first_interaction):
                first_interaction = session_first
            if session_last and (last_interaction is None or session_last > last_interaction):
                last_interaction = session_last

    avg_per_turn = (total_tokens // total_interactions) if total_interactions > 0 else 0
    return {
        "sessions_with_stats": total_sessions_with_stats,
        "total_sessions": total_sessions_with_stats,
        "total_interactions": total_interactions,
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": total_completion_tokens,
        "total_tokens": total_tokens,
        "avg_tokens_per_turn": avg_per_turn,
        "avg_total_per_interaction": avg_per_turn,
        "first_interaction": first_interaction,
        "last_interaction": last_interaction,
    }


def _compute_session_token_stats(session_id: str) -> Optional[Dict[str, Any]]:
    """Return the per-session token summary from its *_stats.json file."""
    path = os.path.join(paths.sessions_dir, f"{session_id}_stats.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r") as f:
            stats = _json.load(f)
    except Exception:
        return None
    interactions = stats.get("interactions") or []
    if not interactions:
        return None
    interaction_count = len(interactions)
    total_prompt = int(stats.get("total_prompt_tokens", 0) or 0)
    total_completion = int(stats.get("total_completion_tokens", 0) or 0)
    total_toks = int(stats.get("total_tokens", 0) or 0)
    return {
        "session_id": session_id,
        "interaction_count": interaction_count,
        "first_interaction": interactions[0].get("timestamp"),
        "last_interaction": interactions[-1].get("timestamp"),
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "total_tokens": total_toks,
        "avg_prompt_tokens": (total_prompt // interaction_count) if interaction_count else 0,
        "avg_completion_tokens": (total_completion // interaction_count) if interaction_count else 0,
        "avg_total_tokens": (total_toks // interaction_count) if interaction_count else 0,
        "avg_tokens_per_turn": (total_toks // interaction_count) if interaction_count else 0,
    }

# ---------------------------------------------------------------------------
# Load config and configure skills
# ---------------------------------------------------------------------------

try:
    with open(paths.global_config_file, "r") as f:
        _config = _json.load(f)
except Exception:
    _config = {}

for var in ["OPENAI_API_KEY", "DEEPSEEK_API_KEY"]:
    if var not in _config and os.getenv(var):
        _config[var] = os.getenv(var)


# ---------------------------------------------------------------------------
# Lifespan — warm caches and the agent during uvicorn startup so the first
# user message does not pay the ADK cold-start cost.
# ---------------------------------------------------------------------------
@asynccontextmanager
async def _lifespan(app: FastAPI):
    # 1. Cache the LLM provider/model list early. This is HTTP-bound and fast,
    #    runs before accepting the first HTTP request.
    try:
        cache_available_models()
    except Exception:  # pragma: no cover - startup best-effort
        pass

    # 2. Warm the full AgentService on a daemon thread. The import + ADK boot
    #    takes ~15–45s depending on the LLM client pools and skill graph,
    #    which is too slow for a blocking lifespan but short enough that by
    #    the time the user navigates to Chat and types "1+1" the service is
    #    already live. Running it here (instead of in the request) also means
    #    we never share Starlette's sync-endpoint threadpool event-loop state
    #    with the AgentService boot path: this thread's asyncio state is
    #    always clean.
    import threading as _th

    def _warm_agent():
        try:
            # Ensure heavy imports are done even if the earlier module-level
            # eager-import in core.runner was swallowed by try/except.
            import core.runner  # noqa: F401
            get_agent()
        except BaseException as e:
            # Lifespan cannot fail the app boot on warmup; the first request
            # will surface the error with proper HTTP error semantics.
            import traceback as _tb
            print(f"[lifespan] agent warmup failed (OK, retry on first chat): {e}", flush=True)
            print(_tb.format_exc(), flush=True)

    _warm = _th.Thread(target=_warm_agent, name="collig-lifespan-warmup", daemon=True)
    _warm.start()

    try:
        yield
    finally:
        # No teardown needed for the loop thread; it is daemon-scoped.
        pass


app = _app = FastAPI(title="Collig API", version="0.2.0", lifespan=_lifespan)

# Configure CORS
_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helper: get skill instances
# ---------------------------------------------------------------------------

def _get_bookmark_skill():
    for skill in get_skill_manager().skills:
        if skill.name == "Bookmarks":
            return skill
    return None


def _get_memory_skill():
    for skill in get_skill_manager().skills:
        if skill.name == "Memory & Notes":
            return skill
    return None


def _get_diary_skill():
    for skill in get_skill_manager().skills:
        if skill.name == "Diary":
            return skill
    return None


def _get_all_bookmarks():
    skill = _get_bookmark_skill()
    if not skill or not getattr(skill, "vectorstore", None):
        return []
    try:
        collection = skill.vectorstore._collection
        data = collection.get(include=["documents", "metadatas"])
        docs = data.get("documents", [])
        metas = data.get("metadatas", [])
        ids = data.get("ids", [])
        results = []
        for d, m, i in zip(docs, metas, ids):
            desc = ""
            for line in d.split('\n'):
                if line.startswith("Description:"):
                    desc = line.replace("Description:", "").strip()
                    break
            results.append({
                "id": i,
                "url": m.get("url", ""),
                "description": desc,
                "tags": m.get("tags", ""),
                "timestamp": m.get("timestamp", ""),
            })
        results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return results
    except Exception:
        return []


def _get_all_notes():
    skill = _get_memory_skill()
    if not skill or not getattr(skill, "vectorstore", None):
        return []
    try:
        collection = skill.vectorstore._collection
        data = collection.get(include=["documents", "metadatas"])
        docs = data.get("documents", [])
        metas = data.get("metadatas", [])
        ids = data.get("ids", [])
        results = []
        for d, m, i in zip(docs, metas, ids):
            results.append({
                "id": i,
                "content": d,
                "timestamp": m.get("timestamp", ""),
            })
        results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return results
    except Exception:
        return []


def _get_all_diary_entries():
    skill = _get_diary_skill()
    if not skill or not getattr(skill, "vectorstore", None):
        return []
    try:
        collection = skill.vectorstore._collection
        data = collection.get(include=["documents", "metadatas"])
        docs = data.get("documents", [])
        metas = data.get("metadatas", [])
        ids = data.get("ids", [])
        results = []
        for d, m, i in zip(docs, metas, ids):
            results.append({
                "id": i,
                "content": d,
                "timestamp": m.get("timestamp", ""),
            })
        results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return results
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Root / Health
# ---------------------------------------------------------------------------

@_app.get("/health")
def health_check():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

class _ChatRequestPydantic(BaseModel):
    message: str
    session_id: Optional[str] = None
    include_history: bool = True
    verbose: Optional[bool] = None


class _ChatResponsePydantic(BaseModel):
    response: str
    action: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    session_id: Optional[str] = None


@_app.post("/api/chat", response_model=_ChatResponsePydantic)
def chat_endpoint(request: _ChatRequestPydantic):
    agent = get_agent()
    try:
        result = agent.process_message(
            request.message,
            session_id=request.session_id,
            include_history=request.include_history,
            verbose=request.verbose,
        )
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail={
                "error": str(e),
                "type": type(e).__name__,
            },
        )
    return _ChatResponsePydantic(
        response=result.get("response", ""),
        action=result.get("action"),
        prompt_tokens=result.get("prompt_tokens"),
        completion_tokens=result.get("completion_tokens"),
        total_tokens=result.get("total_tokens"),
        session_id=result.get("session_id") or request.session_id,
    )


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

@_app.get("/api/sessions")
def list_sessions():
    """List all chat sessions with summary info."""
    try:
        sessions_dir = paths.sessions_dir
        if not os.path.exists(sessions_dir):
            return {"sessions": [], "total": 0}
        sessions = []
        for fname in os.listdir(sessions_dir):
            if not fname.endswith(".json") or fname.endswith("_stats.json"):
                continue
            fpath = os.path.join(sessions_dir, fname)
            try:
                with open(fpath, "r") as f:
                    data = _json.load(f)
                msgs = data.get("messages", [])
                preview = ""
                for m in msgs:
                    if m.get("role") == "user":
                        preview = m.get("content", "")[:100]
                        break
                user_count = sum(1 for m in msgs if m.get("role") == "user")
                ai_count = sum(1 for m in msgs if m.get("role") == "ai")
                sessions.append({
                    "id": data.get("id", fname.replace(".json", "")),
                    "created_at": data.get("created_at", ""),
                    "message_count": len(msgs),
                    "user_messages": user_count,
                    "ai_messages": ai_count,
                    "preview": preview,
                    "last_activity": msgs[-1].get("timestamp", data.get("created_at", "")) if msgs else data.get("created_at", ""),
                })
            except Exception:
                continue
        sessions.sort(key=lambda x: x.get("last_activity", ""), reverse=True)
        return {"sessions": sessions, "total": len(sessions)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@_app.post("/api/sessions", status_code=201)
def create_session():
    """Create a new empty session."""
    try:
        agent = _try_get_agent()
        if agent is not None:
            session_id = agent.session_manager.create_session()
        else:
            session_id = _json_session_manager.create_session()
        return {"session_id": session_id, "created_at": datetime.datetime.now().isoformat()}
    except HTTPException:
        raise
    except Exception as e:
        # Fallback: create via the lightweight JSON session manager
        try:
            session_id = _json_session_manager.create_session()
            return {"session_id": session_id, "created_at": datetime.datetime.now().isoformat()}
        except Exception as e2:
            raise HTTPException(status_code=500, detail=f"{e}; fallback failed: {e2}")


@_app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    """Get full session details including all messages."""
    # Try JSON session store first (works without ADK DB).
    json_data = _json_session_manager.load_session(session_id)
    if json_data is not None:
        return json_data
    # Fallback to the ADK-backed session manager if available.
    agent = _try_get_agent()
    if agent is not None:
        try:
            data = agent.session_manager.load_session(session_id)
            if data is not None:
                return data
        except Exception:
            pass
    raise HTTPException(status_code=404, detail="Session not found")


@_app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    """Delete a chat session, its stats and traces."""
    try:
        fpath = os.path.join(paths.sessions_dir, f"{session_id}.json")
        if os.path.exists(fpath):
            os.remove(fpath)
        stats_path = os.path.join(paths.sessions_dir, f"{session_id}_stats.json")
        if os.path.exists(stats_path):
            os.remove(stats_path)
        traces_path = os.path.join(paths.sessions_dir, f"{session_id}_traces.json")
        if os.path.exists(traces_path):
            os.remove(traces_path)
        return {"message": "Session deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# LLM Configuration
# ---------------------------------------------------------------------------

@_app.get("/api/config/llm")
def get_llm_config_endpoint(provider: Optional[str] = None):
    """Get the LLM config plus field metadata.

    If ``provider`` query param is supplied, we *project* the current config
    onto that provider (showing which URL / key / model / cached models the
    user has previously stored for it) without mutating the persisted
    provider setting. Used by the Settings page so the form fields update
    live as the user flips the provider dropdown before pressing Save.
    """
    cfg = load_config()
    # Real provider currently persisted
    real_llm = get_llm_config(cfg)
    real_provider = real_llm["provider"]

    target_provider = (provider or "").strip().lower() or real_provider
    if target_provider not in ("openai", "deepseek", "dashscope", "ollama", "llama", "custom"):
        target_provider = real_provider

    if target_provider == real_provider:
        projected = real_llm
    else:
        # Build a synthetic config dict whose provider is the target;
        # get_llm_config with provider_scoped=True will pull legacy provider-X
        # values (OPENAI_API_KEY / DASHSCOPE_ENDPOINT / …) without leaking
        # the currently-active flat aliases (provider_url / api_key / llm_model
        # set for the currently active provider).
        projected_cfg = dict(cfg)
        projected_cfg["provider"] = target_provider
        projected = get_llm_config(projected_cfg, provider_scoped=True)

    fields = []
    for f in ("provider", "provider_url", "llm_model", "api_key", "available_models"):
        field_row = {
            "key": f,
            "value": projected.get(f),
            "label": label_for_llm_field(f, target_provider),
            "writable": is_llm_field_writable(f, target_provider),
        }
        if f == "provider_url":
            # Populate the editable combobox dropdown: official vendor presets
            # + user's remembered historical URLs (from prior saves) for this
            # provider. Deepseek currently shows the 4 official rows plus any
            # the user has typed and saved before.
            cfg_for_choices = cfg if target_provider == real_provider else projected_cfg
            field_row["choices"] = get_base_url_choices(target_provider, cfg_for_choices)
        fields.append(field_row)
    return {
        "config": projected,
        "fields": fields,
        "provider": target_provider,
        "real_provider": real_provider,
        "providers_supported": ["openai", "deepseek", "dashscope", "ollama", "llama", "custom"],
    }


class _LlmConfigUpdate(BaseModel):
    provider: Optional[str] = None
    provider_url: Optional[str] = None
    llm_model: Optional[str] = None
    api_key: Optional[str] = None
    # Accept both legacy list[str] (plain ids) and the new enriched list[dict]
    # entries produced by /api/config/models refresh. set_llm_field /
    # cache_available_models already handle either shape uniformly.
    available_models: Optional[List[Any]] = None

    @field_validator("available_models")
    @classmethod
    def _validate_available_models(cls, v):
        if v is None:
            return v
        if not isinstance(v, list):
            raise ValueError("available_models must be a list")
        out: List[Any] = []
        seen: set = set()
        for item in v:
            if isinstance(item, str):
                ident = item.strip()
                if not ident:
                    continue
                key = ident
            elif isinstance(item, dict):
                ident = str(item.get("id") or item.get("model") or "").strip()
                if not ident:
                    continue
                key = ident
            else:
                raise ValueError(
                    f"available_models entries must be str or dict, got {type(item).__name__}"
                )
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out


@_app.put("/api/config/llm")
def update_llm_config_endpoint(update: _LlmConfigUpdate):
    """Update one or more LLM fields. Switches the running agent on provider/model change."""
    cfg = load_config()
    # ---- Read old provider/model before applying updates, so we only rebuild the runtime
    # agent ONLY when they actually change (not every Save with the frontend POSTs
    # all fields).
    old_provider, old_model = get_provider_model(cfg)
    changed = False
    for field in ("provider", "provider_url", "llm_model", "api_key", "available_models"):
        value = getattr(update, field, None)
        if value is None and field != "available_models":
            continue
        if field == "available_models" and value is None:
            continue
        set_llm_field(cfg, field, value)
        changed = True
    if changed:
        save_config(cfg)
    new_provider, new_model = get_provider_model(cfg)

    # Remember the provider_url that was saved (if any non-empty) into the
    # per-provider URL history so the dropdown shows it alongside the
    # official preset list. This lets the user type "Custom → deepseek → click
    # Save and have that URL appear in the editable combobox next time, or click
    # the dropdown and pick the official ones + history back.
    try:
        f_target = new_provider
        url_saved_for_history = None
        if getattr(update, "provider_url", None) is not None:
            url_saved_for_history = str(getattr(update, "provider_url")).strip()
        elif cfg.get("provider_url"):
            # fallback if URL was already present but not explicitly passed by the client
            url_saved_for_history = str(cfg.get("provider_url") or "").strip()
        if url_saved_for_history:
            remember_base_url(f_target, url_saved_for_history, cfg, save=True)
    except Exception:
        # Remembering is best-effort; never fail the Save.
        pass

    provider_changed = (new_provider or "").lower() != (old_provider or "").lower()
    model_changed = (new_model or "") != (old_model or "")

    # Switch runtime provider/model ONLY if either actually differs from what was
    # persisted before this request. This prevents us from touching the ADK
    # App/SQLite engine on Saves that don't really switch anything (common case:
    # user refreshed available_models & clicked Save, provider/model unchanged).
    #
    # If provider/model DID change, prefer the runner's lightweight
    # `set_provider` (core.runner) which re-binds the root agent model without
    # rebuilding the whole ADK App, over the legacy core.agent path that
    # rebuilds the langchain executor + ADK SQLite engine.
    #
    # If runtime swap fails we DON'T fail the save -- settings are already
    # persisted to disk and the next CLI invocation will pick them up anyway.
    switch_warning: Optional[str] = None
    if provider_changed or model_changed:
        # get_agent already aliased to runner singleton from main imports
        try:
            switch_agent = get_agent()
            if switch_agent is not None and hasattr(switch_agent, "set_provider"):
                switch_agent.set_provider(new_provider, new_model)
        except Exception as e:
            # Fallback: try legacy core.agent path (will also error on
            # runtime DB engine issue; but wrap for diagnostic)
            try:
                from core.agent import get_agent as _legacy_agent_get
                leg = _legacy_agent_get()
                if leg is not None and hasattr(leg, "set_provider"):
                    leg.set_provider(new_provider, new_model)
            except Exception as legacy_e:
                switch_warning = (
                    f"Settings were saved, but the in-process agent could not be "
                    f"switched dynamically ({type(legacy_e).__name__}: {legacy_e}). "
                    f"The new provider/model will be used on the next CLI run or "
                    f"service restart."
                )

    # Re-attach skills (uses latest provider/model for tool bindings).
    try:
        reconfigure_skills()
    except Exception as re_e:
        msg = f"reconfigure_skills: {type(re_e).__name__}: {re_e}"
        if switch_warning is None:
            switch_warning = msg
        else:
            switch_warning = switch_warning + "; " + msg

    result = get_llm_config_endpoint()
    if isinstance(result, dict):
        if switch_warning:
            result["runtime_warning"] = switch_warning
        result["_meta"] = {
            "runtime_switch": {
                "provider_changed": provider_changed,
                "model_changed": model_changed,
                "new_provider": new_provider,
                "new_model": new_model,
            },
            "changed": changed,
        }
    return result


class _LlmTestRequest(BaseModel):
    provider: Optional[str] = None
    provider_url: Optional[str] = None
    llm_model: Optional[str] = None
    api_key: Optional[str] = None


@_app.post("/api/config/llm/test")
def test_llm_connection_endpoint(req: _LlmTestRequest):
    """Validate the current LLM draft config with a tiny real API call.

    The Settings page POSTs the current *unsaved* form values so the user can
    verify a new API key / custom Base URL / model works without saving.
    The backend builds a synthetic config dict from the payload + persisted
    defaults, builds a client, and calls chat completions with 16 token max.
    Returns a diagnostic record with:
      - provider, base_url, model used
      - latencies (resolve / connect / ttft / total)
      - validation status ("ok" / "error")
      - short request summary (system prompt, user ping)
      - response (text + usage)
      - error class + message on failure
    """
    import time as _time
    import traceback as _tb

    cfg = load_config()
    log: List[Dict[str, Any]] = []
    start_ts = _time.perf_counter()

    def logit(phase: str, **extra):
        rec: Dict[str, Any] = {
            "ts": _time.perf_counter() - start_ts,
            "phase": phase,
        }
        rec.update(extra)
        log.append(rec)

    # ---- Resolve the effective provider / model / url / key ----
    try:
        # Apply form overrides onto a copy of the persisted config so defaults
        # for unchanged fields still work (e.g. testing just a new key for the
        # already-chosen provider doesn't require re-typing the URL / model).
        draft_cfg = dict(cfg)
        if req.provider:
            set_llm_field(draft_cfg, "provider", req.provider)
        if req.provider_url is not None:
            set_llm_field(draft_cfg, "provider_url", req.provider_url)
        if req.llm_model:
            set_llm_field(draft_cfg, "llm_model", req.llm_model)
        if req.api_key is not None:
            set_llm_field(draft_cfg, "api_key", req.api_key)

        eff = get_llm_config(draft_cfg)
        provider = str(eff["provider"] or "openai").lower()
        model = str(eff["llm_model"] or "")
        if not model:
            model = default_model_for(provider) or ""
        base_url = provider_base_url(provider, draft_cfg) or ""
        bindings = _PROVIDER_KEY_BINDINGS.get(provider)
        k_key = bindings.get("api_key") if isinstance(bindings, dict) else None
        if k_key:
            api_key = (
                draft_cfg.get("api_key")
                or draft_cfg.get(k_key)
                or os.getenv(k_key)
                or ""
            )
        else:
            api_key = ""
        needs_key = k_key is not None
        logit(
            "resolve",
            provider=provider,
            model=model,
            base_url=base_url,
            has_api_key=bool(api_key),
            key_required=needs_key,
        )
    except Exception as e:
        logit(
            "error.resolve",
            error_class=type(e).__name__,
            error_message=str(e),
            traceback=_tb.format_exc(limit=6),
        )
        return {
            "ok": False,
            "status": "invalid_config",
            "started_at": _time.strftime("%H:%M:%S"),
            "duration_ms": int((_time.perf_counter() - start_ts) * 1000),
            "log": log,
        }

    if needs_key and not api_key:
        logit(
            "validate.error",
            error_class="MissingApiKey",
            error_message=f"Provider {provider!r} requires an API key.",
        )
        return {
            "ok": False,
            "status": "missing_api_key",
            "provider": provider,
            "base_url": base_url,
            "model": model,
            "started_at": _time.strftime("%H:%M:%S"),
            "duration_ms": int((_time.perf_counter() - start_ts) * 1000),
            "log": log,
        }
    if not base_url:
        logit(
            "validate.error",
            error_class="MissingBaseUrl",
            error_message=f"Provider {provider!r} has no Base URL configured.",
        )
        return {
            "ok": False,
            "status": "missing_base_url",
            "provider": provider,
            "base_url": base_url,
            "model": model,
            "started_at": _time.strftime("%H:%M:%S"),
            "duration_ms": int((_time.perf_counter() - start_ts) * 1000),
            "log": log,
        }
    if not model:
        logit(
            "validate.error",
            error_class="MissingModel",
            error_message=f"Provider {provider!r} has no model configured.",
        )
        return {
            "ok": False,
            "status": "missing_model",
            "provider": provider,
            "base_url": base_url,
            "model": model,
            "started_at": _time.strftime("%H:%M:%S"),
            "duration_ms": int((_time.perf_counter() - start_ts) * 1000),
            "log": log,
        }

    # ---- Build client & send a tiny deterministic ping ----
    system_ping = (
        "You are a connection-test echo bot. Answer ONLY with 'pong' and nothing else. "
        "Do not include any extra text, punctuation, or commentary."
    )
    user_ping = "ping"
    payload_preview = {
        "model": model,
        "temperature": 0,
        "max_tokens": 32,
        "messages": [
            {"role": "system", "content": system_ping},
            {"role": "user", "content": user_ping},
        ],
    }
    logit(
        "request.build",
        base_url=base_url,
        request=payload_preview,
    )
    try:
        try:
            from openai import OpenAI as _OAI  # type: ignore
        except ImportError as imp:
            raise RuntimeError("openai package is unavailable: %s" % imp) from imp

        client_kwargs: Dict[str, Any] = {
            "api_key": api_key or "not-needed",
            "base_url": base_url,
            "max_retries": 1,
            "timeout": 20.0,
        }
        client = _OAI(**client_kwargs)
        logit("client.ready", timeout_s=20.0, max_retries=1)

        send_at = _time.perf_counter()
        resp = client.chat.completions.create(**payload_preview)  # type: ignore
        ttft_ms = int((_time.perf_counter() - send_at) * 1000)
        resp_dict = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
        choices = resp_dict.get("choices") or []
        text = ""
        finish_reason = None
        if choices:
            msg = choices[0].get("message") or {}
            text = msg.get("content") or ""
            finish_reason = choices[0].get("finish_reason")
        usage = resp_dict.get("usage") or {}
        total_duration_ms = int((_time.perf_counter() - start_ts) * 1000)
        logit(
            "response.ok",
            ttft_ms=ttft_ms,
            total_duration_ms=total_duration_ms,
            finish_reason=finish_reason,
            usage=usage,
            response_text_preview=text[:400],
        )
        valid = text.strip().lower().startswith("pong")
        return {
            "ok": True,
            "status": "ok" if valid else "unexpected_response",
            "provider": provider,
            "base_url": base_url,
            "model": model,
            "started_at": _time.strftime("%H:%M:%S"),
            "duration_ms": total_duration_ms,
            "ttft_ms": ttft_ms,
            "response": {
                "text": text,
                "finish_reason": finish_reason,
                "usage": usage,
            },
            "request_preview": payload_preview,
            "validation": {
                "expected_reply_prefix": "pong",
                "matched": valid,
            },
            "log": log,
        }
    except Exception as e:
        total_duration_ms = int((_time.perf_counter() - start_ts) * 1000)
        # try to pull out HTTP status / body if it's an APIStatusError
        status_code = None
        resp_body = None
        try:
            status_code = getattr(e, "status_code", None)
            if hasattr(e, "response") and getattr(e.response, "text", None):
                resp_body = str(e.response.text)[:1200]
        except Exception:
            pass
        logit(
            "request.error",
            error_class=type(e).__name__,
            error_message=str(e),
            status_code=status_code,
            response_body_preview=resp_body,
            traceback=_tb.format_exc(limit=8),
            duration_ms=total_duration_ms,
        )
        return {
            "ok": False,
            "status": "request_error",
            "provider": provider,
            "base_url": base_url,
            "model": model,
            "started_at": _time.strftime("%H:%M:%S"),
            "duration_ms": total_duration_ms,
            "error": {
                "class": type(e).__name__,
                "message": str(e),
                "status_code": status_code,
                "body": resp_body,
            },
            "request_preview": payload_preview,
            "log": log,
        }


@_app.get("/api/config/models")
def list_models_endpoint(provider: Optional[str] = Query(None),
                         refresh: bool = Query(False),
                         base_url: Optional[str] = Query(None),
                         api_key: Optional[str] = Query(None)):
    """List available models for a provider (cached unless refresh=true).

    The Settings page sets ``base_url`` / ``api_key`` (optional) when the user has
    unsaved draft changes in the form — they are forwarded directly to
    ``fetch_provider_models`` so Custom endpoints or proxy URLs can be probed before
    the user commits the Base URL.
    """
    try:
        cfg = load_config()
        actual_provider = (provider or get_provider_model(cfg)[0]).lower()
        models = fetch_provider_models(
            provider=actual_provider,
            config=cfg,
            refresh=refresh,
            override_base_url=(base_url or None),
            override_api_key=(api_key or None),
        )
        if refresh:
            # Persist the refreshed list per-provider + globally.
            cache_available_models(actual_provider, models, cfg, persist=True)
            # If the provider was given explicitly, also update the {PROVIDER}_MODEL
            # per-provider last model
        return {
            "models": models,
            "provider": actual_provider,
            "count": len(models),
            "base_url_used": (base_url or provider_base_url(actual_provider, cfg)) if actual_provider else None,
        }
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Full Config (raw config.json access)
# ---------------------------------------------------------------------------

@_app.get("/api/config")
def get_full_config():
    """Return the raw ~/.collig/config.json contents."""
    return load_config()


@_app.put("/api/config")
def update_full_config(values: Dict[str, Any]):
    """Merge arbitrary key/values into config.json and persist."""
    try:
        cfg = load_config()
        cfg.update(values)
        save_config(cfg)
        reconfigure_skills()
        return {"message": "Config saved", "config": cfg}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------

@_app.get("/api/skills")
def list_skills():
    """List all registered skills with enable/disable status and tool counts."""
    sm = get_skill_manager()
    result = []
    for skill in sm.skills:
        try:
            tools = skill.get_tools() if skill.enabled else []
        except Exception:
            tools = []
        result.append({
            "name": skill.name,
            "enabled": skill.enabled,
            "description": getattr(skill, "description", "") or "",
            "tool_count": len(tools),
            "tool_names": [getattr(t, "name", str(t)) for t in tools],
        })
    # Return both formats: flat list (for ConfigView) and wrapped (for anyone else)
    return result


class _SkillToggle(BaseModel):
    skill_name: str
    enabled: bool


@_app.put("/api/skills/toggle")
def toggle_skill(toggle: _SkillToggle):
    """Enable or disable a skill by name."""
    sm = get_skill_manager()
    for skill in sm.skills:
        if skill.name == toggle.skill_name:
            skill.enabled = toggle.enabled
            cfg = load_config()
            # Save skill enable state in config if the skill uses it
            save_config(cfg)
            return {"message": f"Skill '{toggle.skill_name}' {'enabled' if toggle.enabled else 'disabled'}",
                    "name": toggle.skill_name, "enabled": toggle.enabled}
    raise HTTPException(status_code=404, detail=f"Skill '{toggle.skill_name}' not found")


# ---------------------------------------------------------------------------
# Token Statistics
# ---------------------------------------------------------------------------

@_app.get("/api/stats/tokens")
def overall_token_stats():
    """Overall token usage across every session (computed from *_stats.json directly)."""
    raw = _compute_overall_token_stats()
    # Merge in live AgentService stats if the runner is healthy, but never require it.
    try:
        agent = _try_get_agent()
        if agent is not None:
            runner_stats = agent.get_overall_token_stats() or {}
            if runner_stats:
                for k, v in runner_stats.items():
                    if v is not None and raw.get(k) in (None, 0):
                        raw[k] = v
    except Exception:
        pass
    # Return flat fields (the DashboardView reads them directly):
    return raw


@_app.get("/api/stats/tokens/{session_id}")
def session_token_stats(session_id: str):
    """Token usage for one session (reads *_stats.json directly)."""
    summary = None
    try:
        agent = _try_get_agent()
        if agent is not None:
            summary = agent.get_token_stats(session_id)
    except Exception:
        summary = None
    if summary is None:
        summary = _compute_session_token_stats(session_id)
    # ChatView reads sessionStats.summary.*, so always wrap for shape stability.
    return {
        "session_id": session_id,
        "summary": summary or {},
    }


# ---------------------------------------------------------------------------
# Traces (LLM calls + Tool calls)
# ---------------------------------------------------------------------------

@_app.get("/api/traces/{session_id}")
def get_session_traces(session_id: str):
    """Get all invocation traces for a session (summaries + full data)."""
    tm = get_trace_manager()
    traces = tm.get_session_traces(session_id)
    summaries = tm.list_invocation_summaries(session_id)
    return {
        "session_id": session_id,
        "invocation_summaries": summaries,
        "invocations": traces.get("invocations", {}),
    }


@_app.get("/api/traces/{session_id}/{invocation_id}")
def get_invocation_trace(session_id: str, invocation_id: str):
    """Get detailed trace for one invocation (LLM calls + tool calls)."""
    tm = get_trace_manager()
    inv = tm.get_invocation_trace(session_id, invocation_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="Invocation trace not found")
    return inv


# ---------------------------------------------------------------------------
# Bookmarks API
# ---------------------------------------------------------------------------

class _BookmarkCreate(BaseModel):
    url: str
    description: str = ""
    tags: str = ""


class _BookmarkUpdate(BaseModel):
    url: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[str] = None


@_app.get("/api/bookmarks")
def list_bookmarks():
    try:
        bookmarks = _get_all_bookmarks()
        return {"bookmarks": bookmarks, "total": len(bookmarks)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@_app.post("/api/bookmarks", status_code=201)
def create_bookmark(bm: _BookmarkCreate):
    skill = _get_bookmark_skill()
    if not skill or not getattr(skill, "vectorstore", None):
        raise HTTPException(status_code=503, detail="Bookmark system not initialized. Check OPENAI_API_KEY.")
    try:
        from langchain_core.documents import Document
        meta = {
            "url": bm.url,
            "timestamp": datetime.datetime.now().isoformat(),
            "tags": bm.tags,
            "type": "user_bookmark"
        }
        search_content = f"URL: {bm.url}\nDescription: {bm.description}\nTags: {bm.tags}"
        skill.vectorstore.add_documents([Document(page_content=search_content, metadata=meta)])
        return {"message": "Bookmark created", "url": bm.url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@_app.delete("/api/bookmarks/{bookmark_id}")
def delete_bookmark(bookmark_id: str):
    skill = _get_bookmark_skill()
    if not skill or not getattr(skill, "vectorstore", None):
        raise HTTPException(status_code=503, detail="Bookmark system not initialized.")
    try:
        skill.vectorstore.delete(ids=[bookmark_id])
        return {"message": "Bookmark deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@_app.put("/api/bookmarks/{bookmark_id}")
def update_bookmark(bookmark_id: str, bm: _BookmarkUpdate):
    skill = _get_bookmark_skill()
    if not skill or not getattr(skill, "vectorstore", None):
        raise HTTPException(status_code=503, detail="Bookmark system not initialized.")
    try:
        existing = skill.vectorstore._collection.get(ids=[bookmark_id], include=["documents", "metadatas"])
        if not existing.get("ids"):
            raise HTTPException(status_code=404, detail="Bookmark not found")
        old_content = existing["documents"][0]
        old_meta = existing["metadatas"][0]
        new_url = bm.url if bm.url is not None else old_meta.get("url", "")
        new_tags = bm.tags if bm.tags is not None else old_meta.get("tags", "")
        old_desc = ""
        for line in old_content.split('\n'):
            if line.startswith("Description:"):
                old_desc = line.replace("Description:", "").strip()
                break
        new_desc = bm.description if bm.description is not None else old_desc
        new_meta = {
            "url": new_url,
            "timestamp": old_meta.get("timestamp", datetime.datetime.now().isoformat()),
            "tags": new_tags,
            "type": "user_bookmark"
        }
        search_content = f"URL: {new_url}\nDescription: {new_desc}\nTags: {new_tags}"
        skill.vectorstore._collection.update(
            ids=[bookmark_id],
            documents=[search_content],
            metadatas=[new_meta]
        )
        return {"message": "Bookmark updated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Notes API
# ---------------------------------------------------------------------------

class _NoteCreate(BaseModel):
    content: str


class _NoteUpdate(BaseModel):
    content: Optional[str] = None


@_app.get("/api/notes")
def list_notes():
    try:
        notes = _get_all_notes()
        return {"notes": notes, "total": len(notes)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@_app.post("/api/notes", status_code=201)
def create_note(note: _NoteCreate):
    skill = _get_memory_skill()
    if not skill or not getattr(skill, "vectorstore", None):
        raise HTTPException(status_code=503, detail="Memory system not initialized. Check OPENAI_API_KEY.")
    try:
        from langchain_core.documents import Document
        meta = {"timestamp": datetime.datetime.now().isoformat(), "type": "user_note"}
        skill.vectorstore.add_documents([Document(page_content=note.content, metadata=meta)])
        return {"message": "Note created"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@_app.delete("/api/notes/{note_id}")
def delete_note(note_id: str):
    skill = _get_memory_skill()
    if not skill or not getattr(skill, "vectorstore", None):
        raise HTTPException(status_code=503, detail="Memory system not initialized.")
    try:
        skill.vectorstore.delete(ids=[note_id])
        return {"message": "Note deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@_app.put("/api/notes/{note_id}")
def update_note(note_id: str, note: _NoteUpdate):
    skill = _get_memory_skill()
    if not skill or not getattr(skill, "vectorstore", None):
        raise HTTPException(status_code=503, detail="Memory system not initialized.")
    try:
        existing = skill.vectorstore._collection.get(ids=[note_id], include=["documents", "metadatas"])
        if not existing.get("ids"):
            raise HTTPException(status_code=404, detail="Note not found")
        old_meta = existing["metadatas"][0]
        new_content = note.content if note.content is not None else existing["documents"][0]
        new_meta = {
            "timestamp": old_meta.get("timestamp", datetime.datetime.now().isoformat()),
            "type": "user_note"
        }
        skill.vectorstore._collection.update(
            ids=[note_id],
            documents=[new_content],
            metadatas=[new_meta]
        )
        return {"message": "Note updated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Diary API
# ---------------------------------------------------------------------------

class _DiaryEntryCreate(BaseModel):
    content: str


class _DiaryEntryUpdate(BaseModel):
    content: Optional[str] = None


@_app.get("/api/diary")
def list_diary():
    try:
        entries = _get_all_diary_entries()
        return {"entries": entries, "total": len(entries)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@_app.post("/api/diary", status_code=201)
def create_diary_entry(entry: _DiaryEntryCreate):
    skill = _get_diary_skill()
    if not skill or not getattr(skill, "vectorstore", None):
        raise HTTPException(status_code=503, detail="Diary system not initialized. Check OPENAI_API_KEY.")
    try:
        from langchain_core.documents import Document
        meta = {"timestamp": datetime.datetime.now().isoformat(), "type": "diary_entry"}
        skill.vectorstore.add_documents([Document(page_content=entry.content, metadata=meta)])
        return {"message": "Diary entry created"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@_app.delete("/api/diary/{entry_id}")
def delete_diary_entry(entry_id: str):
    skill = _get_diary_skill()
    if not skill or not getattr(skill, "vectorstore", None):
        raise HTTPException(status_code=503, detail="Diary system not initialized.")
    try:
        skill.vectorstore.delete(ids=[entry_id])
        return {"message": "Diary entry deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@_app.put("/api/diary/{entry_id}")
def update_diary_entry(entry_id: str, entry: _DiaryEntryUpdate):
    skill = _get_diary_skill()
    if not skill or not getattr(skill, "vectorstore", None):
        raise HTTPException(status_code=503, detail="Diary system not initialized.")
    try:
        existing = skill.vectorstore._collection.get(ids=[entry_id], include=["documents", "metadatas"])
        if not existing.get("ids"):
            raise HTTPException(status_code=404, detail="Diary entry not found")
        old_meta = existing["metadatas"][0]
        new_content = entry.content if entry.content is not None else existing["documents"][0]
        new_meta = {
            "timestamp": old_meta.get("timestamp", datetime.datetime.now().isoformat()),
            "type": "diary_entry"
        }
        skill.vectorstore._collection.update(
            ids=[entry_id],
            documents=[new_content],
            metadatas=[new_meta]
        )
        return {"message": "Diary entry updated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Serve Frontend (Collig)
# ---------------------------------------------------------------------------

FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")

if os.path.exists(FRONTEND_DIST):
    _app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="assets")

    @_app.get("/")
    @_app.get("/{path:path}")
    async def serve_frontend(path: str = ""):
        if path.startswith("api/") or path.startswith("assets/"):
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))



