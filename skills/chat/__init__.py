"""
General Assistant Skill - Portable implementation following agentskills.io spec.

Handles general conversation, questions, math problems, and small talk.
"""
from typing import Dict, Any, List
import os
from langchain_core.tools import tool, BaseTool
from skills.base import Skill

try:
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage, SystemMessage
except ImportError:
    ChatOpenAI = None


class ChatSkill(Skill):
    """Handles general conversation and questions."""

    def __init__(self, skill_root=None):
        super().__init__(skill_root)
        self.llm = None

    def _initialize_llm(self):
        """Initialize the LLM if configuration is available."""
        if self.llm:
            return

        llm_provider = self.config.get("LLM_PROVIDER", "openai")
        api_key = None
        base_url = None
        model_name = "gpt-4o"

        if llm_provider == "dashscope":
            api_key = self.config.get("DASHSCOPE_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
            endpoint_region = self.config.get("DASHSCOPE_ENDPOINT", "china")
            endpoints = {
                "china": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "singapore": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                "international": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
            }
            base_url = endpoints.get(endpoint_region, endpoints["china"])
            model_name = "qwen-plus"
        else:
            api_key = self.config.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")

        if ChatOpenAI and api_key:
            try:
                if base_url:
                    self.llm = ChatOpenAI(api_key=api_key, base_url=base_url, model=model_name, temperature=0.7)
                else:
                    self.llm = ChatOpenAI(api_key=api_key, model=model_name, temperature=0.7)
            except Exception as e:
                print(f"Failed to initialize ChatOpenAI: {e}")

    @property
    def name(self) -> str:
        return "General Assistant"

    @property
    def description(self) -> str:
        return "Handles general conversation, questions, math problems, and small talk"

    @property
    def triggers(self) -> List[str]:
        return [
            "chat", "say", "speak", "calculate", "what is",
            "who is", "tell me", "explain"
        ]

    @property
    def required_config(self) -> List[str]:
        return ["OPENAI_API_KEY"]

    def get_tools(self) -> List[BaseTool]:

        @tool
        def chat(message: str) -> str:
            """
            Engage in general conversation and answer questions.
            
            Args:
                message: The user's message or question
            """
            self._initialize_llm()

            if not self.llm:
                return "I need an API Key to chat. Please configure OPENAI_API_KEY or DASHSCOPE_API_KEY."

            try:
                messages = [
                    SystemMessage(content="You are Collig, a helpful AI co-worker. Answer the user's question concisely and helpfully."),
                    HumanMessage(content=message)
                ]

                response = self.llm.invoke(messages)
                answer = response.content.strip()

                return answer

            except Exception as e:
                return f"I encountered an error: {str(e)}"

        return [chat]
