"""
ADK plugins carrying over behaviour the LangChain agent had inline.

``TokenStatsPlugin`` replaces ``extract_token_usage`` and its estimate-if-
missing fallback: ADK reports usage on the model response, so the numbers
written to ``~/.collig/sessions/*_stats.json`` are now measured rather than
guessed at ~150 tokens per tool schema.

``TrivialQueryPlugin`` keeps the trivial-query shortcut. Doing it here rather
than in the toolset matters, because clearing ``llm_request.config.tools``
strips ADK's auto-generated ``transfer_to_agent`` declarations as well as the
skill tools -- a toolset returning ``[]`` cannot do that.

``UnroutedToolPlugin`` catches the model calling a tool this turn did not
offer.  Per-turn selection is keyword-based, so any phrasing the keyword lists
miss hands the model an empty toolset while its instructions still name
``search_news``, ``get_weather`` and friends; ADK then aborts the whole
invocation with ``ValueError: Tool 'search_news' not found``.  The plugin runs
the tool when it belongs to a skill this root agent owns (marking the routing
gap that caused it) and otherwise returns a plain "not available" response the
model can answer from, so the turn degrades instead of dying.
"""
import inspect
import logging
from collections import OrderedDict
from typing import Any, Dict, Iterable, Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin

from core.runtime import get_token_stats_manager

from .toolsets import is_greeting, is_trivial_query, text_of

logger = logging.getLogger(__name__)


