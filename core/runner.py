"""
``AgentService`` -- the ADK ``Runner`` behind Collig's synchronous surfaces.

The Rich CLI and ``core/main.py``'s ``/api/chat`` both call blocking methods
and expect a plain result dict. ADK is async, so this module owns a private
event loop on a background thread and bridges the two, keeping the shape of
the old ``core.agent.Agent`` API (``process_message``, ``set_provider``,
``get_token_stats`` ...) so those call sites did not have to change.

What it replaces, from the original complaint that the agent had grown slow:

* ``_compress_history()`` -- an extra ``gpt-3.5-turbo`` round trip before
  every real request. ``ContextFilterPlugin`` now caps context by invocation
  count with no model call at all.
* ``create_react_agent()`` per message -- the graph was rebuilt whenever tool
  filtering changed the tool list. ``SkillToolset.get_tools`` narrows tools
  per turn against one long-lived agent.
* ``process_message_stream`` delegating straight to the blocking path. Events
  now stream as the model produces them.

Sessions live in ADK's SQLite service alongside the ones the web GUI writes,
so a conversation started in the CLI is replayable in the browser and vice
versa. The legacy ``~/.collig/sessions/*.json`` files are still written, since
``/api/sessions`` and ``list_sessions.py`` read them; a one-time migration
copies whatever they already hold into ADK.
"""
import asyncio
import json
import os
import shutil
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.events.event import Event
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService
from google.genai import types
from rich.console import Console

from core.paths import paths
from core.runtime import (
    default_model_for,
    get_provider_model,
    get_skill_manager,
    get_token_stats_manager,
    load_config,
    reconfigure_skills,
    save_config,
    update_config,
)
from core.session import SessionManager

console = Console()

# The CLI is single-user by definition, and the web GUI runs on localhost.
USER_ID = "local"

ADK_DB_PATH = paths.runtime_db_file
_ADK_DB_LEGACY_PATH = os.path.join(paths.sessions_dir, "adk.db")

MIGRATION_MARKER = os.path.join(paths.sessions_dir, ".adk_migrated")

_ADK_DB_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Eager import of the root agent module.
#
# ``agents.collig.agent`` performs import-time side effects such as skill
# registration and global singletons (LLM client pools, aiohttp connector
# pools, etc.) that internally create asyncio event loops via
# ``asyncio.get_event_loop``.  FastAPI runs sync chat calls on a Starlette
# threadpool worker that already has an asyncio event loop set via
# ``asgiref.sync``.  If the agents module is imported for the first time
# *from such a worker* (or from any other worker thread whose main thread has a
# pre-set loop, which propagates via the default policy under CPython 3.13+) the
# side effects contend with the policy state cross-thread and the import
# *deadlocks*.  That is exactly the symptom seen in
# ``POST /api/chat``: a 75s curl timeout with 0 bytes received even though
# unrelated endpoints like ``/api/sessions`` and ``/api/config/llm`` returned
# fine.
#
# Doing the import here, at module scope in ``core.runner`` during the *first*
# import of this module on the MAIN thread of the process, guarantees the
# side effects happen once, on a thread whose asyncio state is uncontaminated by
# Starlette's threadpool.  ``_build_agent_isolated`` below still moves the
# *construction* (AgentService + _ensure_runner) to its own worker thread that
# also clears ``set_event_loop(None) first; this is the *import*
# ordering fix.
# ---------------------------------------------------------------------------
try:
    import agents.collig.agent  # noqa: F401
    _AGENT_IMPORT: bool = True
except BaseException:  # pragma: no cover - startup safety net
    import traceback as _tb
    _AGENT_IMPORT = False
    _AGENT_IMPORT_TB = _tb.format_exc()


