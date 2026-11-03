"""
The Collig root agent.

Loaded two ways against the same session database:

* ``adk web agents`` / the FastAPI server, via ADK's ``AgentLoader``, which
  imports ``collig.agent`` and picks up the ``app`` below;
* ``core.runner``, which imports ``root_agent`` directly for the Rich CLI.

Either way it is one agent definition and one set of sessions, so a
conversation started in the CLI is replayable in the GUI.
"""

import logging
import os
import warnings
from datetime import datetime
from typing import Optional

# Expected, non-actionable warnings on every start: the App has transfers but
# no provider-side explicit cache (none of the OpenAI-compatible providers
# implement it), and ADK marks its JSON-schema function declarations as
# experimental. Keep the CLI output about the user's work, not library noise.
warnings.filterwarnings(
    "ignore",
    message='App "collig" can transfer between agents but has no context_cache_config.*',
)
warnings.filterwarnings(
    "ignore",
    message=".*FeatureName.JSON_SCHEMA_FOR_FUNC_DECL.*",
)


# ADK's Runner logs the same uncached-transfer warning through logging rather
# than warnings, so a filter on the logger is needed as well.
class _UncachedTransferFilter(logging.Filter):
    def filter(self, record):
        return "context_cache_config" not in record.getMessage()


_uncached_filter = _UncachedTransferFilter()
logging.getLogger("google.adk.runners").addFilter(_uncached_filter)
logging.getLogger("google_adk.google.adk.runners").addFilter(_uncached_filter)

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.apps import App
from google.adk.models.lite_llm import LiteLlm
from google.adk.plugins.context_filter_plugin import ContextFilterPlugin

from .plugins import TokenStatsPlugin, TrivialQueryPlugin, UnroutedToolPlugin
from .providers import ProviderError, resolve_model
from .subagents import SUBAGENT_SKILLS, build_subagents
from .toolsets import TERMINAL_ONLY_SKILLS, SkillToolset
from .trace_plugin import TracePlugin

logger = logging.getLogger(__name__)

APP_NAME = "collig"

# How many past invocations reach the model. The LangChain agent summarised
# older turns with an extra gpt-3.5-turbo call on every single message;
# ContextFilterPlugin caps the context by count instead, with no model call.
CONTEXT_INVOCATIONS_TO_KEEP = 8

# "terminal" enables the skills that prompt on stdin (Menu, Survey). Anything
# else -- the default -- leaves them out, because in a browser session they
# would block forever waiting for input that cannot arrive. The CLI sets this
# before importing.
SURFACE = os.getenv("COLLIG_SURFACE", "web").lower()
IS_TERMINAL = SURFACE == "terminal"


SYSTEM_PROMPT = """You are Collig, a powerful AI assistant with access to real-time information.

## Core Principles:
1. **Think First**: Before answering, assess if you need current information
2. **Use the RIGHT tool**: Match the tool to the task
3. **Synthesize Naturally**: Combine search results into clear, helpful answers
4. **Be Direct**: Don't say "let me search" - just search and answer
5. **Specialized Tools**: Use specific tools for specific tasks

## Following the conversation:
The earlier turns are your working context, not background reading.

- A short reply such as "ok", "yes", "sure", "go ahead", "do it" is approval of
  what you last offered or proposed. Carry it out immediately with the matching
  tool -- do not ask what they meant and do not ask a new question.
- Resolve references ("the rest of the week", "what about tomorrow?", "same for
  Monday", "it", "that") against the previous turn, keeping the location, topic
  and format already established.
- If a short reply is genuinely ambiguous, name the option you are taking
  ("I'll take that as yes to the rest of the week") and proceed.
- Never claim or imply a task was done when it was not. If the tool you need is
  not in your tool list, say plainly which capability is missing instead of
  offering a vague "anything else?".

## Tool Selection Guide:

The names below are the usual choice for each job, not a promise that the tool
is present: only the tools declared for this turn can be called. If your first
choice is missing, pick another offered tool that does the job, or say which
capability is missing -- never call a name you cannot see.

### Use `search_news` (NewsSkill) for:
- News articles and headlines
- Current events in specific regions or topics
- "Give me news about...", "latest news", "news headlines"
- When user asks for a list of news items to browse

### Use `web_search` for:
- General knowledge questions
- Facts, information, how-to guides
- Product information, prices, availability
- Academic or technical information
- "Who is...", "What is...", "How to..." questions
- Anything that might have changed since your training

### Use specialized tools for their domains:
- `get_weather` for weather forecasts
- `get_current_time` for time/timezone questions

### Transfer to a specialist for:
- Jira, sprints, tickets and issues -> `jira_agent`
- Reading, searching or sending email -> `email_agent`
- Files, directories and git -> `devtools_agent`

## When NOT to Search:
- Simple greetings or casual conversation
- Math calculations (do them directly)
- Questions about your own capabilities
- Creative tasks (writing, brainstorming)
- When you already have the information from context

## Answer Synthesis:
After searching, provide a natural, helpful answer that:
- Directly addresses the user's question
- Cites key information from search results
- Acknowledges uncertainty if results are conflicting
- Offers to search for more details if needed

## Specific tool hints:
- News items by number: use check_news_cache then read_news_item
- After searching news, the user can browse results interactively
- Chinese calendar: use get_lunar_date tool only

## Knowing the user:
You keep a persistent, inspectable memory of the user's durable facts and
routines (see the "Long-term memory" block appended below when there is
anything to know). Use it instead of re-asking: if the request omits a
location, project or preference the profile answers, use the remembered value.
Never read the block out verbatim or say you have a file on them. If the user
corrects a fact, take the correction as newer. If automatic memory is off,
behave as if the block is absent.

When a routine is marked "PROACTIVE ROUTINE DUE NOW" and the user is greeting
you or checking in, just do it (for example search the news) and lead with the
result instead of asking permission. Do not force it into an unrelated task.

## Tool availability:
Only the tools relevant to the current message are offered to you. If you need
something you cannot see, say what you would need rather than inventing a tool
name."""


