# Collig Investigation & Improvement Plan

Date: 2026-10-27

This document records the architecture review behind the current fixes, the
root causes of the reported issues, what changed, and what is still worth
doing. It is intentionally concrete: file paths and symptoms, not generic
advice.

---

## 1. Executive summary

Collig grew two agent stacks side by side:

1. **Legacy LangChain/LangGraph** in `core/agent.py`, used by `make pa`.
2. **Google ADK harness** in `agents/collig/` + `core/runner.py`, used by the
   web console.

That split explains most of the reported symptoms. The CLI was not using the
per-turn tool selection, trace plugins or sub-agents that already existed for
the web. In addition, the ADK tool adapter wrapped LangChain
`StructuredTool` objects directly, which ADK cannot introspect (it raises
`TypeError: unhashable type: 'StructuredTool'`). Tool calls in the harness
therefore failed silently or aborted the turn.

The current pass unifies the CLI on the ADK harness, fixes the tool adapter,
makes skills lazy, adds an intent router and direct tool/shell shortcuts,
rebuilds the /config UI around provider pages, and adds a structured thinking
timeline.

Measured locally:

| Metric | Before | After |
| --- | --- | --- |
| Skill registry build | ~10 s (Bookmarks called the embeddings API) | ~0.8 s |
| Tools catalogued at startup | 58 imported tools | 58 metadata stubs, 0 skill modules loaded |
| Tools sent for "what time is it?" | 58 (legacy fallback / broken harness) | 1 (Time) |
| Time query | model + tool, plugin crash after tool | model + 1 tool, final answer, structured trace |

---

## 2. Architecture findings

### 2.1 Two stacks, duplicated provider logic (high)

- `core/agent.py` builds a LangChain ReAct graph. It re-creates the graph
  whenever the filtered tool list changes.
- `core/runner.py` + `agents/collig/*` build one ADK `App` and narrow tools
  per turn through `SkillToolset`.
- Provider/model/key resolution existed twice (`core/agent.py` and
  `agents/collig/providers.py`), so a change in one path did not reach the
  other.

**Impact:** inconsistent behaviour between CLI and web, duplicated bugs, and
two different definitions of "thinking".

**Fix:** the CLI now imports `core.runner.get_agent()`. The ADK harness is the
single execution engine for both surfaces.

### 2.2 ADK tool adapter was broken (critical)

`agents/collig/toolsets.py` did:

```python
FunctionTool(fn)   # fn is a LangChain StructuredTool
```

ADK's `FunctionTool` reads `__name__`, the signature and the docstring, and
requires a hashable callable. `StructuredTool` is unhashable, so every skill
with tools failed to load into the ADK toolset. Per-skill `except` blocks hid
the error.

**Fix:** `skills.tooling.as_adk_function()` unwraps the original function from
`StructuredTool.func` (or `.coroutine`), preserving name/description, and all
ADK call sites use it.

### 2.3 Skills were eagerly imported and configured (high)

`core/runtime._build_skill_manager()` imported every skill class. Each
`configure()` ran immediately, and the Bookmarks skill called
`embed_query("test")`, which made a network request at startup. This is where
the multi-second cold start came from.

**Fix:** `skills.base.LazySkill` reads only `SKILL.md` metadata (name,
description, triggers, tool names, required config) at registration time. The
real class is imported on first `get_tools()`. `AgentService.tools` now returns
lightweight `ToolStub` objects for the CLI completer and the web Skills page,
so neither forces the registry open. `/api/skills` uses `tool_metadata()` too.

### 2.4 Tool selection had drifted (high)

The legacy `_filter_tools_for_message` mapped keywords to categories and then
to a hand-written list of tool-name prefixes. New skills (jira, web_search)
were not added to the prefix map, so they disappeared from the filtered set;
several prefixes named tools that no longer exist.

**Fix:** `core/harness.route_message()` scores skills, not tools. It uses:
- exact tool-name matches (strongest),
- the skill's own `SKILL.md` triggers,
- curated keywords,
- the skill name in the message.

Only the clear winner(s) survive. A trivial message gets no tools; an
open-ended message also gets no tools rather than an arbitrary default trio.

### 2.5 Provider config was not actually provider-scoped in the CLI (high)

`get_config_schema()` listed every provider's key, endpoint and model in one
flat list. Selecting DeepSeek therefore still showed DashScope rows.

**Fix:** `core/config_ui.py` implements a screen stack:

```
Root -> Model Provider -> OpenAI | DeepSeek | DashScope | Ollama | Llama | Custom
```