def _ensure_runtime_db_location() -> None:
    """Move the runtime SQLite DB out of sessions/ into storage/.

    Historically the file lived at ``~/.collig/sessions/adk.db`` which caused
    two problems: (1) a namespace collision with the JSON session files the
    web UI scans for its /api/sessions listing, and (2) DB-engine creation
    failures when the sessions/ directory layout raced with adk.db creation.
    It now lives at ``paths.runtime_db_file`` (``~/.collig/storage/collig.db``).
    An existing legacy file is moved across in place, atomically on supported
    filesystems, and gated by a process lock to avoid in-process races.
    """
    if not os.path.exists(_ADK_DB_LEGACY_PATH):
        return
    if os.path.exists(ADK_DB_PATH):
        # New location already has a file; keep the newer one and leave the
        # legacy file as a dangling artefact the user can clean up.
        try:
            os.remove(_ADK_DB_LEGACY_PATH)
        except OSError:
            pass
        return
    with _ADK_DB_LOCK:
        # Re-check under the lock in case another thread beat us.
        if not os.path.exists(_ADK_DB_LEGACY_PATH) or os.path.exists(ADK_DB_PATH):
            return
        try:
            os.rename(_ADK_DB_LEGACY_PATH, ADK_DB_PATH)
        except OSError:
            # Cross-filesystem or permission failure; fall back to copy+unlink.
            shutil.copy2(_ADK_DB_LEGACY_PATH, ADK_DB_PATH)
            try:
                os.remove(_ADK_DB_LEGACY_PATH)
            except OSError:
                pass

# Argument names whose values are masked in the verbose thinking block.
SECRET_HINTS = ("password", "secret", "key", "token", "credential")


def _mask(args: Any) -> Any:
    """Copy ``args`` with anything credential-shaped replaced by stars."""
    if not isinstance(args, dict):
        return args
    return {
        k: ("******" if any(h in k.lower() for h in SECRET_HINTS) else v)
        for k, v in args.items()
    }


def _answer_text(content: Optional[types.Content]) -> str:
    """
    The user-facing text of a content block.

    Reasoning parts are skipped: a thinking model emits them as ordinary text
    parts flagged ``thought``, and they belong in the thinking block rather
    than in the answer.
    """
    if content is None or not content.parts:
        return ""
    return "".join(
        part.text for part in content.parts
        if part.text and not getattr(part, "thought", False)
    )



def _thought_text(content: Optional[types.Content]) -> str:
    """Reasoning parts of a content block (the model's thinking)."""
    if content is None or not content.parts:
        return ""
    return "".join(
        part.text for part in content.parts
        if part.text and getattr(part, "thought", False)
    )


class _AsyncCaller:
    """
    Run a single async coroutine on a dedicated, throwaway event loop.

    ``google.adk.runners.Runner`` already ships a synchronous ``run()`` helper
    that starts its own private ``asyncio.run(...)`` on a daemon thread and
    streams events back through a ``queue.Queue``.  Collig previously layered
    its own permanent event-loop thread (``_LoopThread``) on top of that to
    drive the same ADK ``run_async`` generator plus the
    ``DatabaseSessionService`` async methods.  Under CPython 3.13 that double
    event-loop nesting combined with Starlette's threadpool (which sets an
    asyncio event loop on each sync-endpoint worker) to share loop-policy state
    across threads: the symptom was an indefinite hang during the first
    ``POST /api/chat`` in which the server returned 0 bytes until curl's
    60–75s timeout fired.

    Stripping out the custom ``_LoopThread`` and using a plain
    ``asyncio.run(coro)`` per session-service call eliminates the nesting:
    every call gets a fresh, policy-isolated event loop on the caller's own
    thread, so there is no cross-thread loop-policy contamination to deadlock
    on.  For the chat turn itself we use ADK's own sync ``Runner.run()`` so
    ``asyncio.run`` is invoked exactly once per turn on ADK's worker, the
    same way ADK's own CLI surface drives it.

    ``_AsyncCaller`` keeps the call sites uniform as ``self._loop.run(coro)``
    so every place previously written against ``_LoopThread`` works unchanged
    after replacing one class with the other.
    """

    def run(self, coro):
        asyncio.set_event_loop(None)
        return asyncio.run(coro)


