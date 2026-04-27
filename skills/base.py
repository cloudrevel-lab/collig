"""
Portable Skill Base Class following agentskills.io specification.

A Skill is a portable, reusable unit of agent capability that can be:
- Discovered via SKILL.md metadata
- Activated by the agent
- Executed with standardized tool interfaces
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Callable
from pathlib import Path
import yaml


class Skill(ABC):
    """
    Abstract Base Class for all Skills following agentskills.io spec.
    
    Skills provide tools that can be used by agents and are defined by:
    - SKILL.md: Metadata file with name, description, instructions
    - scripts/: Optional directory with executable code
    - references/: Optional documentation
    - assets/: Optional templates and resources
    """

    def __init__(self, skill_root: Optional[Path] = None):
        """
        Initialize a skill.
        
        Args:
            skill_root: Path to the skill's root directory (where SKILL.md lives)
        """
        self.skill_root = Path(skill_root) if skill_root else Path(__file__).parent
        self.config: Dict[str, Any] = {}
        self._enabled: bool = True
        self._metadata: Optional[Dict[str, Any]] = None

    @property
    @abstractmethod
    def name(self) -> str:
        """The unique name of the skill."""
        pass

    @property
    def description(self) -> str:
        """A brief description of what the skill does."""
        return f"Skill: {self.name}"

    @property
    def instructions(self) -> str:
        """
        Detailed instructions for using this skill.
        Read from SKILL.md if available, otherwise use default.
        """
        skill_md_path = self.skill_root / "SKILL.md"
        if skill_md_path.exists():
            try:
                content = skill_md_path.read_text()
                # Parse YAML frontmatter if present
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        return parts[2].strip()
                return content.strip()
            except Exception:
                pass
        return self.__class__.__doc__ or f"Use the {self.name} skill to {self.description.lower()}."

    @property
    def metadata(self) -> Dict[str, Any]:
        """
        Load and return metadata from SKILL.md.
        Cached after first load.
        """
        if self._metadata is not None:
            return self._metadata

        skill_md_path = self.skill_root / "SKILL.md"
        self._metadata = {}

        if skill_md_path.exists():
            try:
                content = skill_md_path.read_text()
                # Parse YAML frontmatter
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        self._metadata = yaml.safe_load(parts[1]) or {}
            except Exception:
                pass

        # Fill in defaults from properties
        self._metadata.setdefault("name", self.name)
        self._metadata.setdefault("description", self.description)

        return self._metadata

    def get_tools(self) -> List[Any]:
        """
        Returns a list of tools provided by this skill.
        Tools can be LangChain BaseTool instances or any callable.
        
        Subclasses should override this to provide their tools.
        """
        return []

    def configure(self, config: Dict[str, Any]):
        """
        Configure the skill with settings.
        
        Args:
            config: Configuration dictionary
        """
        self.config.update(config)

    @property
    def enabled(self) -> bool:
        """Whether this skill is enabled."""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        """Set whether this skill is enabled."""
        self._enabled = value

    @property
    def required_config(self) -> List[str]:
        """List of configuration keys required by this skill."""
        return []

    @property
    def triggers(self) -> List[str]:
        """
        Optional list of trigger keywords for simple matching.
        Used as fallback when LLM intent detection is unavailable.
        """
        return []

    def to_skill_format(self) -> Dict[str, Any]:
        """
        Export the skill in agentskills.io compatible format.
        
        Returns:
            Dictionary with skill metadata and tool definitions
        """
        return {
            "name": self.name,
            "description": self.description,
            "instructions": self.instructions,
            "tools": [
                {
                    "name": tool.name if hasattr(tool, "name") else tool.__name__,
                    "description": tool.description if hasattr(tool, "description") else tool.__doc__,
                }
                for tool in self.get_tools()
            ],
            "required_config": self.required_config,
        }


def skill_tool(name: str = None, description: str = None):
    """
    Decorator to mark a function as a skill tool.
    
    This is an alternative to LangChain's @tool decorator for better portability.
    
    Args:
        name: Optional name for the tool (defaults to function name)
        description: Optional description (defaults to docstring)
    
    Returns:
        Decorated function with tool metadata attached
    """
    def decorator(func: Callable) -> Callable:
        if name:
            func._tool_name = name
        if description:
            func._tool_description = description
        func._is_skill_tool = True
        return func
    return decorator


def load_skill_from_path(skill_path: Path) -> Optional[Skill]:
    """
    Load a skill from a directory path.
    
    Args:
        skill_path: Path to the skill directory
        
    Returns:
        Loaded skill instance or None if loading fails
    """
    import importlib.util
    
    skill_path = Path(skill_path)
    if not skill_path.exists():
        return None

    # Look for SKILL.md to validate this is a skill directory
    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        return None

    # Look for the main skill module
    # Priority: __init__.py, then {directory_name}.py, then any .py file
    init_py = skill_path / "__init__.py"
    dir_name_py = skill_path / f"{skill_path.name}.py"

    module_path = None
    if init_py.exists():
        module_path = init_py
    elif dir_name_py.exists():
        module_path = dir_name_py
    else:
        # Find any .py file
        py_files = list(skill_path.glob("*.py"))
        if py_files:
            module_path = py_files[0]

    if not module_path:
        return None

    # Load the module
    spec = importlib.util.spec_from_file_location(
        f"skill_{skill_path.name}",
        module_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Find the Skill class (first subclass of Skill)
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if (isinstance(attr, type) and 
            issubclass(attr, Skill) and 
            attr is not Skill):
            return attr(skill_root=skill_path)

    return None


def discover_skills(skills_dir: Path) -> List[Skill]:
    """
    Discover all skills in a directory.
    
    Args:
        skills_dir: Path to the skills directory
        
    Returns:
        List of loaded skill instances
    """
    skills = []
    skills_dir = Path(skills_dir)

    if not skills_dir.exists():
        return skills

    # Look for skill directories (those containing SKILL.md)
    for item in skills_dir.iterdir():
        if item.is_dir():
            skill = load_skill_from_path(item)
            if skill:
                skills.append(skill)
        elif item.name == "SKILL.md":
            # Single-file skill (SKILL.md in root)
            skill = load_skill_from_path(skills_dir)
            if skill:
                skills.append(skill)
                break

    return skills
