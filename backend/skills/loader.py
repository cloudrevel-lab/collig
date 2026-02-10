import os
import yaml
from typing import List, Optional
from .base import Skill
from .prompt import PromptSkill

class SkillLoader:
    def __init__(self, skills_dir: str = "skills"):
        self.skills_dir = skills_dir

    def load_skills(self) -> List[Skill]:
        """
        Scans the skills directory for subdirectories containing SKILL.md.
        Returns a list of PromptSkill instances.
        """
        skills = []
        
        # Look in imported/ or external/ directory? 
        # The spec says ./<agent>/skills/ so we can scan the current skills dir too,
        # but probably better to have a dedicated folder for external skills to avoid confusion.
        # Let's check "skills/imported" and "skills/external" or just look for any subdirectory with SKILL.md
        
        if not os.path.exists(self.skills_dir):
            return []

        # Walk through the skills directory
        for root, dirs, files in os.walk(self.skills_dir):
            if "SKILL.md" in files:
                skill_path = os.path.join(root, "SKILL.md")
                skill = self._load_skill_from_file(skill_path)
                if skill:
                    skills.append(skill)
                    
        return skills

    def _load_skill_from_file(self, path: str) -> Optional[PromptSkill]:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Parse Frontmatter
            # Assuming standard Jekyll-style frontmatter:
            # ---
            # key: value
            # ---
            # content
            
            parts = content.split('---', 2)
            if len(parts) < 3:
                # No valid frontmatter
                return None
                
            frontmatter_yaml = parts[1]
            skill_content = parts[2].strip()
            
            metadata = yaml.safe_load(frontmatter_yaml)
            
            if not isinstance(metadata, dict):
                return None
                
            name = metadata.get("name")
            description = metadata.get("description", "No description provided.")
            
            if not name:
                return None
                
            return PromptSkill(
                name=name,
                description=description,
                content=skill_content,
                path=path
            )
            
        except Exception as e:
            print(f"Error loading skill from {path}: {e}")
            return None