def _has_final_reply_since(context: ReadonlyContext, activated_ts: float) -> bool:
    """
    True when the assistant has already spoken as this persona.

    Used to add the "you just switched" note only on the first turn after
    ``/chatto``.  Tool-call turns are skipped: the final answer comes from a
    later model call in the same invocation, and that call still needs the
    switch reminder.
    """
    try:
        events = getattr(getattr(context, "session", None), "events", None) or []
    except Exception:
        return False
    for event in events:
        if getattr(event, "author", None) == "user":
            continue
        try:
            timestamp = float(getattr(event, "timestamp", 0) or 0)
        except (TypeError, ValueError):
            continue
        if timestamp < activated_ts:
            continue
        parts = getattr(getattr(event, "content", None), "parts", None) or []
        if any(getattr(part, "function_call", None) or getattr(part, "function_response", None) for part in parts):
            continue
        if any(getattr(part, "text", None) and not getattr(part, "thought", False) for part in parts):
            return True
    return False


def build_instruction(context: ReadonlyContext) -> str:
    """
    The system prompt plus the facts that change every turn.

    The clock is injected here rather than as a per-turn system message, so it
    stays out of the stored conversation history.

    Long-term memory and the active personality are appended after the base
    prompt: memory supplies facts the user should not have to repeat, and the
    persona goes last so its voice wins over the generic assistant tone.  Both
    reads are defensive -- a half-written JSON file or a deleted personality
    folder must never break a turn.

    When a persona is active it is also named at the *top* of the prompt and
    earlier assistant turns are explicitly marked as a different voice.  A
    dossier at the end of a long prompt was not enough: after switching from
    one persona to another, the model kept imitating the previous assistant's
    Australian slang because that was the most recent style in context.
    """
    now = datetime.now().strftime("%A, %B %d, %Y %H:%M:%S")
    persona_name = ""
    persona_banner = ""
    persona_block = ""
    try:
        from core.personality import get_personality_manager

        manager = get_personality_manager()
        active = manager.current()
        persona_block = manager.prompt_block()
        if active and persona_block:
            persona_name = str(active.get("name") or active.get("slug") or "the active persona")
            persona_banner = (
                f"## CURRENT VOICE: {persona_name} (authoritative for style)\n"
                f"Answer every reply in {persona_name}'s voice: use the dossier's rhythm, "
                "vocabulary, humour and reasoning style. Earlier assistant messages in "
                "this conversation may have used a different voice; do not imitate or "
                "continue their slang, catchphrases or sentence patterns. This voice "
                "stays active until the user switches with /chatto, and you should not "
                "mention the switch unless asked.\n"
            )
            try:
                activated_ts = datetime.fromisoformat(str(active.get("activated_at"))).timestamp()
                # Only call it a switch when there is an older assistant reply
                # to switch away from.  A brand-new session with an already
                # active persona just needs the voice contract above.
                had_prior_reply = _has_final_reply_since(context, 0.0)
                if had_prior_reply and not _has_final_reply_since(context, activated_ts):
                    persona_banner += (
                        f"\nPERSONA SWITCH: the user just changed to {persona_name}. "
                        "The previous assistant reply belongs to a different voice; do "
                        "not carry it over. Start this answer in the new voice from the "
                        "first word.\n"
                    )
            except Exception:
                pass
            style = manager.style_contract()
            if style:
                persona_banner += (
                    "\nStyle contract (follow these literally; they override the default "
                    "assistant tone and the tone of earlier replies):\n" + style + "\n"
                )
    except Exception:
        logger.debug("Could not load the active personality for the system prompt", exc_info=True)

    base_prompt = SYSTEM_PROMPT
    if persona_name:
        base_prompt = base_prompt.replace(
            "You are Collig, a powerful AI assistant with access to real-time information.",
            f"You are Collig, currently speaking as {persona_name}. Your voice and "
            "reasoning style must match the active persona dossier at the end of "
            "this prompt.",
            1,
        )

    lines = []
    if persona_banner:
        # Put the voice contract first, not after a long tool guide: style
        # instructions lose to recency and the old assistant turns otherwise.
        lines.extend([persona_banner, ""])
    lines.extend([base_prompt, ""])
    lines.append(f"Current system time: {now}")
    try:
        lines.append(f"Current session ID: {context.session.id}")
    except Exception:
        pass

    try:
        from core.user_memory import get_user_memory

        memory = get_user_memory().prompt_block()
        if memory:
            lines.extend(["", memory])
    except Exception:
        logger.debug("Could not load user memory for the system prompt", exc_info=True)

    if persona_block:
        lines.extend(["", persona_block])

    return "\n".join(lines)


