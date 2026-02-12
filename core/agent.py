import os
from typing import List, Dict, Any, Optional
from skills.manager import SkillManager
from skills.builtins import TimeSkill, BrowserSkill
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
from session import SessionManager
from paths import paths

from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.tools import tool

class Agent:
    def __init__(self):
        self.name = "Collig"
        self.skill_manager = SkillManager()
        self.session_manager = SessionManager()
        self.shared_context = {} # Store runtime context (e.g., last_created_dir)
        self.active_skill_name = None # For multi-turn skills

        # Load provider config from config.json (persistence) AND env
        # Config.json takes precedence for user preference
        import json
        try:
            with open(paths.global_config_file, "r") as f:
                config = json.load(f)
                self.llm_provider = config.get("LLM_PROVIDER", os.getenv("LLM_PROVIDER", "openai"))
                self.llm_model = config.get("LLM_MODEL", os.getenv("LLM_MODEL", "gpt-4o"))
        except Exception:
             self.llm_provider = os.getenv("LLM_PROVIDER", "openai")
             self.llm_model = os.getenv("LLM_MODEL", "gpt-4o")

        self._register_initial_skills()
        self._load_external_skills()

        # Initialize LangChain/LangGraph Agent
        self._init_langchain_agent()

    def set_provider(self, provider: str, model: str = None):
        """Switches the LLM provider (openai/llama)."""
        self.llm_provider = provider.lower()
        if model:
            self.llm_model = model
        elif self.llm_provider == "llama":
            self.llm_model = "llama3.1" # Default for llama, supports tools
        elif self.llm_provider == "openai":
            self.llm_model = "gpt-4o" # Default for openai
        elif self.llm_provider == "deepseek":
            self.llm_model = "deepseek-chat" # Default for deepseek

        print(f"Switching provider to {self.llm_provider} (Model: {self.llm_model})")
        self._init_langchain_agent()
        return f"Provider switched to {self.llm_provider} ({self.llm_model})"

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

        # Llama (Ollama)
        output.append("\n[bold cyan]llama (via Ollama)[/bold cyan]:")
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

        return "\n".join(output)

    def _register_initial_skills(self):
        """Registers the built-in skills."""
        self.skill_manager.register_skill(TimeSkill())
        self.skill_manager.register_skill(BrowserSkill())
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

        elif self.llm_provider == "llama":
            # Using ChatOllama for local LLM
            # Assumes Ollama is running on localhost:11434 (default)
            try:
                llm = ChatOllama(model=self.llm_model, temperature=0)
            except Exception as e:
                print(f"Error initializing Llama (Ollama): {e}")
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

        # Collect tools from all skills
        self.tools = []
        for skill in self.skill_manager.skills:
            self.tools.extend(skill.get_tools())

        if not self.tools:
            print("Warning: No tools registered.")

        # Create React Agent (LangGraph)
        # Note: prompt can be a string (system prompt) or a SystemMessage.
        system_prompt = "You are Collig, an intelligent AI co-worker. Use the available tools to assist the user. If you need to write code, use the file system tools."
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
            elif self.llm_provider == "llama":
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


    def process_message(self, message: str, session_id: str = None, include_history: bool = True, verbose: bool = True) -> dict:
        """
        Process a user message, optionally within a session context.
        """
        # Save user message to history if session_id is provided
        if session_id:
            self.session_manager.add_message(session_id, "user", message)

        user_msg = message.lower()
        response_data = {}

        try:
            # Execute via LangGraph Agent
            # Input format: {"messages": [HumanMessage(content=message)]}
            # We inject the session ID into the system message context by prepending a SystemMessage

            msgs = []
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

            # We can also pass chat_history if we fetch it from session_manager
            # For now, let's keep it simple (stateless per request for the agent graph,
            # though the session manager tracks history separately).

            # result = self.agent_executor.invoke(inputs)

            # Use stream to capture intermediate steps
            final_state = None
            final_response_text = ""
            has_printed_header = False

            for event in self.agent_executor.stream(inputs):
                for key, value in event.items():
                    if key == "agent":
                        if "messages" in value:
                            msg = value["messages"][-1]
                            if isinstance(msg, AIMessage):
                                # Determine if we have something interesting to print
                                should_print = False

                                # 1. Tool Calls
                                if msg.tool_calls:
                                    should_print = True

                                # 2. Reasoning (mixed with content or explicit)
                                # If there are tool calls and content, it's reasoning.
                                # If there are NO tool calls, it's usually the answer, unless it's a reasoning model outputting <think>
                                # We'll err on the side of printing if it looks like a step.
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
                                                    # If it's a dict, dump it as formatted JSON
                                                    pretty_args = json.dumps(safe_args, indent=2)
                                                    # Indent the whole block to align
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

            # Extract the final response from the last state
            # The stream returns chunks. We need to look at the accumulated state or the last message from the executor.
            # Actually, stream(inputs) yields updates.
            # To get the final message, we might need to rely on the fact that the loop finishes.
            # But the 'event' only contains the *delta* or the *update*.
            # It's safer to just run invoke again? No, that wastes tokens.
            # The final_state['agent']['messages'][-1] should be the final answer IF the last step was the agent.

            # Let's inspect how to get the full final state.
            # If we use stream_mode="values", we get the full list of messages at each step.

            # Re-run with stream_mode="values" to easily get the final result
            # But wait, we can't consume the generator twice.
            # Let's switch to stream_mode="values" for the loop above.
            pass

            # Reworking the loop for stream_mode="values"

            messages = []
            print("\n[Thinking Process]")
            for chunk in self.agent_executor.stream(inputs, stream_mode="values"):
                if "messages" in chunk:
                    messages = chunk["messages"]
                    last_msg = messages[-1]

                    # If it's an AIMessage with tool_calls, print them
                    if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
                         # We might see the same message multiple times if using "values"?
                         # Actually "values" yields the full state.
                         # We only want to print *new* things.
                         # But for simplicity, let's just print the last tool call if it's new.
                         # This is getting complicated.
                         pass

            # Let's stick to the default stream (updates) and reconstruct or just rely on the last update?
            # Actually, the last update from 'agent' node usually contains the final response.
            # But if the last node was 'tools', then 'agent' runs again to generate the final response.
            # So the last event should be from 'agent' and contain the final answer.

            # Let's try a hybrid approach:
            # 1. Use default stream to print thoughts.
            # 2. Capture the last AIMessage content.

            final_response_text = ""
            print("\n[Thinking Process]")
            for event in self.agent_executor.stream(inputs):
                for key, value in event.items():
                    if key == "agent":
                        if "messages" in value:
                            msg = value["messages"][-1]
                            if isinstance(msg, AIMessage):
                                if msg.tool_calls:
                                    for tc in msg.tool_calls:
                                        print(f"  ➜ Planning to use tool: \033[1m{tc['name']}\033[0m")
                                        print(f"    Args: {tc['args']}")
                                elif msg.content:
                                    # Final answer usually
                                    final_response_text = msg.content
                    elif key == "tools":
                         if "messages" in value:
                            msg = value["messages"][-1]
                            # Tool output
                            # print(f"    Tool Output: {msg.content[:100]}...")
                            print(f"    ✔ Tool '{msg.name}' executed.")
            print("[End of Thinking]\n")

            if not final_response_text:
                # Fallback if we missed it (e.g. if the last step didn't explicitly return content in the expected way)
                # This happens if the agent stops?
                # Let's assume the last AIMessage in the loop was the answer.
                pass

            response_text = final_response_text

            response_data = {
                "response": response_text,
                "action": "agent_response"
            }

            # Save AI response to history
            if session_id:
                self.session_manager.add_message(session_id, "ai", response_text)

        except Exception as e:
            response_data = {
                "response": f"I encountered an error: {str(e)}",
                "action": "error"
            }

        return response_data

agent = Agent()
