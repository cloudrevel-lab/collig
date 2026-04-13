import os
import re
import json
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from skills.manager import SkillManager
from skills.builtins import TimeSkill, BrowserSkill, ThinkingToggleSkill, set_agent_instance
from skills.filesystem import FileSystemSkill
from skills.programming import ProgrammingSkill
from skills.email import EmailSkill
from skills.setup import SetupWizardSkill
from skills.chat import ChatSkill
from skills.map import MapSkill
from skills.system import SystemSkill
from skills.memory import MemorySkill
from skills.loader import SkillLoader
from skills.weather import WeatherSkill
from skills.bookmark import BookmarkSkill
from skills.news import NewsSkill
from skills.profile import ProfileSkill
from skills.git import GitSkill
from skills.date_calculator import DateCalculatorSkill
from skills.cache import CacheSkill
from skills.lunar_calendar import LunarCalendarSkill
from skills.menu import MenuSkill
from skills.survey import SurveySkill
from core.session import SessionManager
from core.paths import paths

from rich.console import Console

from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.tools import tool

# Rich console for properly formatted output
console = Console()

# Patterns that indicate a trivial query (no tools needed)
_TRIVIAL_PATTERNS = [
    # Simple math: "1+1", "2 * 3", "100 / 5", "what is 2+2", "what's 1+1", etc.
    re.compile(r'^(what(?:\s*[\']s)?|calc(?:ulate)?|solve)\s*:?\s*\d+\s*[\+\-\*/x÷]\s*\d+', re.IGNORECASE),
    re.compile(r'^\d+\s*[\+\-\*/x÷]\s*\d+'),
    # Greetings
    re.compile(r'^(hi|hello|hey|greetings|good\s+(morning|afternoon|evening|day))\.?$', re.IGNORECASE),
    # Simple identity questions
    re.compile(r'^(who\s+are\s+you|what\s+are\s+you|what\s+(is|are)\s+your\s+(name|capabilities))\??$', re.IGNORECASE),
    # Thanks
    re.compile(r'^(thanks?|thank\s+you|thx|cheers|appreciate\s+it)\.?$', re.IGNORECASE),
]

# Keyword groups for tool category matching
_TOOL_KEYWORDS = {
    'weather': ['weather', 'temperature', 'forecast', 'rain', 'sunny', 'cold', 'hot'],
    'time': ['time', 'clock', 'timezone', 'what time'],
    'news': ['news', 'headlines', 'latest news', 'current events', 'breaking news'],
    'email': ['email', 'mail', 'inbox', 'send email', 'check mail', 'compose'],
    'file': ['file', 'directory', 'folder', 'read file', 'write file', 'create file', 'list files', 'delete file'],
    'git': ['git', 'commit', 'push', 'pull', 'branch', 'status', 'diff', 'stash'],
    'memory': ['note', 'remember', 'save note', 'my notes', 'search notes'],
    'bookmark': ['bookmark', 'save link', 'saved links', 'favorites'],
    'profile': ['my name', 'my info', 'personal info', 'set my name', 'about me'],
    'system': ['system status', 'disk space', 'memory usage', 'install', 'package'],
    'calendar': ['lunar', 'chinese calendar', 'chinese date'],
    'date': ['days between', 'date calculator', 'what date', 'add days', 'subtract days'],
    'cache': ['cache', 'cached'],
    'browser': ['open browser', 'open website', 'launch browser', 'browse'],
    'menu': ['menu', 'select from', 'choose from'],
    'survey': ['survey', 'questionnaire', 'form'],
    'thinking': ['hide thinking', 'show thinking', 'toggle thinking'],
}


# Try to import tiktoken for accurate token counting
try:
    import tiktoken
    HAS_TIKTOKEN = True
except ImportError:
    HAS_TIKTOKEN = False


def estimate_tokens(text: str) -> int:
    """
    Estimate token count for a given text.
    Uses tiktoken if available, otherwise falls back to ~4 chars per token.
    """
    if not text:
        return 0

    if HAS_TIKTOKEN:
        try:
            # Use cl100k_base encoding (used by gpt-4, gpt-3.5-turbo)
            encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(text))
        except:
            pass

    # Fallback estimation: ~4 chars per token for English
    return len(text) // 4