def _initial_model():
    """
    The configured model, or an unauthenticated OpenAI default.

    A missing key must not stop the agent loading: the CLI still has to start
    so the user can run ``config set OPENAI_API_KEY``, and the dev UI still has
    to render so the admin page can set it. The failure surfaces on the first
    message instead.
    """
    try:
        return resolve_model()
    except ProviderError as e:
        logger.warning("%s Falling back to openai/gpt-4o until a key is set.", e)
        return LiteLlm(model="openai/gpt-4o")


# Skills the specialists own, plus -- outside a terminal -- the ones that would
# block on stdin.
_excluded = list(SUBAGENT_SKILLS)
if not IS_TERMINAL:
    _excluded += [name for name in TERMINAL_ONLY_SKILLS if name not in _excluded]

root_agent = LlmAgent(
    name=APP_NAME,
    model=_initial_model(),
    description="Collig, a general-purpose AI co-worker with skills for notes, "
    "bookmarks, weather, news, search, diary and more.",
    instruction=build_instruction,
    tools=[SkillToolset(exclude_skills=_excluded, terminal=IS_TERMINAL)],
    sub_agents=build_subagents(),
)

# Exposed so core.runner can read per-turn usage off the same plugin instance
# the App is running.
token_stats_plugin = TokenStatsPlugin()

# ADK warns that an app with transfers and no `context_cache_config` re-sends
# its prompt uncached after each transfer. That config drives Gemini's explicit
# CachedContent API, which none of Collig's providers (OpenAI, DeepSeek,
# DashScope, Ollama -- all via LiteLLM) implement, so it is deliberately left
# unset. OpenAI-compatible endpoints cache prompt prefixes automatically.
trace_plugin = TracePlugin()

# A tool the model calls without the turn having offered it must not abort the
# message. Shares the same skill exclusions as the root toolset so it cannot
# run a specialist's tool on the root agent's behalf.
unrouted_tool_plugin = UnroutedToolPlugin(
    exclude_skills=_excluded,
    root_agent_name=APP_NAME,
)

app = App(
    name=APP_NAME,
    root_agent=root_agent,
    plugins=[
        TrivialQueryPlugin(),
        token_stats_plugin,
        trace_plugin,
        unrouted_tool_plugin,
        ContextFilterPlugin(num_invocations_to_keep=CONTEXT_INVOCATIONS_TO_KEEP),
    ],
)


def set_model(provider: Optional[str] = None, model: Optional[str] = None) -> None:
    """
    Point the agent at a different provider/model at runtime.

    The sub-agents leave ``model`` unset and resolve it from their parent, so
    this one assignment moves the whole tree. Raises ``ProviderError`` if the
    new provider has no key configured.
    """
    root_agent.model = resolve_model(provider, model)
