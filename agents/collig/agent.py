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
from datetime import datetime
from typing import Optional

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.apps import App
from google.adk.models.lite_llm import LiteLlm
from google.adk.plugins.context_filter_plugin import ContextFilterPlugin

from .plugins import TokenStatsPlugin, TrivialQueryPlugin
from .providers import ProviderError, resolve_model
from .subagents import SUBAGENT_SKILLS, build_subagents
from .toolsets import SkillToolset

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

## Tool Selection Guide:

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

## Tool availability:
Only the tools relevant to the current message are offered to you. If you need
something you cannot see, say what you would need rather than inventing a tool
name."""


def build_instruction(context: ReadonlyContext) -> str:
    """
    The system prompt plus the facts that change every turn.

    The clock is injected here rather than as a per-turn system message, so it
    stays out of the stored conversation history.
    """
    now = datetime.now().strftime("%A, %B %d, %Y %H:%M:%S")
    lines = [SYSTEM_PROMPT, "", f"Current system time: {now}"]
    try:
        lines.append(f"Current session ID: {context.session.id}")
    except Exception:
        pass
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
app = App(
    name=APP_NAME,
    root_agent=root_agent,
    plugins=[
        TrivialQueryPlugin(),
        token_stats_plugin,
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