class TokenStatsPlugin(BasePlugin):
    """
    Accumulates reported token usage per invocation and records it on finish.

    A single turn can make several model calls (a tool round-trip, a sub-agent
    transfer), so usage is summed across the invocation and written once --
    matching what a CLI user thinks of as "this message cost N tokens".
    """

    # How many finished invocations to keep totals for. Only the current turn
    # is ever read back, so this is a small ring rather than a cache.
    _RECENT_LIMIT = 16

    def __init__(self, name: str = "token_stats_plugin"):
        super().__init__(name=name)
        # invocation_id -> {"prompt", "completion", "session_id", "message"}
        self._pending: Dict[str, Dict[str, Any]] = {}
        # Totals for invocations that have finished. `after_run_callback` runs
        # before the caller regains control, so without this the CLI would
        # always read zero for the turn it just completed.
        self._recent: "OrderedDict[str, Dict[str, int]]" = OrderedDict()

    def _bucket(self, invocation_id: str) -> Dict[str, Any]:
        return self._pending.setdefault(
            invocation_id,
            {"prompt": 0, "completion": 0, "session_id": None, "message": None},
        )

    async def before_run_callback(self, *, invocation_context: InvocationContext):
        bucket = self._bucket(invocation_context.invocation_id)
        bucket["session_id"] = invocation_context.session.id
        content = invocation_context.user_content
        if content and content.parts:
            bucket["message"] = " ".join(p.text for p in content.parts if p.text)
        return None

    async def after_model_callback(self, *, callback_context: CallbackContext,
                                   llm_response: LlmResponse):
        usage = llm_response.usage_metadata
        if usage is None:
            return None
        bucket = self._bucket(callback_context.invocation_id)
        # candidates_token_count is the completion side; thought tokens are
        # reported separately by reasoning models and belong there too.
        completion = (usage.candidates_token_count or 0) + (
            getattr(usage, "thoughts_token_count", None) or 0
        )
        bucket["prompt"] += usage.prompt_token_count or 0
        bucket["completion"] += completion
        return None

    async def after_run_callback(self, *, invocation_context: InvocationContext):
        invocation_id = invocation_context.invocation_id
        bucket = self._pending.pop(invocation_id, None)
        if not bucket:
            return None
        self._remember(invocation_id, bucket["prompt"], bucket["completion"])
        if bucket["prompt"] or bucket["completion"]:
            try:
                get_token_stats_manager().add_interaction(
                    bucket["session_id"],
                    bucket["prompt"],
                    bucket["completion"],
                    user_message=bucket["message"],
                )
            except Exception as e:
                logger.warning("Failed to record token stats: %s", e)
        return None

    async def on_run_error_callback(self, *, invocation_context: InvocationContext,
                                    error: Exception):
        # Drop the bucket so a failed turn does not leak, or later get
        # attributed to whichever invocation happens to reuse the id.
        self._pending.pop(invocation_context.invocation_id, None)
        return None

    def _remember(self, invocation_id: str, prompt: int, completion: int) -> None:
        self._recent[invocation_id] = {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
        }
        while len(self._recent) > self._RECENT_LIMIT:
            self._recent.popitem(last=False)

    def usage_for(self, invocation_id: str) -> Dict[str, int]:
        """Usage for an invocation, running or just finished."""
        bucket = self._pending.get(invocation_id)
        if bucket:
            prompt, completion = bucket["prompt"], bucket["completion"]
            return {
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": prompt + completion,
            }
        return self._recent.get(
            invocation_id,
            {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )


class TrivialQueryPlugin(BasePlugin):
    """
    Sends no tool declarations at all for greetings, thanks and simple maths.

    Roughly 150 tokens per tool schema, times every tool that would otherwise
    be declared, on a turn whose answer is "hello".
    """

    def __init__(self, name: str = "trivial_query_plugin"):
        super().__init__(name=name)

    async def before_model_callback(self, *, callback_context: CallbackContext,
                                    llm_request: LlmRequest) -> Optional[LlmResponse]:
        text = text_of(callback_context)
        if not is_trivial_query(text):
            return None
        # A greeting may still have a job: a due routine (for example the user
        # checks the news every morning) needs its tool to be offered.  Keep
        # the declarations in that one case; SkillToolset has already narrowed
        # them to the routine's skill.
        if is_greeting(text):
            try:
                from core.user_memory import get_user_memory

                if get_user_memory().due_routine():
                    return None
            except Exception:
                pass
        if llm_request.config is not None:
            llm_request.config.tools = None
            llm_request.config.tool_config = None
        llm_request.tools_dict = {}
        return None


# Tools that must never be run just because the model named them.  The turn's
# routing is an optimisation, not a security boundary, but a call the model was
# *not* offered should not be given the side effects of one that it was --
# least of all a delete, a send or a write.
_NO_SILENT_RUN_PREFIXES = (
    "send_",
    "delete_",
    "remove_",
    "write_",
    "create_",
    "install_",
    "uninstall_",
    "move_",
    "copy_",
    "run_",
    "execute_",
    "shell",
    "open_browser",
    "git_commit",
    "git_push",
    "git_reset",
    "git_checkout",
)


def _is_missing_tool_error(error: Exception, tool: Any = None) -> bool:
    """
    True for ADK's failed tool lookup, and only for that.

    ADK raises exactly one ``ValueError`` with this wording, from
    ``_get_tool``, after the call fails to resolve against the declarations
    offered for the turn; it also hands the callback a placeholder ``BaseTool``
    whose description is ``Tool not found``.  Either signal is enough, so a
    reworded error message does not resurrect the crash.  A ``ValueError``
    raised *inside* a tool has to keep propagating as a tool failure.
    """
    if not isinstance(error, ValueError):
        return False
    if getattr(tool, "description", "") == "Tool not found":
        return True
    text = str(error or "")
    return "not found" in text and "Available tools:" in text


class UnroutedToolPlugin(BasePlugin):
    """
    Answers a call to a tool this turn did not offer instead of aborting.

    The model sees skill instructions that name tools ("use ``search_news``
    for news"), but only the routed skills' tools are declared.  When the
    router misses -- an unanticipated phrasing, a language the keyword lists
    do not cover -- the model still calls the tool it was told about, and ADK
    fails the entire invocation with ``Tool 'search_news' not found``.  One
    message then costs the user a traceback and no answer.

    Here the call is resolved against the skills this agent actually owns and,
    when it is a read-shaped tool, run: the user gets their answer and the log
    gets a ``routing gap`` line naming the phrase that fell through.  Anything
    else returns a normal function response saying the tool is not available
    this turn, which the model can answer from.
    """

    def __init__(
        self,
        name: str = "unrouted_tool_plugin",
        exclude_skills: Optional[Iterable[str]] = None,
        root_agent_name: Optional[str] = None,
    ):
        """
        Args:
            exclude_skills: skills handled by a sub-agent; their tools are not
                this agent's to run on its behalf.
            root_agent_name: when set, only the root agent may run a tool that
                was not offered -- a sub-agent has its own fixed toolset, so a
                miss there is a bug rather than a routing gap.
        """
        super().__init__(name=name)
        self.exclude_skills = set(exclude_skills or ())
        self.root_agent_name = root_agent_name

    async def on_tool_error_callback(
        self,
        *,
        tool: Any,
        tool_args: Dict[str, Any],
        tool_context: Any,
        error: Exception,
    ) -> Optional[Dict[str, Any]]:
        if not _is_missing_tool_error(error, tool):
            return None

        name = str(getattr(tool, "name", "") or "")
        response = await self._run_unrouted(name, dict(tool_args or {}), tool_context)
        if response is not None:
            return response
        logger.info("Model called '%s', which this turn did not offer", name)
        return {
            "error": (
                f"Tool '{name}' is not available on this turn, so it was not run. "
                "Do not call it again. Use a tool that is offered, or tell the "
                "user plainly which capability is missing and answer from the "
                "conversation so far."
            )
        }

    async def _run_unrouted(
        self, name: str, args: Dict[str, Any], tool_context: Any
    ) -> Optional[Dict[str, Any]]:
        """
        Run `name` if this agent owns it, else return None.

        Returns the tool's response as ADK would have, or an error response if
        the call itself failed -- never None for a tool that was attempted.
        """
        if not name or name.lower().startswith(_NO_SILENT_RUN_PREFIXES):
            return None
        if not self._is_root_invocation(tool_context):
            return None

        from core.harness import find_tool

        try:
            found = find_tool(name)
        except Exception:
            logger.debug("Could not look up unrouted tool %s", name, exc_info=True)
            return None
        if found is None:
            return None
        skill, fn = found
        if str(getattr(skill, "name", "")) in self.exclude_skills:
            return None

        target = getattr(fn, "func", None) or fn
        try:
            result = await self._call(target, args)
        except Exception as exc:
            logger.debug("Unrouted tool %s failed", name, exc_info=True)
            return {"error": f"Tool '{name}' failed: {type(exc).__name__}: {exc}"}

        logger.info(
            "Routing gap: ran '%s' (%s) that this turn did not offer",
            name,
            getattr(skill, "name", "?"),
        )
        return {"result": result if isinstance(result, str) else str(result)}

    @staticmethod
    async def _call(target: Any, args: Dict[str, Any]) -> Any:
        result = target(**args) if args else target()
        if inspect.isawaitable(result):
            result = await result
        return result

    def _is_root_invocation(self, tool_context: Any) -> bool:
        if not self.root_agent_name:
            return True
        try:
            invocation = tool_context.get_invocation_context()
        except Exception:
            return True
        agent_name = getattr(getattr(invocation, "agent", None), "name", None)
        return agent_name in (None, self.root_agent_name)
