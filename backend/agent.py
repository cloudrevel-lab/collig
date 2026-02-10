import os
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
from session import SessionManager

from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import HumanMessage, SystemMessage

class Agent:
    def __init__(self):
        self.name = "Collig"
        self.skill_manager = SkillManager()
        self.session_manager = SessionManager()
        self.shared_context = {} # Store runtime context (e.g., last_created_dir)
        self.active_skill_name = None # For multi-turn skills

        # Load provider config
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
            self.llm_model = "llama3" # Default for llama
        elif self.llm_provider == "openai":
            self.llm_model = "gpt-4o" # Default for openai

        print(f"Switching provider to {self.llm_provider} (Model: {self.llm_model})")
        self._init_langchain_agent()
        return f"Provider switched to {self.llm_provider} ({self.llm_model})"


    def _register_initial_skills(self):
        """Registers the built-in skills."""
        self.skill_manager.register_skill(TimeSkill())
        self.skill_manager.register_skill(BrowserSkill())
        self.skill_manager.register_skill(WeatherSkill())
        self.skill_manager.register_skill(FileSystemSkill())
        # self.skill_manager.register_skill(ProgrammingSkill())
        # self.skill_manager.register_skill(EmailSkill())
        # self.skill_manager.register_skill(SetupWizardSkill())
        # self.skill_manager.register_skill(MapSkill())
        self.skill_manager.register_skill(SystemSkill())
        self.skill_manager.register_skill(MemorySkill())
        self.skill_manager.register_skill(BookmarkSkill())
        # self.skill_manager.register_skill(ChatSkill()) # Fallback / General Skill

    def _init_langchain_agent(self):
        """Initializes the LangChain Agent with tools from skills."""

        llm = None

        if self.llm_provider == "openai":
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                print("Warning: OPENAI_API_KEY not found. Agent will not function correctly.")
                return
            llm = ChatOpenAI(model=self.llm_model, temperature=0)

        elif self.llm_provider == "llama":
            # Using ChatOllama for local LLM
            # Assumes Ollama is running on localhost:11434 (default)
            try:
                llm = ChatOllama(model=self.llm_model, temperature=0)
            except Exception as e:
                print(f"Error initializing Llama (Ollama): {e}")
                return
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


    def process_message(self, message: str, session_id: str = None) -> dict:
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
            # or simply including it in the HumanMessage if we can't easily modify the system prompt per-request in prebuilt.
            # create_react_agent's state_modifier is fixed at creation.
            # So we prepend a SystemMessage to the conversation.

            msgs = []
            if session_id:
                msgs.append(SystemMessage(content=f"Current Session ID: {session_id}"))
            msgs.append(HumanMessage(content=message))

            inputs = {"messages": msgs}

            # We can also pass chat_history if we fetch it from session_manager
            # For now, let's keep it simple (stateless per request for the agent graph,
            # though the session manager tracks history separately).

            result = self.agent_executor.invoke(inputs)

            # Result contains 'messages'. The last message is the AI response.
            last_message = result["messages"][-1]
            response_text = last_message.content

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