Each provider page shows only that provider's key, URL/region, model and cached
models. Escape goes up one level; only the root quits. Per-provider values are
stored under `{PROVIDER}_KEY` / `{PROVIDER}_URL` / `{PROVIDER}_MODEL` /
`{PROVIDER}_AVAILABLE_MODELS`.

### 2.6 Provider switches did not persist (medium)

`core/runner.AgentService.set_provider()` called `update_config(LLM_PROVIDER=…,
LLM_MODEL=…)` but `get_provider_model()` prefers the newer `provider` /
`llm_model` aliases. The next start therefore reverted to the old provider.

**Fix:** `set_provider()` now writes through `set_llm_field()`, including the
target provider's key, URL and model, and saves the config.

### 2.7 Web skill toggles did not persist (medium)

`PUT /api/skills/toggle` set `skill.enabled` but saved an unchanged config, so
the toggle was lost on restart.

**Fix:** it now writes `SKILL_<NAME>_ENABLED` before saving.

### 2.8 Thinking output was a flat wall of text (medium)

The legacy path printed "Reasoning:", "Planning to use tool:", "Args:" and
"Tool executed" as unrelated lines. It did not show the intent, the selected
skills, the tool duration or the answering phase.

**Fix:** `core/thinking.py` renders a live timeline with Understanding,
Skills, Thinking, Plan, Tool and Responding steps, including durations. It is
disabled automatically on non-TTY surfaces (web server, piped --prompt) so it
does not pollute logs.

### 2.9 No shell escape (medium)

`/run <cmd>` existed, but it was not discoverable and used a separate command
style.

**Fix:** `!<cmd>` runs a real shell command, streams output, reports the exit
code, and supports `!cd` in-process. `/get_current_time` and other tool names
can also be invoked directly as `/<tool>` with no model call.

### 2.10 Trace plugin was incompatible with ADK 2.7 (high)

After the tool wrapper was fixed, the next failure was:

```
TracePlugin.before_tool_callback() got an unexpected keyword argument 'tool'
```

ADK 2.7 calls tool callbacks with `tool`, `tool_args`, `tool_context` and
`result`; the plugin still used the older `tool_call` / `tool_response` shape.

**Fix:** updated `agents/collig/trace_plugin.py` to the current ADK signatures
and used `tool_context.invocation_id` / `function_call_id`.

### 2.11 Web data endpoints broke on LazySkill (high)

This one showed up as "my bookmarks and notes are gone" in the web UI. The
Chroma databases were intact (40 bookmarks, 17 notes, 2 diary entries under
`~/.collig/data/`), but `/api/bookmarks`, `/api/notes` and `/api/diary` all
returned empty lists.

The API helpers read `skill.vectorstore` directly. After the lazy-skill
refactor the manager returned a `LazySkill`, which deliberately has no
`vectorstore` until its module is imported, so the guard
`if not getattr(skill, "vectorstore", None)` returned early.

**Fix:** added `Skill.ensure_loaded()` (a no-op for concrete skills) and
overrode it in `LazySkill`. The web helpers now call it before reading
skill-specific attributes. Verified against the live server:

```
/api/bookmarks -> total 40
/api/notes     -> total 17
/api/diary     -> total 2
```

---

## 3. What changed in this pass

| Area | Files |
| --- | --- |
| Lazy skills + tool metadata | `skills/base.py`, `core/runtime.py`, `skills/manager.py` |
| ADK tool adapter | `skills/tooling.py`, `agents/collig/toolsets.py` |
| Intent router, shell, direct tools | `core/harness.py` |
| Thinking timeline | `core/thinking.py`, `core/runner.py` |
| CLI on ADK harness | `core/cli.py` |
| Provider-scoped config UI | `core/config_ui.py`, `core/runtime.py` |
| Trace/token plugin compatibility | `agents/collig/trace_plugin.py` |
| Startup network call removal | `skills/bookmark/__init__.py` |
| Skill metadata quality | `skills/jira/SKILL.md`, `skills/date_calculator/SKILL.md` |
| Tests | `tests/test_harness.py` |

---

## 4. Remaining improvements

### P0 - correctness and trust

1. **Permission layer for destructive tools.** Filesystem delete/write, git
   push, email send and shell commands should require an explicit approval
   mode (allow once / allow for session / deny), with a visible diff or command
   preview. The current harness executes immediately.
