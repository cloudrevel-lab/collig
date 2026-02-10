from typing import Dict, Any, List
import os
from .base import Skill

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

class PromptSkill(Skill):
    """
    A skill defined by a markdown file with YAML frontmatter.
    The content of the markdown file serves as the system prompt for the LLM.
    """
    def __init__(self, name: str, description: str, content: str, path: str):
        super().__init__()
        self._name = name
        self._description = description
        self.content = content # The system prompt
        self.path = path
        self.client = None
        
        # Initialize OpenAI client
        api_key = os.getenv("OPENAI_API_KEY")
        if OpenAI and api_key:
            self.client = OpenAI(api_key=api_key)

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def triggers(self) -> List[str]:
        # Generate triggers from name and description?
        # Or just rely on LLM router.
        # Let's use the name words as basic triggers.
        return self._name.lower().split()

    def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        if not self.client:
             return {
                "response": "Error: OpenAI API key not found. This skill requires an LLM.",
                "action": None
            }

        user_message = context.get("message", "")
        
        # Combine skill instructions with user message
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": self.content},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.7
            )
            
            content = response.choices[0].message.content
            return {
                "response": content,
                "action": None
            }
            
        except Exception as e:
            return {
                "response": f"Error executing skill '{self.name}': {str(e)}",
                "action": None
            }
