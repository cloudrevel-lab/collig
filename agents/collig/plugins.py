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
"""
import logging
from collections import OrderedDict
from typing import Any, Dict, Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin

from core.runtime import get_token_stats_manager

from .toolsets import is_trivial_query, text_of

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
        if not is_trivial_query(text_of(callback_context)):
            return None
        if llm_request.config is not None:
            llm_request.config.tools = None
            llm_request.config.tool_config = None
        llm_request.tools_dict = {}
        return None
