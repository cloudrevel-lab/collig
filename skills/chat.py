from typing import Dict, Any, List
import os
from .base import Skill

try:
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage, SystemMessage
except ImportError:
    ChatOpenAI = None

class ChatSkill(Skill):
    def __init__(self):
        super().__init__()
        self.llm = None
        api_key = os.getenv("OPENAI_API_KEY")
        if ChatOpenAI and api_key:
            self.llm = ChatOpenAI(api_key=api_key, model="gpt-4o", temperature=0.7)

    @property
    def name(self) -> str:
        return "General Assistant"

    @property
    def description(self) -> str:
        return "Handles general conversation, questions, math problems, and small talk when no other specific skill matches."

    @property
    def triggers(self) -> List[str]:
        # These are fallback triggers. The LLM intent classifier should prefer this skill
        # for general queries.
        return ["chat", "say", "speak", "calculate", "what is", "who is", "tell me", "explain"]

    def _initialize_llm(self):
        """Attempts to initialize the LLM if configuration is available."""
        if self.llm:
            return

        api_key = self.config.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")

        if ChatOpenAI and api_key:
            try:
                self.llm = ChatOpenAI(api_key=api_key, model="gpt-4o", temperature=0.7)
            except Exception as e:
                print(f"Failed to initialize ChatOpenAI: {e}")

    @property
    def required_config(self) -> List[str]:
        return ["OPENAI_API_KEY"]

    def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        message = context.get("message", "")

        self._initialize_llm()

        if not self.llm:
            return {
                "response": "I need an **OpenAI API Key** to chat.\nPlease run: `config set OPENAI_API_KEY sk-...`",
                "action": "missing_config"
            }

        try:
            # Using LangChain
            messages = [
                SystemMessage(content="You are Collig, a helpful AI co-worker. Answer the user's question concisely and helpfully."),
                HumanMessage(content=message)
            ]

            response = self.llm.invoke(messages)
            answer = response.content.strip()

            return {
                "response": answer,
                "action": "chat_response"
            }

        except Exception as e:
            return {
                "response": f"I tried to think of an answer but encountered an error: {str(e)}",
                "action": "error"
            }
