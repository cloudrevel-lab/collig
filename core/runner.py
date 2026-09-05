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
import threading
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
    update_config,
)
from core.session import SessionManager

console = Console()

# The CLI is single-user by definition, and the web GUI runs on localhost.
USER_ID = "local"

ADK_DB_PATH = os.path.join(paths.sessions_dir, "adk.db")

# Written once the JSON sessions have been copied across, so the import does
# not re-run on every start.
MIGRATION_MARKER = os.path.join(paths.sessions_dir, ".adk_migrated")

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


class _LoopThread:
    """
    A private asyncio loop running on its own thread.

    ``asyncio.run()`` per call would tear down the loop between turns, which
    ADK's database session service and LiteLLM's pooled HTTP clients do not
    appreciate. One long-lived loop keeps both alive across the process.
    """

    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._serve, name="collig-adk", daemon=True
        )
        self._thread.start()

    def _serve(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def run(self, coro):
        """Run a coroutine on the loop and block until it finishes."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result()
        except KeyboardInterrupt:
            # Ctrl+C in the CLI: stop the work too, rather than leaving it
            # running on the background thread against the next turn.
            future.cancel()
            raise


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

        # Imported here, not at module scope: building the agent registers
        # every skill, and `core.runner` is imported by modules that only want
        # the class.
        from agents.collig.agent import (
            APP_NAME,
            app as adk_app,
            root_agent,
            token_stats_plugin,
        )

        self.app_name = APP_NAME
        self._root_agent = root_agent
        self._token_plugin = token_stats_plugin

        os.makedirs(paths.sessions_dir, exist_ok=True)
        self._session_service = DatabaseSessionService(db_url=f"sqlite:///{ADK_DB_PATH}")
        self._runner = Runner(app=adk_app, session_service=self._session_service)
        self._loop = _LoopThread()
        self._known_sessions: set = set()

        self.migrate_legacy_sessions()

    # ------------------------------------------------------------------
    # Tools and skills
    # ------------------------------------------------------------------

    @property
    def tools(self) -> List[Any]:
        """
        Every tool the enabled skills provide, as plain functions.

        Read as a property rather than cached, so toggling a skill is visible
        immediately. These are the undecorated functions, carrying ``.name``
        and ``.description`` from ``core.tooling.tool`` -- which is what the
        CLI's autocompletion and the Jira shortcuts use them for. The model
        sees a narrowed subset of these, chosen per turn by ``SkillToolset``.
        """
        functions: List[Any] = []
        for skill in get_skill_manager().skills:
            if not skill.enabled:
                continue
            try:
                functions.extend(skill.get_tools())
            except Exception:
                continue
        return functions

    # Historical alias: the LangChain agent distinguished the full tool list
    # from the filtered one, and a few call sites still ask for `all_tools`.
    @property
    def all_tools(self) -> List[Any]:
        return self.tools

    def refresh(self) -> None:
        """Re-read config.json into the skills after a settings change."""
        reconfigure_skills()

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
        from agents.collig.providers import ProviderError, describe_provider

        provider = (provider or "").lower()
        model = model or default_model_for(provider)

        console.print(f"Switching provider to {provider} (Model: {model})")
        try:
            set_model(provider, model)
        except ProviderError as e:
            return f"Cannot switch to {provider}: {e}"

        self.llm_provider, self.llm_model = describe_provider(provider, model)
        update_config(LLM_PROVIDER=self.llm_provider, LLM_MODEL=self.llm_model)
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
        session_id = f"scratch-{uuid.uuid4()}"
        self._loop.run(self._session_service.create_session(
            app_name=self.app_name, user_id=USER_ID, session_id=session_id
        ))
        return session_id

    def _discard_session(self, session_id: str) -> None:
        try:
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
        """
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

    async def _run_turn(self, message: str, session_id: str, verbose: bool,
                        token_callback: Optional[Callable[[str, str], None]]) -> Dict[str, Any]:
        """Drive one invocation, rendering events as they arrive."""
        new_message = types.Content(role="user", parts=[types.Part(text=message)])
        run_config = RunConfig(
            streaming_mode=StreamingMode.SSE if token_callback else StreamingMode.NONE
        )

        final_text = ""
        invocation_id = ""
        header_printed = False
        stream_started = False

        def header() -> None:
            nonlocal header_printed
            if verbose and not header_printed:
                console.print("\n[Thinking Process]")
                header_printed = True

        async for event in self._runner.run_async(
            user_id=USER_ID,
            session_id=session_id,
            new_message=new_message,
            run_config=run_config,
        ):
            invocation_id = event.invocation_id or invocation_id
            calls = event.get_function_calls()
            responses = event.get_function_responses()

            if calls:
                header()
                reasoning = _answer_text(event.content)
                if verbose and reasoning:
                    console.print(f"  ➜ Reasoning: {reasoning}")
                for call in calls:
                    if not verbose:
                        continue
                    console.print(f"  ➜ Planning to use tool: [bold]{call.name}[/bold]")
                    args = _mask(call.args or {})
                    try:
                        pretty = json.dumps(args, indent=2, default=str)
                    except Exception:
                        pretty = str(args)
                    console.print(
                        "    Args:\n"
                        + "\n".join("    " + line for line in pretty.splitlines())
                    )

            if responses:
                header()
                if verbose:
                    for response in responses:
                        console.print(f"    ✔ Tool '{response.name}' executed.")

            if calls or responses:
                continue

            text = _answer_text(event.content)
            if not text:
                continue

            if event.partial:
                # SSE deltas: emit as they arrive. The aggregated non-partial
                # event follows and becomes the authoritative answer, so it
                # must not be printed again -- the CLI's `response_started`
                # flag takes care of that.
                if token_callback:
                    if not stream_started:
                        if header_printed:
                            console.print("[End of Thinking]\n")
                            header_printed = False
                        token_callback("", "start")
                        stream_started = True
                    token_callback(text, "token")
            elif event.author != "user":
                final_text = text

        if verbose and header_printed:
            console.print("[End of Thinking]\n")
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

        # No session, or history explicitly suppressed (the connection tests):
        # run against a throwaway session so nothing is recorded.
        scratch = session_id is None or not include_history
        run_session_id = self._scratch_session() if scratch else session_id
        assert run_session_id is not None

        if not scratch:
            self._ensure_session(run_session_id)
            self.session_manager.add_message(run_session_id, "user", message)

        try:
            result = self._loop.run(
                self._run_turn(message, run_session_id, verbose, token_callback)
            )
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
            if scratch:
                self._discard_session(run_session_id)

        if not scratch and result.get("response"):
            # Mirrored into the JSON store because /api/sessions and
            # list_sessions.py still read from there.
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


def get_agent() -> AgentService:
    """The process-wide ``AgentService``, built on first use."""
    global _agent
    if _agent is None:
        with _agent_lock:
            if _agent is None:
                _agent = AgentService()
    return _agent
