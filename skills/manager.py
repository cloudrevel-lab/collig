from typing import List, Dict, Optional, Any
import os
from .base import Skill

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

class SkillManager:
    def __init__(self):
        self.skills: List[Skill] = []
        self.client = None
        # Check for API key and initialize client
        api_key = os.getenv("OPENAI_API_KEY")
        if OpenAI and api_key:
            self.client = OpenAI(api_key=api_key)

    def register_skill(self, skill: Skill):
        """Registers a new skill."""
        # Use carriage return to overwrite line
        # Pad with spaces to clear previous longer names
        import sys
        sys.stdout.write(f"\r\033[KRegistering skill: {skill.name}")
        sys.stdout.flush()
        self.skills.append(skill)

    def find_skill(self, message: str) -> Optional[Skill]:
        """
        Finds a skill that matches the user's message.
        Prioritizes LLM-based intent recognition if available.
        """
        if self.client:
            try:
                skill = self._find_skill_llm(message)
                if skill:
                    return skill
            except Exception as e:
                print(f"LLM intent detection failed: {e}. Falling back to keywords.")

        # Fallback to simple keyword matching
        message = message.lower()
        for skill in self.skills:
            for trigger in skill.triggers:
                if trigger in message:
                    return skill
        return None

    def _find_skill_llm(self, message: str) -> Optional[Skill]:
        """Uses LLM to determine the best skill for the message."""
        # Use a cheaper/faster model for intent classification if possible, 
        # or stick to what's configured.
        # But wait, self.client is hardcoded to OpenAI currently.
        # We should respect the global config if possible, but for now we rely on the client init.
        
        skills_info = []
        for skill in self.skills:
            # Create a rich description for the LLM
            triggers_str = ", ".join(skill.triggers)
            skills_info.append(f"- Name: {skill.name}\n  Description: {skill.description}\n  Triggers: {triggers_str}")

        skills_text = "\n".join(skills_info)

        system_prompt = (
            "You are an intelligent intent classifier for an AI agent.\n"
            "Your task is to determine which skill from the available list best matches the user's request.\n"
            "Available Skills:\n"
            f"{skills_text}\n\n"
            "Rules:\n"
            "1. Analyze the user's message and the capabilities of each skill.\n"
            "2. If a skill matches the intent, return ONLY the exact Name of the skill.\n"
            "3. If no skill matches, return 'None'.\n"
            "4. Be flexible with natural language variations (e.g., 'check mail' should match 'Email Manager').\n"
            "5. Do not include any other text, explanation, or punctuation."
        )

        # Use gpt-3.5-turbo or similar for speed/cost if available, else 4o
        response = self.client.chat.completions.create(
            model="gpt-3.5-turbo", 
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message}
            ],
            temperature=0.0
        )

        skill_name = response.choices[0].message.content.strip()

        if skill_name == "None":
            return None

        for skill in self.skills:
            if skill.name == skill_name:
                return skill

        return None

    def execute_skill(self, skill: Skill, message: str, shared_context: Dict[str, Any] = None, runtime_context: Dict[str, Any] = None) -> Dict[str, Any]:
        """Executes a skill with the given context."""
        context = {"message": message}
        if shared_context:
            context.update(shared_context)
        if runtime_context:
            context.update(runtime_context)

        try:
            return skill.execute(context)
        except Exception as e:
            return {
                "response": f"Error executing skill '{skill.name}': {str(e)}",
                "action": "error"
            }