2. **Shell sandbox boundaries.** `!` and the filesystem tools currently run
   with the user's full permissions. Add a workspace root, deny-list and an
   audit log.
3. **One source of truth for provider metadata.** `agents/collig/providers.py`
   and `core/config_ui.py` both define provider tables and DashScope regions.
   Move them to `core/runtime.py` (or a `providers.json`) so adding a provider
   is one edit.
4. **Model capability detection.** Context window, tool-calling support and
   reasoning behaviour are guessed. Cache capabilities per model and fall back
   safely (some local models do not support tools).

### P1 - agent quality and cost

5. **Semantic / embedding router.** The current router is lexical. For
   ambiguous requests ("clean up the repo", "what's on my plate?") a small
   local embedding index over skill descriptions would be more robust than
   more keywords. Keep lexical as the deterministic fallback.
6. **Two-stage tool exposure.** For large skills (Jira, email), first expose a
   single `describe_skill` tool and only inject the full schema after the model
   asks. This is the pattern the ADK harness already enables.
7. **Prompt/token budgets.** Add a per-turn budget: context window, max tool
   schemas, max sub-agent transfers. The time query still reported ~3.7k
   prompt tokens; most is system prompt and sub-agent descriptions, not tools.
8. **Better conversation memory.** Replace the JSON session mirror with the
   ADK SQLite store as the only source; keep a migration command for old files.
9. **Trace viewer in the CLI.** `/trace` (last invocation) with the same
   timeline the web Trace panel shows.

### P1 - UX

10. **Streaming answer + thinking in one view.** The current Live block stops
    before the answer streams. A single renderer could show the thinking block
    and then append answer tokens below it without flicker.
11. **Keyboard help.** A `?` overlay for /config and the main prompt; the
    footer is currently the only discoverability.
12. **Provider test from the provider page.** The web Settings page has a
    connection test; the CLI detail page should offer `t` too.
13. **Config diff/preview.** Before `s` saves, show exactly which keys change
    (masked), especially when switching the active provider.

### P2 - product features

14. **MCP client.** Collig's skill system is custom. Supporting Model Context
    Protocol servers would unlock a large ecosystem and avoid one-off
    integrations.
15. **Sub-agent delegation UI.** The ADK stack already has jira/email/survey
    specialists. Surface transfers as explicit cards ("Delegating to
    jira_agent") and allow the user to approve or cancel.
16. **Scheduled / background tasks.** "Every morning, summarise my Jira
    sprint" is a natural fit for the session store plus a scheduler.
17. **Skill marketplace / install flow.** `skills/imported` is a manual
    directory. A signed bundle format, version pinning and an install command
    would make the README's "drop a SKILL.md" story production-ready.
18. **Evaluation harness.** A small set of golden prompts per skill (tool
    chosen, no tool for trivia, correct arguments) would catch router and
    adapter regressions like the `StructuredTool` bug.
19. **Voice / dictation and image input.** Useful for a personal co-worker;
    the provider abstraction already supports multimodal models.
20. **Crash-safe config writes.** Write config.json atomically (temp file +
    rename) and keep a rolling backup; a half-written config currently makes
    the next start fall back to defaults.

---

## 5. How to verify

```bash
# Harness/router/lazy-skill/config-scoping tests
uv run python tests/test_harness.py

# Existing provider/config round-trip tests
uv run python tests/test_llm_config_menu.py

# One real turn through the ADK harness
uv run python core/cli.py --prompt "What time is it? Use the tool."

# Direct tool shortcut (no model call) and shell escape are available
# interactively after "make pa":
#   /get_current_time
#   !pwd
#   /config
```

The interactive /config stack is:

- `Esc` in a provider page -> provider list.
- `Esc` in the provider list -> root.
- `Esc` at root -> quit (with a save prompt if dirty).
- `q` / `Ctrl+C` -> quit from anywhere.

---

## 6. Notes for the next contributor

- Do not add a new skill by editing a keyword list. Put `triggers` and `tools`
  in its `SKILL.md`; the router and the web Skills page read that metadata.
- Keep heavy imports and network calls out of `Skill.__init__` and
  `configure()`. LazySkill calls `configure()` when the skill is first
  selected; that is allowed to be expensive, but startup is not.
- When adding an ADK plugin hook, check `google.adk.plugins.base_plugin`
  signatures for the installed ADK version. The tool hook changed between
  versions.
- Prefer `core.runtime.set_llm_field()` over writing `LLM_PROVIDER` /
  `LLM_MODEL` directly; the flat aliases are what the next start reads.
