"""
Skill Manager - Loads and manages portable skills following agentskills.io spec.
"""
from typing import List, Dict, Optional, Any
import os
from pathlib import Path
from .base import Skill, discover_skills


class SkillManager:
    """
    Manages the lifecycle of portable skills.
    
    Supports:
    - Discovering skills from directories with SKILL.md
    - Loading skills dynamically
    - Finding skills via LLM intent detection or keyword matching
    - Executing skills with context
    """

    def __init__(self, skills_dir: Optional[Path] = None):
        """
        Initialize the skill manager.
        
        Args:
            skills_dir: Path to the skills directory. If None, uses default location.
        """
        self.skills: List[Skill] = []
        self.client = None
        self.skills_dir = skills_dir or Path(__file__).parent

    def configure(self, config: Dict[str, Any]):
        """
        Configure the skill manager with settings.
        
        Args:
            config: Configuration dictionary
        """
        # Configure all loaded skills
        for skill in self.skills:
            skill.configure(config)

        # Initialize OpenAI client if available
        if not self.client:
            try:
                from openai import OpenAI
                api_key = config.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
                if api_key:
                    self.client = OpenAI(api_key=api_key)
            except ImportError:
                pass

    def discover_and_load_skills(self):
        """
        Discover and load all skills from the skills directory.
        
        Skills are loaded from directories containing SKILL.md
        """
        self.skills = discover_skills(self.skills_dir)
        
        # Print summary
        print(f"\nLoaded {len(self.skills)} skills:")
        for skill in self.skills:
            print(f"  - {skill.name}: {skill.description}")

    def register_skill(self, skill: Skill):
        """
        Register a skill instance.
        
        Args:
            skill: Skill instance to register
        """
        import sys
        sys.stdout.write(f"\r\033[KRegistering skill: {skill.name}")
        sys.stdout.flush()
        self.skills.append(skill)

    def get_tools(self) -> List[Any]:
        """
        Get all tools from all enabled skills.
        
        Returns:
            List of all available tools
        """
        tools = []
        for skill in self.skills:
            if skill.enabled:
                tools.extend(skill.get_tools())
        return tools

    def find_skill(self, message: str) -> Optional[Skill]:
        """
        Finds a skill that matches the user's message.
        
        Prioritizes LLM-based intent recognition if available,
        falls back to keyword matching.
        
        Args:
            message: User message to analyze
            
        Returns:
            Matching skill or None
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
            if not skill.enabled:
                continue
            
            # Check triggers
            for trigger in skill.triggers:
                if trigger in message:
                    return skill
            
            # Also check skill name and description
            if skill.name.lower() in message or skill.description.lower() in message:
                return skill
        
        return None

    def _find_skill_llm(self, message: str) -> Optional[Skill]:
        """
        Uses LLM to determine the best skill for the message.
        
        Args:
            message: User message to analyze
            
        Returns:
            Matching skill or None
        """
        # Build skill descriptions for the LLM
        skills_info = []
        for skill in self.skills:
            if not skill.enabled:
                continue
            triggers_str = ", ".join(skill.triggers) if skill.triggers else "N/A"
            skills_info.append(
                f"- Name: {skill.name}\n"
                f"  Description: {skill.description}\n"
                f"  Triggers: {triggers_str}"
            )

        if not skills_info:
            return None

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
            "4. Be flexible with natural language variations.\n"
            "5. Do not include any other text, explanation, or punctuation."
        )

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

    def get_skill_by_name(self, name: str) -> Optional[Skill]:
        """
        Get a skill by its exact name.
        
        Args:
            name: Skill name
            
        Returns:
            Skill instance or None
        """
        for skill in self.skills:
            if skill.name == name:
                return skill
        return None

    def list_skills(self) -> List[Dict[str, Any]]:
        """
        List all available skills with their metadata.
        
        Returns:
            List of skill metadata dictionaries
        """
        return [
            {
                "name": skill.name,
                "description": skill.description,
                "enabled": skill.enabled,
                "triggers": skill.triggers,
                "tools": [
                    {
                        "name": tool.name if hasattr(tool, "name") else tool.__name__,
                        "description": tool.description if hasattr(tool, "description") else tool.__doc__,
                    }
                    for tool in skill.get_tools()
                ]
            }
            for skill in self.skills
        ]

    def export_skills_manifest(self) -> Dict[str, Any]:
        """
        Export a manifest of all skills in agentskills.io compatible format.
        
        Returns:
            Dictionary containing skill manifests
        """
        return {
            "skills": [skill.to_skill_format() for skill in self.skills],
            "count": len(self.skills)
        }
