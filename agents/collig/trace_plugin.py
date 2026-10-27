"""
ADK Plugin that records LLM calls and tool calls into the TraceManager.

Registered in ``agents/collig/agent.py`` alongside the token-stats plugin so
every turn automatically captures its prompt, tool plans and tool results
for the web trace viewer.
"""
import logging
from typing import Any, Dict, List, Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin

from core.trace_manager import get_trace_manager

logger = logging.getLogger(__name__)


class TracePlugin(BasePlugin):
    """
    Wires the ADK event stream into :class:`TraceManager`.

    Hooks used:

    * ``before_run_callback`` — start an invocation bucket, record the user message.
    * ``before_model_callback`` — record the prompt, system instruction and
      tool schemas that are about to be sent.
    * ``after_model_callback`` — record the response text, planned tool calls
      and reported token usage.
    * ``before_tool_callback`` — record a tool's name and masked arguments.
    * ``after_tool_callback`` — record the tool result or error.
    * ``after_run_callback`` — close the invocation bucket with the final answer.
    * ``on_run_error_callback`` — close the invocation bucket on failure.
    """

    def __init__(self, name: str = "trace_plugin"):
        super().__init__(name=name)
        # invocation_id -> index of pending llm call (None between calls)
        self._pending_llm: Dict[str, Optional[int]] = {}
        # invocation_id -> { tool_call_id: (tool_index, session_id) }
        self._pending_tools: Dict[str, Dict[str, tuple]] = {}
        # invocation_id -> session_id for quick lookup
        self._inv_session: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------

    async def before_run_callback(self, *, invocation_context: InvocationContext):
        invocation_id = invocation_context.invocation_id
        session_id = invocation_context.session.id
        self._inv_session[invocation_id] = session_id
        self._pending_llm[invocation_id] = None
        self._pending_tools[invocation_id] = {}

        user_message = None
        content = invocation_context.user_content
        if content and content.parts:
            user_message = " ".join(
                p.text for p in content.parts if getattr(p, "text", None)
            )
        try:
            get_trace_manager().start_invocation(
                session_id, invocation_id, user_message=user_message
            )
        except Exception as e:
            logger.warning("Trace: failed to start invocation: %s", e)
        return None

    async def after_run_callback(self, *, invocation_context: InvocationContext):
        invocation_id = invocation_context.invocation_id
        session_id = self._inv_session.pop(invocation_id, None)
        self._pending_llm.pop(invocation_id, None)
        self._pending_tools.pop(invocation_id, None)
        if session_id is None:
            return None

        final_answer = None
        try:
            events = invocation_context.session.events
            if events:
                for ev in reversed(events):
                    if ev.author != "user" and ev.content and ev.content.parts:
                        parts = [
                            p.text for p in ev.content.parts
                            if getattr(p, "text", None) and not getattr(p, "thought", False)
                        ]
                        if parts:
                            final_answer = "".join(parts)
                            break
        except Exception:
            pass

        try:
            get_trace_manager().finish_invocation(
                session_id, invocation_id, final_answer=final_answer
            )
        except Exception as e:
            logger.warning("Trace: failed to finish invocation: %s", e)
        return None

    async def on_run_error_callback(self, *, invocation_context: InvocationContext,
                                    error: Exception):
        invocation_id = invocation_context.invocation_id
        session_id = self._inv_session.pop(invocation_id, None)
        self._pending_llm.pop(invocation_id, None)
        self._pending_tools.pop(invocation_id, None)
        if session_id is None:
            return None
        try:
            get_trace_manager().finish_invocation(
                session_id, invocation_id,
                final_answer=f"[Error] {error}",
            )
        except Exception as e:
            logger.warning("Trace: failed to finish error invocation: %s", e)
        return None

    # ------------------------------------------------------------------
    # LLM calls
    # ------------------------------------------------------------------

    async def before_model_callback(self, *, callback_context: CallbackContext,
                                    llm_request: LlmRequest) -> None:
        invocation_id = callback_context.invocation_id
        session_id = self._inv_session.get(invocation_id)
        if session_id is None:
            return None

        model_name = None
        try:
            model_name = getattr(llm_request, "model", None) or ""
            if not model_name:
                prov = callback_context.provider
                model_name = getattr(prov, "model", None) or getattr(prov, "name", "") or ""
        except Exception:
            pass

        system_prompt = None
        messages: List[Dict] = []
        try:
            if llm_request.system_instruction:
                parts = llm_request.system_instruction.parts or []
                system_prompt = "\n".join(
                    p.text for p in parts if getattr(p, "text", None)
                )
            for c in llm_request.contents or []:
                role = getattr(c, "role", "user")
                text_parts = [
                    p.text for p in (c.parts or [])
                    if getattr(p, "text", None)
                ]
                content_text = "".join(text_parts)
                if content_text:
                    messages.append({"role": role, "content": content_text})
        except Exception:
            pass

        tools: List[Dict] = []
        try:
            tool_list = getattr(llm_request.config, "tools", None) if llm_request.config else None
            for t in (tool_list or []):
                fn = getattr(t, "function_declaration", None)
                if fn is not None:
                    tools.append({
                        "name": getattr(fn, "name", ""),
                        "description": getattr(fn, "description", ""),
                        "parameters": getattr(fn, "parameters", None),
                    })
        except Exception:
            pass

        try:
            idx = get_trace_manager().start_llm_call(
                session_id, invocation_id,
                model=model_name,
                system_prompt=system_prompt,
                messages=messages,
                tools=tools,
                raw_request=llm_request,
            )
            self._pending_llm[invocation_id] = idx
        except Exception as e:
            logger.warning("Trace: failed to start LLM call: %s", e)
        return None

    async def after_model_callback(self, *, callback_context: CallbackContext,
                                   llm_response: LlmResponse):
        invocation_id = callback_context.invocation_id
        session_id = self._inv_session.get(invocation_id)
        idx = self._pending_llm.get(invocation_id)
        if session_id is None or idx is None:
            return None

        response_text = ""
        tool_calls_planned: List[Dict] = []
        try:
            if llm_response.content and llm_response.content.parts:
                text_parts = []
                for p in llm_response.content.parts:
                    if getattr(p, "text", None) and not getattr(p, "thought", False):
                        text_parts.append(p.text)
                    fc = getattr(p, "function_call", None)
                    if fc is not None:
                        tool_calls_planned.append({
                            "name": getattr(fc, "name", ""),
                            "args": getattr(fc, "args", None) or {},
                        })
                response_text = "".join(text_parts)
        except Exception:
            pass

        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        try:
            usage = llm_response.usage_metadata
            if usage is not None:
                prompt_tokens = usage.prompt_token_count or 0
                completion = (usage.candidates_token_count or 0) + (
                    getattr(usage, "thoughts_token_count", None) or 0
                )
                completion_tokens = completion
                total_tokens = prompt_tokens + completion_tokens
        except Exception:
            pass

        try:
            get_trace_manager().finish_llm_call(
                session_id, invocation_id, idx,
                response_text=response_text,
                tool_calls_planned=tool_calls_planned,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                raw_response=llm_response,
            )
        except Exception as e:
            logger.warning("Trace: failed to finish LLM call: %s", e)

        self._pending_llm[invocation_id] = None
        return None

    # ------------------------------------------------------------------
    # Tool calls
    # ------------------------------------------------------------------

    async def before_tool_callback(self, *, tool: Any, tool_args: Dict[str, Any],
                                   tool_context: Any) -> None:
        invocation_id = tool_context.invocation_id
        session_id = self._inv_session.get(invocation_id) or tool_context.session.id
        if session_id is None:
            return None

        try:
            name = getattr(tool, "name", "") or ""
            args = dict(tool_args or {})
            call_id = getattr(tool_context, "function_call_id", None) or f"{name}-{id(tool)}"
            idx = get_trace_manager().start_tool_call(
                session_id, invocation_id, name=name, args=args,
            )
            self._pending_tools.setdefault(invocation_id, {})[call_id] = (idx, session_id)
        except Exception as e:
            logger.warning("Trace: failed to start tool call: %s", e)
        return None

    async def after_tool_callback(self, *, tool: Any, tool_args: Dict[str, Any],
                                  tool_context: Any, result: Any) -> None:
        invocation_id = tool_context.invocation_id
        name = getattr(tool, "name", "") or ""
        call_id = getattr(tool_context, "function_call_id", None) or f"{name}-{id(tool)}"
        pending = self._pending_tools.get(invocation_id) or {}
        entry = pending.pop(call_id, None)
        if entry is None:
            return None
        idx, session_id = entry

        try:
            get_trace_manager().finish_tool_call(
                session_id, invocation_id, idx,
                result=result, error=None,
            )
        except Exception as e:
            logger.warning("Trace: failed to finish tool call: %s", e)
        return None
