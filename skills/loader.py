"""
Skill Loader - Utility for loading skills dynamically.
"""
from typing import List, Optional, Dict, Any
from pathlib import Path
from skills.base import Skill, load_skill_from_path, discover_skills


class SkillLoader:
    """Loads skills from directories or manifest files."""

    def __init__(self, skills_dir: Optional[Path] = None):
        self.skills_dir = skills_dir or Path(__file__).parent

    def load_skill(self, skill_name: str) -> Optional[Skill]:
        """
        Load a specific skill by name.

        Args:
            skill_name: Name of the skill to load

        Returns:
            Skill instance or None if not found
        """
        skill_path = self.skills_dir / skill_name
        if skill_path.exists():
            return load_skill_from_path(skill_path)
        return None

    def load_all_skills(self) -> List[Skill]:
        """
        Load all skills from the skills directory.

        Returns:
            List of loaded skill instances
        """
        return discover_skills(self.skills_dir)

    def load_skills(self) -> List[Skill]:
        """
        Load all skills from the skills directory.
        Alias for load_all_skills for backwards compatibility.

        Returns:
            List of loaded skill instances
        """
        return self.load_all_skills()

    def load_skills_from_manifest(self, manifest_path: Path) -> List[Skill]:
        """
        Load skills based on a manifest file.

        Args:
            manifest_path: Path to the manifest file

        Returns:
            List of loaded skill instances
        """
        # TODO: Implement manifest-based loading
        return []

    def configure_skills(self, skills: List[Skill], config: Dict[str, Any]):
        """
        Configure multiple skills with the same config.

        Args:
            skills: List of skills to configure
            config: Configuration dictionary
        """
        for skill in skills:
            skill.configure(config)
