"""
TraceManager — persists per-turn traces for the web frontend.

Captures every LLM call (prompt + response + tokens) and every tool call
(name + args + result) during a turn, keyed by (session_id, invocation_id).
Written to ``~/.collig/sessions/{session_id}_traces.json`` so the web UI
can render the full "thinking trace" for any message.
"""
import json
import os
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.paths import paths


_SECRET_HINTS = ("password", "secret", "key", "token", "credential")


def _mask(args: Any) -> Any:
    if not isinstance(args, dict):
        return args
    return {
        k: ("******" if any(h in k.lower() for h in _SECRET_HINTS) else v)
        for k, v in args.items()
    }


class TraceManager:
    """
    Stores one trace file per session.

    Layout of ``{session_id}_traces.json``::

        {
          "session_id": "...",
          "invocations": {
            "<invocation_id>": {
              "invocation_id": "...",
              "session_id": "...",
              "started_at": "iso",
              "finished_at": "iso",
              "user_message": "...",
              "final_answer": "...",
              "events": [
                {
                  "type": "LLM_START" | "LLM_DONE" | "TOOL_START" | "TOOL_DONE" | "FINAL",
                  "at": "iso",
                  "index": 0,
                  "ref": "llm:0" | "tool:3" | null,
                  "summary": "... optional human-readable ...",
                },
                ... ordered chronologically ...
              ],
              "llm_calls": [
                {
                  "index": 0,
                  "started_at": "iso",
                  "finished_at": "iso",
                  "duration_ms": 1234,
                  "model": "openai/gpt-4o",
                  "system_prompt": "...",
                  "messages": [{"role":"user","content":"..."}],
                  "tools": [{"name":"...","description":"...","parameters":{...}}],
                  "response_text": "...",
                  "tool_calls_planned": [{"name":"...","args":{...}}],
                  "prompt_tokens": 100,
                  "completion_tokens": 50,
                  "total_tokens": 150,
                  "error": null,
                  "raw_request": { ... full LlmRequest.model_dump() ... },
                  "raw_response": { ... full LlmResponse.model_dump() ... },
                }
              ],
              "tool_calls": [
                {
                  "index": 0,
                  "started_at": "iso",
                  "finished_at": "iso",
                  "duration_ms": 456,
                  "name": "get_weather",
                  "args": {...},
                  "result": "...",
                  "error": null
                }
              ],
              "total_prompt_tokens": 100,
              "total_completion_tokens": 50,
              "total_tokens": 150
            }
          }
        }
    """

    def __init__(self, sessions_dir: Optional[str] = None):
        self.sessions_dir = sessions_dir or paths.sessions_dir
        self._lock = threading.Lock()
        # session_id -> loaded trace data
        self._cache: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _trace_path(self, session_id: str) -> str:
        return os.path.join(self.sessions_dir, f"{session_id}_traces.json")

    def _load(self, session_id: str) -> Dict[str, Any]:
        if session_id in self._cache:
            return self._cache[session_id]
        path = self._trace_path(session_id)
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
            except Exception:
                data = None
        else:
            data = None
        if not data:
            data = {"session_id": session_id, "invocations": {}}
        self._cache[session_id] = data
        return data

    def _save(self, session_id: str, data: Dict[str, Any]) -> None:
        os.makedirs(self.sessions_dir, exist_ok=True)
        path = self._trace_path(session_id)
        self._cache[session_id] = data
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Invocation lifecycle
    # ------------------------------------------------------------------

    def start_invocation(self, session_id: str, invocation_id: str,
                         user_message: Optional[str] = None) -> None:
        with self._lock:
            data = self._load(session_id)
            data["invocations"][invocation_id] = {
                "invocation_id": invocation_id,
                "session_id": session_id,
                "started_at": datetime.now().isoformat(),
                "finished_at": None,
                "user_message": user_message,
                "final_answer": None,
                "events": [],
                "llm_calls": [],
                "tool_calls": [],
                "total_prompt_tokens": 0,
                "total_completion_tokens": 0,
                "total_tokens": 0,
            }
            self._save(session_id, data)

    def finish_invocation(self, session_id: str, invocation_id: str,
                          final_answer: Optional[str] = None) -> None:
        with self._lock:
            data = self._load(session_id)
            inv = data["invocations"].get(invocation_id)
            if inv is None:
                return
            inv["finished_at"] = datetime.now().isoformat()
            if final_answer is not None:
                inv["final_answer"] = final_answer
            try:
                inv.setdefault("events", []).append({
                    "type": "FINAL",
                    "at": datetime.now().isoformat(),
                    "index": len(inv["events"]),
                    "ref": None,
                    "summary": f"Finished. Final answer length: {len(final_answer or '')}",
                })
            except Exception:
                pass
            self._save(session_id, data)

    # ------------------------------------------------------------------
    # LLM calls
    # ------------------------------------------------------------------

    def start_llm_call(self, session_id: str, invocation_id: str,
                       model: Optional[str] = None,
                       system_prompt: Optional[str] = None,
                       messages: Optional[List[Dict]] = None,
                       tools: Optional[List[Dict]] = None,
                       raw_request: Optional[Any] = None) -> int:
        """Returns the index of the new LLM call record."""
        with self._lock:
            data = self._load(session_id)
            inv = data["invocations"].setdefault(
                invocation_id,
                {
                    "invocation_id": invocation_id,
                    "session_id": session_id,
                    "started_at": datetime.now().isoformat(),
                    "finished_at": None,
                    "user_message": None,
                    "final_answer": None,
                    "events": [],
                    "llm_calls": [],
                    "tool_calls": [],
                    "total_prompt_tokens": 0,
                    "total_completion_tokens": 0,
                    "total_tokens": 0,
                },
            )
            idx = len(inv["llm_calls"])

            # --- serialize raw request, keeping size bounded ---
            raw_request_safe = None
            _prompt_fallback = {
                "_note": "Structured fallback (LlmRequest.model_dump was empty or unavailable).",
                "model": model,
                "system_instruction": system_prompt,
                "contents": messages,
                "tools_declared": tools,
            }
            if raw_request is not None:
                try:
                    if hasattr(raw_request, "model_dump"):
                        raw_request_safe = raw_request.model_dump(mode="json")
                    else:
                        raw_request_safe = raw_request
                    # Guard against empty/sparse model_dump output (some providers
                    # strip nested types in JSON mode). If the result is hollow,
                    # fall back to our structured copy so the UI always has
                    # something inspectable for token accounting.
                    if isinstance(raw_request_safe, dict):
                        non_empty = sum(
                            1 for v in raw_request_safe.values()
                            if v not in (None, "", [], {})
                        )
                        if non_empty == 0:
                            raw_request_safe = dict(_prompt_fallback)
                    # Validate serializable + cap huge fields via quick JSON dump
                    s = json.dumps(raw_request_safe, default=str)
                    if len(s) > 512 * 1024:  # 512KB cap per raw request
                        # Strip out the heaviest known nested buckets first
                        def _cap(x):
                            if isinstance(x, dict):
                                return {k: _cap(v) for k, v in x.items() if len(k) < 200}
                            if isinstance(x, list):
                                if len(x) > 200:
                                    x = x[:200] + ["... [truncated list]"]
                                return [_cap(v) for v in x]
                            if isinstance(x, str) and len(x) > 64 * 1024:
                                return x[:65536] + "... [truncated large string]"
                            return x
                        raw_request_safe = _cap(raw_request_safe)
                except Exception as e:
                    raw_request_safe = {
                        **_prompt_fallback,
                        "_serialization_error": str(e),
                    }
            else:
                raw_request_safe = dict(_prompt_fallback)

            inv["llm_calls"].append({
                "index": idx,
                "started_at": datetime.now().isoformat(),
                "_started_monotonic": time.monotonic(),
                "finished_at": None,
                "duration_ms": None,
                "model": model,
                "system_prompt": system_prompt,
                "messages": messages or [],
                "tools": tools or [],
                "response_text": None,
                "tool_calls_planned": [],
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "error": None,
                "raw_request": raw_request_safe,
                "raw_response": None,
            })
            try:
                inv.setdefault("events", []).append({
                    "type": "LLM_START",
                    "at": datetime.now().isoformat(),
                    "index": len(inv["events"]),
                    "ref": f"llm:{idx}",
                    "summary": f"LLM call #{idx + 1} to {model or '(unknown model)'}. "
                               f"{len(messages or [])} message(s), "
                               f"{len(tools or [])} tool(s) offered.",
                })
            except Exception:
                pass
            self._save(session_id, data)
            return idx

    def finish_llm_call(self, session_id: str, invocation_id: str, index: int,
                        response_text: Optional[str] = None,
                        tool_calls_planned: Optional[List[Dict]] = None,
                        prompt_tokens: int = 0,
                        completion_tokens: int = 0,
                        total_tokens: int = 0,
                        error: Optional[str] = None,
                        raw_response: Optional[Any] = None) -> None:
        with self._lock:
            data = self._load(session_id)
            inv = data["invocations"].get(invocation_id)
            if inv is None or index >= len(inv["llm_calls"]):
                return
            call = inv["llm_calls"][index]
            call["finished_at"] = datetime.now().isoformat()
            started = call.pop("_started_monotonic", None)
            if started is not None:
                call["duration_ms"] = int((time.monotonic() - started) * 1000)
            if response_text is not None:
                call["response_text"] = response_text
            if tool_calls_planned is not None:
                call["tool_calls_planned"] = [
                    {"name": tc.get("name"), "args": _mask(tc.get("args") or {})}
                    for tc in tool_calls_planned
                ]
            call["prompt_tokens"] = prompt_tokens
            call["completion_tokens"] = completion_tokens
            call["total_tokens"] = total_tokens
            if error is not None:
                call["error"] = str(error)
            inv["total_prompt_tokens"] += prompt_tokens
            inv["total_completion_tokens"] += completion_tokens
            inv["total_tokens"] += total_tokens

            # --- serialize raw response, bounded ---
            raw_response_safe = None
            _resp_fallback = {
                "_note": "Structured fallback (LlmResponse.model_dump was empty or unavailable).",
                "response_text": response_text,
                "tool_calls_planned": tool_calls_planned or [],
                "usage_metadata": {
                    "prompt_token_count": prompt_tokens,
                    "candidates_token_count": completion_tokens,
                    "total_tokens": total_tokens,
                },
                "error": error,
            }
            if raw_response is not None:
                try:
                    if hasattr(raw_response, "model_dump"):
                        raw_response_safe = raw_response.model_dump(mode="json")
                    else:
                        raw_response_safe = raw_response
                    # Same sparse-dump guard as the request side: if the Pydantic
                    # dump came back hollow, swap in our structured copy.
                    if isinstance(raw_response_safe, dict):
                        non_empty = sum(
                            1 for v in raw_response_safe.values()
                            if v not in (None, "", [], {})
                        )
                        if non_empty == 0:
                            raw_response_safe = dict(_resp_fallback)
                    s = json.dumps(raw_response_safe, default=str)
                    if len(s) > 512 * 1024:
                        def _cap(x):
                            if isinstance(x, dict):
                                return {k: _cap(v) for k, v in x.items() if len(k) < 200}
                            if isinstance(x, list):
                                if len(x) > 200:
                                    x = x[:200] + ["... [truncated list]"]
                                return [_cap(v) for v in x]
                            if isinstance(x, str) and len(x) > 64 * 1024:
                                return x[:65536] + "... [truncated large string]"
                            return x
                        raw_response_safe = _cap(raw_response_safe)
                except Exception as e:
                    raw_response_safe = {
                        **_resp_fallback,
                        "_serialization_error": str(e),
                    }
            else:
                raw_response_safe = dict(_resp_fallback)
            call["raw_response"] = raw_response_safe

            try:
                ntc = len(call.get("tool_calls_planned") or [])
                inv.setdefault("events", []).append({
                    "type": "LLM_DONE",
                    "at": datetime.now().isoformat(),
                    "index": len(inv["events"]),
                    "ref": f"llm:{index}",
                    "summary": f"LLM call #{index + 1} done. "
                               f"{prompt_tokens}→{completion_tokens} tok. "
                               f"Planned tool calls: {ntc}. "
                               + (f"Error: {error}" if error else f"Response length: {len(response_text or '')}"),
                })
            except Exception:
                pass
            self._save(session_id, data)

    # ------------------------------------------------------------------
    # Tool calls
    # ------------------------------------------------------------------

    def start_tool_call(self, session_id: str, invocation_id: str,
                        name: str, args: Optional[Dict] = None) -> int:
        with self._lock:
            data = self._load(session_id)
            inv = data["invocations"].setdefault(
                invocation_id,
                {
                    "invocation_id": invocation_id,
                    "session_id": session_id,
                    "started_at": datetime.now().isoformat(),
                    "finished_at": None,
                    "user_message": None,
                    "final_answer": None,
                    "events": [],
                    "llm_calls": [],
                    "tool_calls": [],
                    "total_prompt_tokens": 0,
                    "total_completion_tokens": 0,
                    "total_tokens": 0,
                },
            )
            idx = len(inv["tool_calls"])
            inv["tool_calls"].append({
                "index": idx,
                "started_at": datetime.now().isoformat(),
                "_started_monotonic": time.monotonic(),
                "finished_at": None,
                "duration_ms": None,
                "name": name,
                "args": _mask(args or {}),
                "result": None,
                "error": None,
            })
            try:
                inv.setdefault("events", []).append({
                    "type": "TOOL_START",
                    "at": datetime.now().isoformat(),
                    "index": len(inv["events"]),
                    "ref": f"tool:{idx}",
                    "summary": f"Tool #{idx + 1} `{name}` start. Args keys: {sorted(list((args or {}).keys()))[:10]}.",
                })
            except Exception:
                pass
            self._save(session_id, data)
            return idx

    def finish_tool_call(self, session_id: str, invocation_id: str, index: int,
                         result: Any = None, error: Optional[str] = None) -> None:
        with self._lock:
            data = self._load(session_id)
            inv = data["invocations"].get(invocation_id)
            if inv is None or index >= len(inv["tool_calls"]):
                return
            tc = inv["tool_calls"][index]
            tc["finished_at"] = datetime.now().isoformat()
            started = tc.pop("_started_monotonic", None)
            if started is not None:
                tc["duration_ms"] = int((time.monotonic() - started) * 1000)
            try:
                s = json.dumps(result, default=str)
            except Exception:
                s = str(result)
            if len(s) > 20000:
                s = s[:20000] + "... [truncated]"
            tc["result"] = s
            if error is not None:
                tc["error"] = str(error)
            try:
                inv.setdefault("events", []).append({
                    "type": "TOOL_DONE",
                    "at": datetime.now().isoformat(),
                    "index": len(inv["events"]),
                    "ref": f"tool:{index}",
                    "summary": f"Tool #{index + 1} `{tc['name']}` done. "
                               f"Duration {tc['duration_ms']} ms. "
                               + (f"Error: {error}" if error else f"Result length: {len(s)}"),
                })
            except Exception:
                pass
            self._save(session_id, data)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_session_traces(self, session_id: str) -> Dict[str, Any]:
        """Return the trace file contents for a session (empty if none)."""
        with self._lock:
            return self._load(session_id)

    def get_invocation_trace(self, session_id: str,
                             invocation_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            data = self._load(session_id)
            return data["invocations"].get(invocation_id)

    def list_invocation_summaries(self, session_id: str) -> List[Dict[str, Any]]:
        """Lightweight list suitable for a trace sidebar."""
        with self._lock:
            data = self._load(session_id)
        result = []
        for inv_id, inv in data["invocations"].items():
            result.append({
                "invocation_id": inv_id,
                "started_at": inv.get("started_at"),
                "finished_at": inv.get("finished_at"),
                "user_message_preview": (inv.get("user_message") or "")[:200],
                "llm_call_count": len(inv.get("llm_calls", [])),
                "tool_call_count": len(inv.get("tool_calls", [])),
                "total_tokens": inv.get("total_tokens", 0),
            })
        result.sort(key=lambda r: r.get("started_at") or "")
        return result


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_trace_manager: Optional[TraceManager] = None
_trace_lock = threading.Lock()


def get_trace_manager() -> TraceManager:
    """Process-wide TraceManager over ``~/.collig/sessions``."""
    global _trace_manager
    if _trace_manager is None:
        with _trace_lock:
            if _trace_manager is None:
                _trace_manager = TraceManager()
    return _trace_manager