class AgentService:
    """
    One ADK ``Runner`` plus the compatibility surface the CLI expects.

    The attributes are deliberately the ones ``core/cli.py`` already reads:
    ``skill_manager``, ``session_manager``, ``llm_provider``, ``llm_model``,
    ``verbose`` and ``tools``.
    """

    def __init__(self):
        self.name = "Collig"
        self.skill_manager = get_skill_manager()
        self.session_manager = SessionManager()
        self.token_stats_manager = get_token_stats_manager()
        # Kept because skills/builtins hands the agent instance around; only
        # `verbose` is actually read off it there.
        self.shared_context: Dict[str, Any] = {}
        self.active_skill_name: Optional[str] = None

        config = load_config()
        self.llm_provider, self.llm_model = get_provider_model(config)
        self.verbose = config.get("VERBOSE_THINKING", True)

        from skills.builtins import set_agent_instance
        set_agent_instance(self)

        # ---- Shallow-only init below.  We deliberately DO NOT create the ADK
        # SQLite engine or ADK Runner / App / DatabaseSessionService here.  The
        # Settings page only needs provider/key/model/verbose + tools and must
        # never touch adk.db.  The heavy ADK stack is deferred to
        # _ensure_runner(), called only when process_message*() / continue /
        # stop / start_session actually need it.
        #
        # Lazy: set these fields as None and fill them in on first use.
        self.app_name: Optional[str] = None
        self._root_agent = None
        self._token_plugin = None
        self._adk_app = None
        self._session_service = None
        self._runner = None
        self._loop = None
        self._known_sessions: Optional[set] = None
        self.__runner_ensured = False
        self.__runner_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Runner / ADK boot (deferred)
    # ------------------------------------------------------------------

    def _ensure_runner(self):
        """Create the ADK Runner, DB session service, App, and run loop.

        Called lazily only by methods that actually run the agent
        (process_message, session start/stop, etc.). This keeps the Settings
        page (which only calls get_agent().set_provider / tools / verbose /
        token_stats) free of any adk.db SQLite activity.
        """
        if self.__runner_ensured:
            return
        with self.__runner_lock:
            if self.__runner_ensured:
                return
            from agents.collig.agent import (
                APP_NAME,
                app as adk_app,
                root_agent,
                token_stats_plugin,
            )

            self.app_name = APP_NAME
            self._root_agent = root_agent
            self._token_plugin = token_stats_plugin
            self._adk_app = adk_app

            os.makedirs(paths.storage_dir, exist_ok=True)
            os.makedirs(paths.sessions_dir, exist_ok=True)
            _ensure_runtime_db_location()
            self._session_service = DatabaseSessionService(
                db_url=f"sqlite+aiosqlite:///{ADK_DB_PATH}"
            )
            self._runner = Runner(app=self._adk_app, session_service=self._session_service)
            self._loop = _AsyncCaller()
            self._known_sessions = set()
            if not os.path.exists(MIGRATION_MARKER):
                self.migrate_legacy_sessions()
            self.__runner_ensured = True

    # ------------------------------------------------------------------
    # Tools and skills
    # ------------------------------------------------------------------

    @property
    def tools(self) -> List[Any]:
        """
        Every enabled tool, as cheap name/description stubs.

        Read as a property rather than cached, so toggling a skill is visible
        immediately.  This catalogue intentionally does not call
        ``skill.get_tools()``: the CLI only needs names and descriptions for
        autocompletion, and forcing every lazy skill to import just to draw a
        prompt is the startup cost the harness exists to avoid.  The model
        sees real tools, narrowed per turn by ``SkillToolset``.
        """
        from skills.base import ToolStub

        stubs: List[Any] = []
        for skill in get_skill_manager().skills:
            if not skill.enabled:
                continue
            try:
                for item in skill.tool_metadata():
                    stubs.append(ToolStub(item["name"], item.get("description", "")))
            except Exception:
                continue
        return stubs

    # Historical alias: the LangChain agent distinguished the full tool list
    # from the filtered one, and a few call sites still ask for `all_tools`.
    @property
    def all_tools(self) -> List[Any]:
        return self.tools

    def refresh(self) -> None:
        """Re-read config.json into the skills after a settings change."""
        reconfigure_skills()

    # Legacy compatibility surface.  The CLI used to call these on the
    # LangChain agent; on the ADK harness they are cheap no-ops/aliases so
    # every existing command keeps working after the migration.
    def ensure_ready(self, config: Optional[Dict[str, Any]] = None) -> None:
        """Idempotent readiness hook; the ADK runner is built lazily."""
        self._ensure_runner()

    def load_skills_async(self, config: Optional[Dict[str, Any]] = None,
                          on_done=None):
        """Warm the ADK runner in the background, then call on_done."""
        def _run():
            try:
                self.ensure_ready(config)
            finally:
                if on_done is not None:
                    try:
                        on_done(self)
                    except Exception:
                        pass
        thread = threading.Thread(target=_run, name="collig-harness-warm", daemon=True)
        thread.start()
        return thread

    def _init_langchain_agent(self) -> None:
        """Backwards-compatible alias: re-read config, do not rebuild a graph."""
        self.refresh()

    @property
    def agent_executor(self):
        """Legacy health-check probe; returns the ADK Runner."""
        self._ensure_runner()
        return self._runner

    @property
    def llm(self):
        """Legacy probe used by diagnostics; returns the root model."""
        self._ensure_runner()
        return getattr(self._root_agent, "model", None)

    # ------------------------------------------------------------------
    # Provider
    # ------------------------------------------------------------------

    def set_provider(self, provider: str, model: Optional[str] = None) -> str:
        """
        Switch provider/model at runtime and remember the choice.

        The sub-agents inherit their model from the root agent, so this moves
        the whole tree with one assignment -- no rebuild, unlike the LangChain
        path which reconstructed the executor and all its tool bindings.
        """
        from agents.collig.agent import set_model
        from agents.collig.providers import ProviderError
        from core.runtime import get_llm_config, provider_base_url, set_llm_field

        provider = (provider or "").lower()
        model = model or default_model_for(provider)

        console.print(f"Switching provider to {provider} (Model: {model})")
        try:
            set_model(provider, model)
        except ProviderError as e:
            return f"Cannot switch to {provider}: {e}"

        # Persist the choice through the unified aliases.  Writing only
        # LLM_PROVIDER/LLM_MODEL used to leave the newer `provider` /
        # `llm_model` aliases stale, so the next start reverted.
        cfg = load_config()
        set_llm_field(cfg, "provider", provider)
        set_llm_field(cfg, "llm_model", model)
        scoped = get_llm_config(cfg, provider_scoped=True)
        set_llm_field(cfg, "api_key", scoped.get("api_key") or "")
        # DashScope stores a region, not a URL; provider_base_url maps it.
        if provider != "dashscope":
            url = provider_base_url(provider, cfg)
            if url:
                set_llm_field(cfg, "provider_url", url)
        save_config(cfg)

        self.llm_provider, self.llm_model = provider, model
        reconfigure_skills()
        return f"Provider switched to {self.llm_provider} ({self.llm_model})"

    def get_available_models(self) -> str:
        """Human-readable catalogue of providers and models."""
        from agents.collig.providers import list_available_models
        return list_available_models()

    # ------------------------------------------------------------------
    # Verbosity
    # ------------------------------------------------------------------

    def set_verbose(self, enabled: bool) -> str:
        """Show or hide the thinking block, and persist the preference."""
        self.verbose = enabled
        status = "enabled" if enabled else "disabled"
        try:
            update_config(VERBOSE_THINKING=enabled)
            return f"Thinking messages {status}. Preference saved."
        except Exception as e:
            return f"Thinking messages {status}, but failed to save preference: {e}"

    def toggle_verbose(self) -> str:
        """Flip the thinking block on or off."""
        return self.set_verbose(not self.verbose)

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    def _ensure_session(self, session_id: str) -> None:
        """Create the ADK session for ``session_id`` if it does not exist."""
        self._ensure_runner()
        if session_id in self._known_sessions:
            return
        existing = self._loop.run(self._session_service.get_session(
            app_name=self.app_name, user_id=USER_ID, session_id=session_id
        ))
        if existing is None:
            self._loop.run(self._session_service.create_session(
                app_name=self.app_name, user_id=USER_ID, session_id=session_id
            ))
        self._known_sessions.add(session_id)

    def _scratch_session(self) -> str:
        """
        A throwaway session for a stateless request.

        Used by the connection tests (``include_history=False``) and by
        ``/api/chat`` calls that carry no session, so neither pollutes a real
        conversation's history.
        """
        self._ensure_runner()
        session_id = f"scratch-{uuid.uuid4()}"
        self._loop.run(self._session_service.create_session(
            app_name=self.app_name, user_id=USER_ID, session_id=session_id
        ))
        return session_id

    def _discard_session(self, session_id: str) -> None:
        try:
            self._ensure_runner()
            self._loop.run(self._session_service.delete_session(
                app_name=self.app_name, user_id=USER_ID, session_id=session_id
            ))
        except Exception:
            pass

    def migrate_legacy_sessions(self) -> int:
        """
        Copy the JSON session history into ADK, once.

        Runs at startup so an existing conversation shows up in the web GUI
        with its history intact. Anything already present in ADK is skipped,
        and a marker file stops the scan repeating on later starts.

        NOTE: this method is called on the critical-path of the very first
        ``get_agent()`` call, which is what the FastAPI lifespan warm-up does.
        The per-file ``_loop.run`` calls use ``asyncio.run()`` on a fresh event
        loop each time (``_AsyncCaller``); scanning the sessions directory
        (now ~72 JSONs, 51 of which have messages) takes between 30–90s when
        run sequentially. That is acceptable for a one-time migration, but to
        keep the cold-start experience acceptable we:

        1. Bail out immediately (O(1)) if the marker file exists.
        2. Skip the session-service probe when the marker already exists --
           this guards against a pathological case where a previous run wrote
           the marker but the caller thread still has a stale event-loop in
           ``asyncio.get_event_loop_policy`` and the first ``_loop.run`` call
           inside ``os.listdir`` scope (which happens for every file on the
           legacy path) waits 2 minutes per probe on some policy locks.
        """
        self._ensure_runner()
        if os.path.exists(MIGRATION_MARKER):
            return 0

        migrated = 0
        try:
            filenames = sorted(
                f for f in os.listdir(paths.sessions_dir)
                if f.endswith(".json") and not f.endswith("_stats.json")
            )
        except OSError:
            return 0

        for filename in filenames:
            session_id = filename[: -len(".json")]
            try:
                with open(os.path.join(paths.sessions_dir, filename)) as f:
                    data = json.load(f)
            except Exception:
                continue

            messages = data.get("messages") or []
            if not messages:
                continue

            try:
                existing = self._loop.run(self._session_service.get_session(
                    app_name=self.app_name, user_id=USER_ID, session_id=session_id
                ))
                if existing is not None:
                    continue
                # create_session returns the live Session; append_event both
                # persists the event and appends it to that object, so it can
                # be reused across the whole conversation.
                session = self._loop.run(self._session_service.create_session(
                    app_name=self.app_name, user_id=USER_ID, session_id=session_id
                ))
                for message in messages:
                    self._loop.run(self._session_service.append_event(
                        session=session,
                        event=self._legacy_event(session_id, message),
                    ))
                migrated += 1
            except Exception:
                continue

        try:
            with open(MIGRATION_MARKER, "w") as f:
                f.write(datetime.now().isoformat())
        except OSError:
            pass

        if migrated:
            console.print(f"[dim]Imported {migrated} session(s) into the ADK store.[/dim]")
        return migrated

    def _legacy_event(self, session_id: str, message: Dict[str, Any]) -> Event:
        """Turn one stored JSON message into an ADK event."""
        self._ensure_runner()
        role = message.get("role", "user")
        author = "user" if role == "user" else self.app_name
        content = types.Content(
            role="user" if role == "user" else "model",
            parts=[types.Part(text=str(message.get("content", "")))],
        )
        event = Event(
            author=author,
            content=content,
            invocation_id=f"imported-{session_id}",
        )
        stamp = message.get("timestamp")
        if stamp:
            try:
                event.timestamp = datetime.fromisoformat(stamp).timestamp()
            except (TypeError, ValueError):
                pass
        return event

    # ------------------------------------------------------------------
    # Running a turn
    # ------------------------------------------------------------------

    def _run_turn(self, message: str, session_id: str, verbose: bool,
                  token_callback: Optional[Callable[[str, str], None]]) -> Dict[str, Any]:
        """Drive one invocation, rendering a structured thinking timeline.

        Uses ``google.adk.runners.Runner.run`` (the synchronous wrapper) rather
        than calling ``run_async`` via a nested event loop.  The sync wrapper
        streams events through a ``queue.Queue``; by using it directly we
        eliminate the double-event-loop nesting that previously deadlocked the
        FastAPI sync-threadpool worker on CPython 3.13.
        """
        from core.harness import route_message
        from core.thinking import ThinkingBlock

        self._ensure_runner()
        new_message = types.Content(role="user", parts=[types.Part(text=message)])
        run_config = RunConfig(
            streaming_mode=StreamingMode.SSE if token_callback else StreamingMode.NONE
        )

        final_text = ""
        invocation_id = ""
        stream_started = False
        route = route_message(message)

        display = ThinkingBlock(console, verbose)
        display.begin(message)
        display.route(route)

        def append_final(text: str) -> None:
            nonlocal final_text
            if not text:
                return
            if final_text:
                final_text = final_text.rstrip() + "\n\n" + text
            else:
                final_text = text

        try:
            for event in self._runner.run(
                user_id=USER_ID,
                session_id=session_id,
                new_message=new_message,
                run_config=run_config,
            ):
                invocation_id = event.invocation_id or invocation_id
                calls = event.get_function_calls()
                responses = event.get_function_responses()
                text = _answer_text(event.content)
                thought = _thought_text(event.content)

                if thought:
                    display.thought(thought)

                if calls:
                    # Model commentary alongside tool calls is planning text.
                    if text:
                        display.thought(text)
                    for call in calls:
                        args = _mask(call.args or {})
                        if call.name and call.name.startswith("transfer_to_agent"):
                            target = args.get("agent_name") if isinstance(args, dict) else None
                            display.transfer(str(target or call.name))
                        else:
                            display.plan(call.name, args)
                            display.tool_start(call.name)
                    # Text emitted alongside a tool call is planning commentary,
                    # not the answer; keep it in the thinking block only.
                    continue

                if responses:
                    for response in responses:
                        if response.name and response.name.startswith("transfer_to_agent"):
                            continue
                        display.tool_end(response.name)
                    continue

                if not text:
                    continue

                if event.partial:
                    if token_callback:
                        if not stream_started:
                            display.answering()
                            display.finish()
                            token_callback("", "start")
                            stream_started = True
                        token_callback(text, "token")
                elif event.author != "user":
                    display.answering()
                    append_final(text)
        except KeyboardInterrupt:
            display.finish()
            raise
        except Exception as exc:
            display.error(str(exc))
            display.finish()
            raise

        display.finish()
        if stream_started and token_callback:
            token_callback("", "end")

        usage = self._token_plugin.usage_for(invocation_id)
        return {
            "response": final_text,
            "action": "agent_response",
            "prompt_tokens": usage["prompt_tokens"],
            "completion_tokens": usage["completion_tokens"],
            "total_tokens": usage["total_tokens"],
        }

    def process_message(self, message: str, session_id: Optional[str] = None,
                        include_history: bool = True,
                        verbose: Optional[bool] = None) -> Dict[str, Any]:
        """
        Answer one message, blocking until the turn completes.

        Returns the same dict the LangChain agent did -- ``response``,
        ``action`` and the three token counts -- so existing callers are
        unaffected. Token counts are now measured by the provider rather than
        estimated at roughly 150 tokens per tool schema.
        """
        return self._dispatch(message, session_id, include_history, verbose, None)

    def process_message_stream(self, message: str, session_id: Optional[str] = None,
                               include_history: bool = True,
                               verbose: Optional[bool] = None,
                               token_callback: Optional[Callable[[str, str], None]] = None
                               ) -> Dict[str, Any]:
        """
        Answer one message, calling ``token_callback`` as text arrives.

        The callback is invoked as ``(text, kind)`` with kind in
        ``start``/``token``/``end``. Under LangChain this signature existed
        but delegated to the blocking path; it now really streams.
        """
        return self._dispatch(message, session_id, include_history, verbose, token_callback)

    def _dispatch(self, message: str, session_id: Optional[str],
                  include_history: bool, verbose: Optional[bool],
                  token_callback: Optional[Callable[[str, str], None]]) -> Dict[str, Any]:
        if verbose is None:
            verbose = self.verbose

        scratch = session_id is None or not include_history
        run_session_id: Optional[str] = None
        try:
            run_session_id = self._scratch_session() if scratch else session_id
            assert run_session_id is not None

            if not scratch:
                self._ensure_session(run_session_id)
                self.session_manager.add_message(run_session_id, "user", message)

            result = self._run_turn(message, run_session_id, verbose, token_callback)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            import traceback
            traceback.print_exc()
            result = {
                "response": f"I encountered an error: {str(e)}",
                "action": "error",
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }
        finally:
            if scratch and run_session_id:
                self._discard_session(run_session_id)

        if not scratch and run_session_id and result.get("response"):
            self.session_manager.add_message(run_session_id, "ai", result["response"])

        return result

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_token_stats(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Token usage for one session."""
        return self.token_stats_manager.get_summary(session_id)

    def get_overall_token_stats(self) -> Optional[Dict[str, Any]]:
        """Token usage across every session."""
        return self.token_stats_manager.get_overall_summary()


_agent: Optional[AgentService] = None
_agent_lock = threading.Lock()


def _build_agent_isolated() -> AgentService:
    """Construct the process-wide AgentService and perform its initial boot.

    We previously did this work on a throwaway worker thread.  Under CPython
    3.13, however, ``threading.Thread`` startup inherits the calling thread's
    asyncio event-loop policy state in subtle ways that conspire with the
    combined trio of (a) the caller's pre-set ``asyncio.set_event_loop`` from
    Starlette's sync-endpoint threadpool, (b) ``_LoopThread`` creating its own
    nested event-loop, and (c) ``aiosqlite`` resolving
    ``asyncio.get_running_loop`` during connection boot, to produce an
    indefinite hang that manifests as ``POST /api/chat`` returning 0 bytes
    until curl's 60s or 75s timeout fires.  Even with
    ``asyncio.set_event_loop(None)`` on both the caller and the worker side,
    the builder-thread pattern was observed to stall the very first
    ``get_agent()`` call for 7+ minutes in ORDER2 probes.

    The robust fix is: construct the ``AgentService`` and run its first boot
    synchronously on the caller's thread, but:

    * Ensure the heavy root-agent module was already imported at module scope
      of ``core.runner`` (see the eager-import block earlier in this file).
      Importing ``agents.collig.agent`` is by far the slowest single step and
      performing it here would push the first-user-message latency >40s.

    * Sever the calling thread's asyncio state with ``set_event_loop(None)``
      just before touching any ADK or aiosqlite code, so any policy state
      brought in by Starlette / ``asgiref.sync`` cannot contaminate
      ``_LoopThread`` or ``DatabaseSessionService``.

    After ``get_agent()`` returns once, subsequent calls are fast (<1us
    double-checked lock) because ``_agent`` is already populated.  To hide the
    cold-start latency from end users, the FastAPI ``lifespan`` in
    ``core.main`` pre-warms ``get_agent()`` on a daemon thread during the
    "application startup" phase, before uvicorn begins accepting HTTP.  The
    frontend's Chat spinner therefore has ~30s of runway during page load,
    which covers the cold start with comfortable margin.
    """
    asyncio.set_event_loop(None)
    if not _AGENT_IMPORT:
        # Module-scope eager import failed earlier (it was inside try/except).
        # Re-run it here after clearing asyncio state so any original error
        # surfaces cleanly rather than a generic "builder thread stalled".
        import agents.collig.agent  # noqa: F401
    svc = AgentService()
    svc._ensure_runner()
    return svc


def get_agent() -> AgentService:
    """The process-wide ``AgentService``, built on first use on an isolated
    worker thread to avoid asyncio-event-loop contamination from FastAPI's sync threadpool."""
    global _agent
    if _agent is None:
        with _agent_lock:
            if _agent is None:
                _agent = _build_agent_isolated()
    return _agent