def extract_token_usage(message: AIMessage) -> Tuple[int, int]:
    """
    Extract token usage from AIMessage if available in metadata.
    Returns (prompt_tokens, completion_tokens).
    """
    prompt_tokens = 0
    completion_tokens = 0

    # Check usage_metadata (newer LangChain format)
    if hasattr(message, 'usage_metadata') and message.usage_metadata:
        usage = message.usage_metadata
        if isinstance(usage, dict):
            prompt_tokens = usage.get('input_tokens', 0)
            completion_tokens = usage.get('output_tokens', 0)
        else:
            # Might be an object with attributes
            prompt_tokens = getattr(usage, 'input_tokens', 0)
            completion_tokens = getattr(usage, 'output_tokens', 0)
        if prompt_tokens > 0 or completion_tokens > 0:
            return prompt_tokens, completion_tokens

    # Check response_metadata (older format)
    if hasattr(message, 'response_metadata') and message.response_metadata:
        # Check OpenAI-style token usage
        usage = message.response_metadata.get('token_usage', {})
        if usage:
            prompt_tokens = usage.get('prompt_tokens', 0)
            completion_tokens = usage.get('completion_tokens', 0)

    return prompt_tokens, completion_tokens


class TokenStatsManager:
    """Manages token usage statistics for sessions."""

    def __init__(self, sessions_dir: str):
        self.sessions_dir = sessions_dir

    def _get_stats_path(self, session_id: str) -> str:
        """Get the path to the stats file for a session."""
        return os.path.join(self.sessions_dir, f"{session_id}_stats.json")

    def _get_all_stats_files(self) -> List[str]:
        """Get all stats files in the sessions directory."""
        if not os.path.exists(self.sessions_dir):
            return []
        files = []
        for filename in os.listdir(self.sessions_dir):
            if filename.endswith("_stats.json"):
                files.append(os.path.join(self.sessions_dir, filename))
        return files

    def load_stats(self, session_id: str) -> Dict[str, Any]:
        """Load stats for a session, or create new stats if none exist."""
        stats_path = self._get_stats_path(session_id)
        if os.path.exists(stats_path):
            try:
                with open(stats_path, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        # Default empty stats structure
        return {
            "session_id": session_id,
            "created_at": datetime.now().isoformat(),
            "interactions": [],
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_tokens": 0
        }

    def save_stats(self, session_id: str, stats: Dict[str, Any]):
        """Save stats for a session."""
        stats_path = self._get_stats_path(session_id)
        with open(stats_path, "w") as f:
            json.dump(stats, f, indent=2)

    def add_interaction(self, session_id: str, prompt_tokens: int, completion_tokens: int,
                       user_message: str = None, timestamp: str = None):
        """Add a token usage interaction to the session stats."""
        if session_id is None:
            return

        if timestamp is None:
            timestamp = datetime.now().isoformat()

        stats = self.load_stats(session_id)

        interaction = {
            "timestamp": timestamp,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens
        }
        if user_message:
            # Truncate long messages for storage
            interaction["message_preview"] = user_message[:100] + ("..." if len(user_message) > 100 else "")

        stats["interactions"].append(interaction)
        stats["total_prompt_tokens"] += prompt_tokens
        stats["total_completion_tokens"] += completion_tokens
        stats["total_tokens"] += prompt_tokens + completion_tokens

        self.save_stats(session_id, stats)

    def get_summary(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get a summary of token usage for a session."""
        stats = self.load_stats(session_id)
        if not stats["interactions"]:
            return None

        interaction_count = len(stats["interactions"])
        first_interaction = stats["interactions"][0]["timestamp"]
        last_interaction = stats["interactions"][-1]["timestamp"]

        # Calculate averages
        avg_prompt = stats["total_prompt_tokens"] // interaction_count if interaction_count > 0 else 0
        avg_completion = stats["total_completion_tokens"] // interaction_count if interaction_count > 0 else 0
        avg_total = stats["total_tokens"] // interaction_count if interaction_count > 0 else 0

        return {
            "session_id": session_id,
            "interaction_count": interaction_count,
            "first_interaction": first_interaction,
            "last_interaction": last_interaction,
            "total_prompt_tokens": stats["total_prompt_tokens"],
            "total_completion_tokens": stats["total_completion_tokens"],
            "total_tokens": stats["total_tokens"],
            "avg_prompt_tokens": avg_prompt,
            "avg_completion_tokens": avg_completion,
            "avg_total_tokens": avg_total
        }

    def get_overall_summary(self) -> Optional[Dict[str, Any]]:
        """Get overall token usage statistics across all sessions."""
        stats_files = self._get_all_stats_files()
        if not stats_files:
            return None

        total_sessions = 0
        total_interactions = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_tokens = 0
        first_interaction = None
        last_interaction = None

        for stats_file in stats_files:
            try:
                with open(stats_file, "r") as f:
                    stats = json.load(f)

                if stats.get("interactions"):
                    total_sessions += 1
                    total_interactions += len(stats["interactions"])
                    total_prompt_tokens += stats.get("total_prompt_tokens", 0)
                    total_completion_tokens += stats.get("total_completion_tokens", 0)
                    total_tokens += stats.get("total_tokens", 0)

                    # Track first and last interaction times
                    session_first = stats["interactions"][0]["timestamp"]
                    session_last = stats["interactions"][-1]["timestamp"]

                    if first_interaction is None or session_first < first_interaction:
                        first_interaction = session_first
                    if last_interaction is None or session_last > last_interaction:
                        last_interaction = session_last
            except Exception:
                continue

        if total_sessions == 0:
            return None

        # Calculate averages
        avg_prompt_per_session = total_prompt_tokens // total_sessions if total_sessions > 0 else 0
        avg_completion_per_session = total_completion_tokens // total_sessions if total_sessions > 0 else 0
        avg_total_per_session = total_tokens // total_sessions if total_sessions > 0 else 0

        avg_prompt_per_interaction = total_prompt_tokens // total_interactions if total_interactions > 0 else 0
        avg_completion_per_interaction = total_completion_tokens // total_interactions if total_interactions > 0 else 0
        avg_total_per_interaction = total_tokens // total_interactions if total_interactions > 0 else 0

        return {
            "total_sessions": total_sessions,
            "total_interactions": total_interactions,
            "first_interaction": first_interaction,
            "last_interaction": last_interaction,
            "total_prompt_tokens": total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
            "total_tokens": total_tokens,
            "avg_prompt_per_session": avg_prompt_per_session,
            "avg_completion_per_session": avg_completion_per_session,
            "avg_total_per_session": avg_total_per_session,
            "avg_prompt_per_interaction": avg_prompt_per_interaction,
            "avg_completion_per_interaction": avg_completion_per_interaction,
            "avg_total_per_interaction": avg_total_per_interaction
        }


def _is_trivial_query(message: str) -> bool:
    """Check if a message is a trivial query that doesn't need tools."""
    msg = message.strip()
    for pattern in _TRIVIAL_PATTERNS:
        if pattern.match(msg):
            return True
    return False


def _filter_tools_for_message(message: str, all_tools: list) -> list:
    """
    Filter tools based on message intent to reduce token usage.
    Returns a subset of relevant tools, or empty list for trivial queries.
    """
    msg_lower = message.lower().strip()

    # Trivial queries need no tools at all
    if _is_trivial_query(msg_lower):
        return []

    # Find matching tool categories
    matching_categories = set()
    for category, keywords in _TOOL_KEYWORDS.items():
        for keyword in keywords:
            if keyword in msg_lower:
                matching_categories.add(category)
                break

    # If no category matched, include a broader set of commonly useful tools
    if not matching_categories:
        # General conversation: include only core utilities
        matching_categories = {'time', 'thinking', 'profile'}

    # Map categories to tool name prefixes/patterns
    category_tool_prefixes = {
        'weather': ['get_weather'],
        'time': ['get_current_time'],
        'news': ['search_news', 'read_news', 'check_news', 'list_cached_news', 'load_cached_news', 'save_news'],
        'email': ['setup_email', 'check_inbox', 'send_email', 'download_emails', 'search_emails', 'read_email'],
        'file': ['create_directory', 'list_directory', 'delete_item', 'write_file', 'read_file'],
        'git': ['git_status', 'git_add', 'git_commit', 'git_push', 'git_diff', 'git_log'],
        'memory': ['add_note', 'list_notes', 'search_notes', 'delete_notes'],
        'bookmark': ['add_bookmark', 'list_bookmarks', 'search_bookmarks', 'delete_bookmark', 'open_bookmark'],
        'profile': ['set_personal_info', 'get_personal_info'],
        'system': ['get_system_status', 'clear_conversation', 'install_package'],
        'calendar': ['get_lunar_date'],
        'date': ['date_calculator'],
        'cache': ['cache_content', 'cache_news_list', 'list_cache', 'search_cache', 'get_cache_item', 'delete_cache', 'clear_cache'],
        'browser': ['open_browser'],
        'menu': ['select_from_menu', 'select_option_by_number'],
        'survey': ['load_survey', 'continue_survey'],
        'thinking': ['hide_thinking', 'show_thinking', 'toggle_thinking'],
    }

    # Collect matching tool names
    matching_tool_names = set()
    for cat in matching_categories:
        matching_tool_names.update(category_tool_prefixes.get(cat, []))

    # Filter tools
    if matching_tool_names:
        return [t for t in all_tools if t.name in matching_tool_names]

    # Fallback: return all tools if filtering somehow produced nothing
    return all_tools


class Agent:
    def __init__(self):
        import time as time_module
        init_start = time_module.time()

        self.name = "Collig"
        self.skill_manager = SkillManager()
        self.session_manager = SessionManager()
        self.token_stats_manager = TokenStatsManager(paths.sessions_dir)
        self.shared_context = {} # Store runtime context (e.g., last_created_dir)
        self.active_skill_name = None # For multi-turn skills
        self.verbose = True # Show thinking messages by default

        # Load provider config from config.json (persistence) AND env
        # Config.json takes precedence for user preference
        import json
        try:
            with open(paths.global_config_file, "r") as f:
                config = json.load(f)
                self.llm_provider = config.get("LLM_PROVIDER", os.getenv("LLM_PROVIDER", "openai"))
                self.llm_model = config.get("LLM_MODEL", os.getenv("LLM_MODEL", "gpt-4o"))
                self.verbose = config.get("VERBOSE_THINKING", True)
        except Exception:
             self.llm_provider = os.getenv("LLM_PROVIDER", "openai")
             self.llm_model = os.getenv("LLM_MODEL", "gpt-4o")
             self.verbose = True

        console.print(f"[dim]Basic setup: {time_module.time() - init_start:.2f}s[/dim]")

        skills_start = time_module.time()
        self._register_initial_skills()
        console.print(f"[dim]Initial skills registered: {time_module.time() - skills_start:.2f}s[/dim]")

        external_start = time_module.time()
        self._load_external_skills()
        console.print(f"[dim]External skills loaded: {time_module.time() - external_start:.2f}s[/dim]")

        # Set global agent reference for skills that need it
        from skills.builtins import set_agent_instance
        set_agent_instance(self)

        # Initialize LangChain/LangGraph Agent
        langchain_start = time_module.time()
        console.print(f"[dim]Initializing LangChain agent...[/dim]")
        self._init_langchain_agent()
        console.print(f"[dim]LangChain agent initialized: {time_module.time() - langchain_start:.2f}s[/dim]")
        console.print(f"[dim]Total agent initialization: {time_module.time() - init_start:.2f}s[/dim]")

    def set_provider(self, provider: str, model: str = None):
        """Switches the LLM provider (openai/ollama/llama/deepseek)."""
        self.llm_provider = provider.lower()
        if model:
            self.llm_model = model
        elif self.llm_provider == "llama":
            self.llm_model = "llama3.1" # Default for llama, supports tools
        elif self.llm_provider == "ollama":
            self.llm_model = "qwen3:8b" # Default for ollama
        elif self.llm_provider == "openai":
            self.llm_model = "gpt-4o" # Default for openai
        elif self.llm_provider == "deepseek":
            self.llm_model = "deepseek-chat" # Default for deepseek

        console.print(f"Switching provider to {self.llm_provider} (Model: {self.llm_model})")
        self._init_langchain_agent()
        return f"Provider switched to {self.llm_provider} ({self.llm_model})"

    def set_verbose(self, enabled: bool) -> str:
        """Sets whether to show thinking messages and saves to config."""
        self.verbose = enabled

        # Save to config
        import json
        try:
            if os.path.exists(paths.global_config_file):
                with open(paths.global_config_file, "r") as f:
                    config = json.load(f)
            else:
                config = {}

            config["VERBOSE_THINKING"] = enabled
            with open(paths.global_config_file, "w") as f:
                json.dump(config, f, indent=2)

            status = "enabled" if enabled else "disabled"
            return f"Thinking messages {status}. Preference saved."
        except Exception as e:
            status = "enabled" if enabled else "disabled"
            return f"Thinking messages {status}, but failed to save preference: {e}"

    def toggle_verbose(self) -> str:
        """Toggles whether to show thinking messages."""
        new_state = not self.verbose
        return self.set_verbose(new_state)

    def get_available_models(self) -> str:
        """Returns a string listing available models for the current or specified provider."""
        output = []

        # DeepSeek
        output.append("[bold cyan]deepseek[/bold cyan]:")
        output.append("  - deepseek-chat (V3)")
        output.append("  - deepseek-reasoner (R1)")

        # OpenAI
        output.append("\n[bold cyan]openai[/bold cyan]:")
        output.append("  - gpt-4o")
        output.append("  - gpt-4o-mini")
        output.append("  - gpt-3.5-turbo")

        # Ollama
        output.append("\n[bold cyan]ollama[/bold cyan]:")
        try:
            import subprocess
            result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                for line in lines[1:]: # Skip header
                    parts = line.split()
                    if parts:
                        output.append(f"  - {parts[0]}")
            else:
                output.append("  (Error listing Ollama models)")
        except Exception as e:
            output.append(f"  (Ollama not found or error: {e})")

        # Llama (alias for ollama)
        output.append("\n[bold cyan]llama (alias for ollama)[/bold cyan]:")
        output.append("  (Use 'ollama' provider instead)")

        return "\n".join(output)

    def _register_initial_skills(self):
        """Registers the built-in skills."""
        self.skill_manager.register_skill(TimeSkill())
        self.skill_manager.register_skill(BrowserSkill())
        self.skill_manager.register_skill(ThinkingToggleSkill())
        self.skill_manager.register_skill(WeatherSkill())
        self.skill_manager.register_skill(FileSystemSkill())
        self.skill_manager.register_skill(EmailSkill())
        # self.skill_manager.register_skill(ProgrammingSkill())
        # self.skill_manager.register_skill(SetupWizardSkill())
        # self.skill_manager.register_skill(MapSkill())
        self.skill_manager.register_skill(SystemSkill())
        self.skill_manager.register_skill(MemorySkill())
        self.skill_manager.register_skill(BookmarkSkill())
        self.skill_manager.register_skill(NewsSkill())
        self.skill_manager.register_skill(ProfileSkill())
        self.skill_manager.register_skill(GitSkill())
        self.skill_manager.register_skill(DateCalculatorSkill())
        self.skill_manager.register_skill(CacheSkill())
        self.skill_manager.register_skill(LunarCalendarSkill())
        self.skill_manager.register_skill(MenuSkill())
        self.skill_manager.register_skill(SurveySkill())
        # self.skill_manager.register_skill(ChatSkill()) # Fallback / General Skill

    def _init_langchain_agent(self):
        """Initializes the LangChain Agent with tools from skills."""

        self.llm = None

        # Helper to get API key from env or config.json
        def get_api_key(env_var_name):
            key = os.getenv(env_var_name)
            if not key:
                # Try loading from config.json
                import json
                try:
                    with open(paths.global_config_file, "r") as f:
                        config = json.load(f)
                        key = config.get(env_var_name)
                except Exception:
                    pass
            return key

        # ALWAYS collect tools from enabled skills first - this must happen
        # even if LLM initialization fails, so that skill toggle works
        self.tools = []
        for skill in self.skill_manager.skills:
            if skill.enabled:
                self.tools.extend(skill.get_tools())

        if not self.tools:
            console.print("Warning: No tools registered.")

        console.print(f"[dim]Loaded {len(self.tools)} tools[/dim]")

        # Now try to initialize LLM
        if self.llm_provider == "openai":
            api_key = get_api_key("OPENAI_API_KEY")
            if not api_key:
                console.print("Warning: OPENAI_API_KEY not found. Agent will not function correctly.")
                return
            self.llm = ChatOpenAI(model=self.llm_model, temperature=0, api_key=api_key)

        elif self.llm_provider == "ollama" or self.llm_provider == "llama":
            # Using ChatOllama for local LLM
            # Assumes Ollama is running on localhost:11434 (default)
            try:
                self.llm = ChatOllama(model=self.llm_model, temperature=0)
            except Exception as e:
                console.print(f"Error initializing {self.llm_provider} (Ollama): {e}")
                return

        elif self.llm_provider == "deepseek":
            api_key = get_api_key("DEEPSEEK_API_KEY")
            if not api_key:
                console.print("Warning: DEEPSEEK_API_KEY not found. Please set it using 'config set DEEPSEEK_API_KEY <key>'.")
                # Do not initialize LLM without key to avoid async key error
                return

            # DeepSeek uses OpenAI-compatible API
            self.llm = ChatOpenAI(
                model=self.llm_model,
                temperature=0,
                base_url="https://api.deepseek.com",
                api_key=api_key
            )

        else:
            console.print(f"Unknown provider: {self.llm_provider}. Falling back to OpenAI.")
            self.llm_provider = "openai"
            self._init_langchain_agent()
            return

        # Create React Agent (LangGraph)
        # Note: prompt can be a string (system prompt) or a SystemMessage.
        system_prompt = """You are Collig, an AI assistant.

IMPORTANT: Only use tools when they are genuinely needed. For simple math, greetings, general knowledge, or conversational questions, respond directly without any tool calls.

When you DO use tools:
- Use only the tools provided to you.
- Don't make up tool names.
- If a tool doesn't exist, don't try to call it.

Specific tool hints:
- News items by number: use check_news_cache then read_news_item.
- Chinese calendar: use get_lunar_date tool only.
- Multi-select: use select_from_menu with comma-separated options for arrow-key selection."""

        # Store all tools for reference, but we'll filter dynamically per message
        self.all_tools = self.tools[:]

        self.agent_executor = create_react_agent(self.llm, self.all_tools, prompt=system_prompt)

    def _load_external_skills(self):
        """Loads external skills from SKILL.md files."""
        # Assume skills are in backend/skills or backend/skills/imported
        # The loader looks in "skills" relative to CWD, which is usually backend/
        # But if running from root, might need adjustment.
        # Assuming we run from backend/ as per Makefile
        loader = SkillLoader(skills_dir="skills")
        external_skills = loader.load_skills()
        for skill in external_skills:
            self.skill_manager.register_skill(skill)


    def _compress_history(self, history: List[Dict], current_message: str) -> List[Any]:
        """
        Compresses conversation history by summarizing older messages
        and keeping recent ones intact.
        Uses a sliding window approach based on estimated token count to prevent context length errors.
        """
        if not history:
            return []

        # Configuration for compression
        RAW_CONTEXT_COUNT = 3
        MAX_SUMMARY_TOKENS = 6000 # Rough estimate (chars / 4) to stay well within limits

        # Helper to convert dict to LangChain message
        def to_lc_msg(msg):
            if msg["role"] == "user":
                return HumanMessage(content=msg["content"])
            elif msg["role"] == "ai":
                return AIMessage(content=msg["content"])
            return None

        # 1. Simple Case: History is short enough
        if len(history) <= RAW_CONTEXT_COUNT:
            return [to_lc_msg(m) for m in history if to_lc_msg(m)]

        # 2. Prepare data for summarization
        recent_raw = history[-RAW_CONTEXT_COUNT:]

        # We need to be careful about the "to_summarize" part.
        # If it's too huge, the summarization call itself will fail (as seen in the error).
        # So we must truncate 'to_summarize' to a safe limit BEFORE asking the LLM to summarize it.

        to_summarize_candidates = history[:-RAW_CONTEXT_COUNT]

        # Estimate token count for candidates (1 token ~= 4 chars)
        current_tokens = 0
        safe_to_summarize = []

        # Iterate backwards to keep the most recent "old" messages
        for msg in reversed(to_summarize_candidates):
            msg_len = len(msg.get("content", ""))
            est_tokens = msg_len / 4
            if current_tokens + est_tokens > MAX_SUMMARY_TOKENS:
                break
            safe_to_summarize.insert(0, msg)
            current_tokens += est_tokens

        # If we dropped messages, we might want to note that?
        # For now, just silently drop extremely old history that doesn't fit in the summary window.

        # Create a prompt for summarization
        summary_prompt = "Summarize the following conversation history, focusing on key facts and user preferences that might be relevant to the new user request: '{}'. Ignore irrelevant details like casual chatter or completed tool outputs unless they provide necessary context.\n\nHistory:\n".format(current_message)

        for msg in safe_to_summarize:
            summary_prompt += f"{msg['role'].upper()}: {msg['content']}\n"

        try:
            from langchain_core.messages import SystemMessage
            from langchain_openai import ChatOpenAI
            from langchain_ollama import ChatOllama

            llm = None
            if self.llm_provider == "openai":
                api_key = os.getenv("OPENAI_API_KEY")
                if api_key:
                    llm = ChatOpenAI(model="gpt-3.5-turbo", api_key=api_key)
            elif self.llm_provider == "ollama" or self.llm_provider == "llama":
                llm = ChatOllama(model=self.llm_model)
            elif self.llm_provider == "deepseek":
                api_key = os.getenv("DEEPSEEK_API_KEY")
                if api_key:
                    llm = ChatOpenAI(model="deepseek-chat", base_url="https://api.deepseek.com", api_key=api_key)

            if llm:
                summary_response = llm.invoke(summary_prompt)
                summary = summary_response.content

                # Construct result
                compressed_msgs = []
                compressed_msgs.append(SystemMessage(content=f"Previous Conversation Summary: {summary}"))

                for msg in recent_raw:
                    lc_msg = to_lc_msg(msg)
                    if lc_msg:
                        compressed_msgs.append(lc_msg)

                return compressed_msgs

        except Exception as e:
            console.print(f"Warning: History compression failed ({e}). Falling back to truncation.")

        # Fallback: Just return last N messages
        fallback_msgs = []
        # Keep last 5 if compression fails (safer than 10 given the error)
        for msg in history[-5:]:
            lc_msg = to_lc_msg(msg)
            if lc_msg:
                fallback_msgs.append(lc_msg)
        return fallback_msgs


    def process_message_stream(self, message: str, session_id: str = None, include_history: bool = True, verbose: bool = None, token_callback=None) -> dict:
        """
        Process a user message with optional streaming callback.
        The token_callback is maintained for backwards compatibility but not actively used.
        """
        return self.process_message(message, session_id, include_history, verbose)

    def process_message(self, message: str, session_id: str = None, include_history: bool = True, verbose: bool = None) -> dict:
        """
        Process a user message, optionally within a session context.
        If verbose is not specified, uses the instance's verbose setting.
        """
        if verbose is None:
            verbose = self.verbose

        # Save user message to history if session_id is provided
        if session_id:
            self.session_manager.add_message(session_id, "user", message)

        user_msg = message.lower()
        response_data = {}

        # Initialize token counters
        total_prompt_tokens = 0
        total_completion_tokens = 0

        # Filter tools based on message intent to reduce token usage
        filtered_tools = _filter_tools_for_message(message, self.all_tools)
        num_filtered = len(filtered_tools)
        num_total = len(self.all_tools)

        # Create a temporary agent with filtered tools if different from default
        use_filtered = num_filtered < num_total and num_filtered > 0
        use_no_tools = num_filtered == 0

        if use_no_tools:
            # For trivial queries, use a simple LLM call without tools
            return self._process_simple_message(message, session_id)
        elif use_filtered:
            # Create a temporary agent with filtered tools
            temp_agent_executor = create_react_agent(self.llm, filtered_tools, prompt="""You are Collig, an AI assistant.

IMPORTANT: Only use tools when they are genuinely needed. For simple math, greetings, general knowledge, or conversational questions, respond directly without any tool calls.

When you DO use tools:
- Use only the tools provided to you.
- Don't make up tool names.
- If a tool doesn't exist, don't try to call it.

Specific tool hints:
- News items by number: use check_news_cache then read_news_item.
- Chinese calendar: use get_lunar_date tool only.
- Multi-select: use select_from_menu with comma-separated options for arrow-key selection.""")
        else:
            temp_agent_executor = self.agent_executor

        try:
            # Build the message list
            msgs = []

            # Inject current system time as a system message to ground the model
            from datetime import datetime
            current_time_str = datetime.now().strftime("%A, %B %d, %Y %H:%M:%S")
            msgs.append(SystemMessage(content=f"Current System Time: {current_time_str}"))

            if session_id:
                msgs.append(SystemMessage(content=f"Current Session ID: {session_id}"))

                if include_history:
                    # Load history
                    history = self.session_manager.get_history(session_id)
                    # Use compression
                    compressed_history = self._compress_history(history, message)
                    msgs.extend(compressed_history)

            msgs.append(HumanMessage(content=message))
            inputs = {"messages": msgs}

            # Use stream to capture intermediate steps for verbose mode
            final_state = None
            final_response_text = ""
            has_printed_header = False
            last_ai_message = None
            response_started = False

            for event in temp_agent_executor.stream(inputs):
                for key, value in event.items():
                    if key == "agent":
                        if "messages" in value:
                            msg = value["messages"][-1]
                            if isinstance(msg, AIMessage):
                                last_ai_message = msg

                                # Extract token usage if available
                                prompt_tok, completion_tok = extract_token_usage(msg)
                                if prompt_tok > 0 or completion_tok > 0:
                                    total_prompt_tokens = prompt_tok
                                    total_completion_tokens = completion_tok

                                # Determine if we have something interesting to print
                                should_print = False

                                # 1. Tool Calls
                                if msg.tool_calls:
                                    should_print = True

                                # 2. Reasoning (mixed with content or explicit)
                                if msg.content and msg.tool_calls:
                                     should_print = True

                                # Print header if needed
                                if verbose and should_print and not has_printed_header:
                                    console.print("\n[Thinking Process]")
                                    has_printed_header = True

                                # Do the printing
                                if verbose and should_print:
                                    if msg.content and msg.tool_calls:
                                        console.print(f"  ➜ Reasoning: {msg.content}")

                                    if msg.tool_calls:
                                        import json
                                        for tc in msg.tool_calls:
                                            console.print(f"  ➜ Planning to use tool: [bold]{tc['name']}[/bold]")

                                            # Pretty print arguments
                                            args = tc.get('args', {})
                                            if args:
                                                # Mask sensitive data
                                                safe_args = args.copy() if isinstance(args, dict) else args
                                                if isinstance(safe_args, dict):
                                                    for k in safe_args:
                                                        if any(secret in k.lower() for secret in ['password', 'secret', 'key', 'token', 'credential']):
                                                            safe_args[k] = "******"

                                                try:
                                                    pretty_args = json.dumps(safe_args, indent=2)
                                                    indented_args = "\n".join("    " + line for line in pretty_args.splitlines())
                                                    console.print(f"    Args:\n{indented_args}")
                                                except:
                                                    console.print(f"    Args: {safe_args}")
                                            else:
                                                console.print(f"    Args: {{}}")

                                # Capture final response if it's the answer (no tool calls)
                                if msg.content and not msg.tool_calls:
                                    final_response_text = msg.content

                    elif key == "tools":
                        if "messages" in value:
                            msg = value["messages"][-1]

                            if verbose and not has_printed_header:
                                console.print("\n[Thinking Process]")
                                has_printed_header = True

                            if verbose:
                                console.print(f"    ✔ Tool '{msg.name}' executed.")

                # Keep track of the last event as the final state
                final_state = event

            if verbose and has_printed_header:
                console.print("[End of Thinking]\n")

            # Extract the final response from the last state if not already found
            if not final_response_text and final_state and "agent" in final_state:
                last_msg = final_state["agent"]["messages"][-1]
                if isinstance(last_msg, AIMessage):
                    final_response_text = last_msg.content
                    last_ai_message = last_msg

            # IMPORTANT: 3000-3500 tokens is NORMAL for this agent!
            # We have ~15-20 skills with multiple tools each.
            # Each tool has a name, description, and JSON schema = ~150-200 tokens per tool!
            # If we don't get token counts from streaming, we still know roughly what it should be.

            # Try one more time to get token counts from the last AI message
            if (total_prompt_tokens == 0 or total_completion_tokens == 0) and last_ai_message:
                prompt_tok, completion_tok = extract_token_usage(last_ai_message)
                if prompt_tok > 0 or completion_tok > 0:
                    total_prompt_tokens = prompt_tok
                    total_completion_tokens = completion_tok

            # If we STILL don't have token counts, use a reasonable estimate
            # With tool filtering, this should be much lower than before.
            if total_prompt_tokens == 0 and total_completion_tokens == 0:
                # Count actual tools used in this turn
                active_tools = num_filtered if use_filtered else (0 if use_no_tools else num_total)

                # Build a rough estimate of the prompt
                approx_prompt = """You are Collig, an AI assistant."""
                for msg in msgs:
                    if hasattr(msg, 'content') and msg.content:
                        approx_prompt += str(msg.content) + " "

                base_tokens = estimate_tokens(approx_prompt)
                tool_tokens = active_tools * 150  # ~150 tokens per tool with schema

                total_prompt_tokens = base_tokens + tool_tokens
                total_completion_tokens = estimate_tokens(final_response_text)

            response_text = final_response_text

            response_data = {
                "response": response_text,
                "action": "agent_response",
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "total_tokens": total_prompt_tokens + total_completion_tokens
            }

            # Save token stats
            self.token_stats_manager.add_interaction(
                session_id,
                total_prompt_tokens,
                total_completion_tokens,
                user_message=message
            )

            # Save AI response to history
            if session_id:
                self.session_manager.add_message(session_id, "ai", response_text)

        except Exception as e:
            import traceback
            traceback.print_exc()
            response_data = {
                "response": f"I encountered an error: {str(e)}",
                "action": "error",
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            }

        return response_data

    def _process_simple_message(self, message: str, session_id: str = None) -> dict:
        """
        Process a trivial message (greeting, simple math, etc.) without any tools.
        This saves significant tokens by avoiding tool schema injection.
        """
        total_prompt_tokens = 0
        total_completion_tokens = 0

        try:
            # Build minimal message list
            msgs = [HumanMessage(content=message)]

            # Direct LLM call without tools
            response = self.llm.invoke(msgs)
            response_text = response.content if hasattr(response, 'content') else str(response)

            # Extract token usage
            total_prompt_tokens, total_completion_tokens = extract_token_usage(response)
            if total_prompt_tokens == 0:
                total_prompt_tokens = estimate_tokens(message) + 50  # small system overhead
                total_completion_tokens = estimate_tokens(response_text)

            # Save token stats
            self.token_stats_manager.add_interaction(
                session_id,
                total_prompt_tokens,
                total_completion_tokens,
                user_message=message
            )

            # Save AI response to history
            if session_id:
                self.session_manager.add_message(session_id, "ai", response_text)

            return {
                "response": response_text,
                "action": "agent_response",
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "total_tokens": total_prompt_tokens + total_completion_tokens
            }

        except Exception as e:
            import traceback
            traceback.print_exc()
            return {
                "response": f"I encountered an error: {str(e)}",
                "action": "error",
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            }

    def get_token_stats(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get token usage statistics for a session."""
        return self.token_stats_manager.get_summary(session_id)

    def get_overall_token_stats(self) -> Optional[Dict[str, Any]]:
        """Get overall token usage statistics across all sessions."""
        return self.token_stats_manager.get_overall_summary()


agent = Agent()
