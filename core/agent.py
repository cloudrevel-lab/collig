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
from core.session import SessionManager
from core.paths import paths

from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.tools import tool


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

        print(f"[dim]Basic setup: {time_module.time() - init_start:.2f}s[/dim]")

        skills_start = time_module.time()
        self._register_initial_skills()
        print(f"[dim]Initial skills registered: {time_module.time() - skills_start:.2f}s[/dim]")

        external_start = time_module.time()
        self._load_external_skills()
        print(f"[dim]External skills loaded: {time_module.time() - external_start:.2f}s[/dim]")

        # Set global agent reference for skills that need it
        from skills.builtins import set_agent_instance
        set_agent_instance(self)

        # Initialize LangChain/LangGraph Agent
        langchain_start = time_module.time()
        print(f"[dim]Initializing LangChain agent...[/dim]")
        self._init_langchain_agent()
        print(f"[dim]LangChain agent initialized: {time_module.time() - langchain_start:.2f}s[/dim]")
        print(f"[dim]Total agent initialization: {time_module.time() - init_start:.2f}s[/dim]")

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

        print(f"Switching provider to {self.llm_provider} (Model: {self.llm_model})")
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
        # self.skill_manager.register_skill(ChatSkill()) # Fallback / General Skill

    def _init_langchain_agent(self):
        """Initializes the LangChain Agent with tools from skills."""

        llm = None

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

        if self.llm_provider == "openai":
            api_key = get_api_key("OPENAI_API_KEY")
            if not api_key:
                print("Warning: OPENAI_API_KEY not found. Agent will not function correctly.")
                return
            llm = ChatOpenAI(model=self.llm_model, temperature=0, api_key=api_key)

        elif self.llm_provider == "ollama" or self.llm_provider == "llama":
            # Using ChatOllama for local LLM
            # Assumes Ollama is running on localhost:11434 (default)
            try:
                llm = ChatOllama(model=self.llm_model, temperature=0)
            except Exception as e:
                print(f"Error initializing {self.llm_provider} (Ollama): {e}")
                return

        elif self.llm_provider == "deepseek":
            api_key = get_api_key("DEEPSEEK_API_KEY")
            if not api_key:
                print("Warning: DEEPSEEK_API_KEY not found. Please set it using 'config set DEEPSEEK_API_KEY <key>'.")
                # Do not initialize LLM without key to avoid async key error
                return

            # DeepSeek uses OpenAI-compatible API
            llm = ChatOpenAI(
                model=self.llm_model,
                temperature=0,
                base_url="https://api.deepseek.com",
                api_key=api_key
            )

        else:
            print(f"Unknown provider: {self.llm_provider}. Falling back to OpenAI.")
            self.llm_provider = "openai"
            self._init_langchain_agent()
            return

        # Collect tools from all enabled skills
        self.tools = []
        for skill in self.skill_manager.skills:
            if skill.enabled:
                self.tools.extend(skill.get_tools())

        if not self.tools:
            print("Warning: No tools registered.")

        print(f"[dim]Loaded {len(self.tools)} tools[/dim]")

        # Create React Agent (LangGraph)
        # Note: prompt can be a string (system prompt) or a SystemMessage.
        system_prompt = """You are Collig, an AI assistant. Use tools to help.

News items by number: use check_news_cache then read_news_item.

Chinese calendar: use get_lunar_date tool only.

Multi-select: use select_from_menu with comma-separated options for arrow-key selection."""
        self.agent_executor = create_react_agent(llm, self.tools, prompt=system_prompt)

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
            print(f"Warning: History compression failed ({e}). Falling back to truncation.")

        # Fallback: Just return last N messages
        fallback_msgs = []
        # Keep last 5 if compression fails (safer than 10 given the error)
        for msg in history[-5:]:
            lc_msg = to_lc_msg(msg)
            if lc_msg:
                fallback_msgs.append(lc_msg)
        return fallback_msgs


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

            for event in self.agent_executor.stream(inputs):
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
                                    print("\n[Thinking Process]")
                                    has_printed_header = True

                                # Do the printing
                                if verbose and should_print:
                                    if msg.content and msg.tool_calls:
                                        print(f"  ➜ Reasoning: {msg.content}")

                                    if msg.tool_calls:
                                        import json
                                        for tc in msg.tool_calls:
                                            print(f"  ➜ Planning to use tool: \033[1m{tc['name']}\033[0m")

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
                                                    print(f"    Args:\n{indented_args}")
                                                except:
                                                    print(f"    Args: {safe_args}")
                                            else:
                                                print(f"    Args: {{}}")

                                # Capture final response if it's the answer (no tool calls)
                                if msg.content and not msg.tool_calls:
                                    final_response_text = msg.content

                    elif key == "tools":
                        if "messages" in value:
                            msg = value["messages"][-1]

                            if verbose and not has_printed_header:
                                print("\n[Thinking Process]")
                                has_printed_header = True

                            if verbose:
                                print(f"    ✔ Tool '{msg.name}' executed.")

                # Keep track of the last event as the final state
                final_state = event

            if verbose and has_printed_header:
                print("[End of Thinking]\n")

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
            # This is NOT a bug - with ~15 skills, this is the actual token cost!
            if total_prompt_tokens == 0 and total_completion_tokens == 0:
                num_tools = len(self.tools) if hasattr(self, 'tools') else 15

                # Build a rough estimate of the prompt
                approx_prompt = """You are Collig, an intelligent AI co-worker. Use the available tools to assist the user. If you need to write code, use the file system tools."""
                for msg in msgs:
                    if hasattr(msg, 'content') and msg.content:
                        approx_prompt += str(msg.content) + " "

                base_tokens = estimate_tokens(approx_prompt)
                tool_tokens = num_tools * 150  # ~150 tokens per tool with schema

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

    def get_token_stats(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get token usage statistics for a session."""
        return self.token_stats_manager.get_summary(session_id)

    def get_overall_token_stats(self) -> Optional[Dict[str, Any]]:
        """Get overall token usage statistics across all sessions."""
        return self.token_stats_manager.get_overall_summary()


agent = Agent()
