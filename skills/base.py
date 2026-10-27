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

    def ensure_loaded(self):
        """Load and return the concrete skill instance.

        Concrete skills are already loaded, so this is a no-op. LazySkill
        overrides it to import the module on first access to skill-specific
        attributes (for example the web API reading skill.vectorstore).
        """
        return self

    def tool_metadata(self) -> List[Dict[str, str]]:
        """Cheap name/description pairs for this skill's tools."""
        out: List[Dict[str, str]] = []
        for tool in self.get_tools():
            name = getattr(tool, "name", None) or getattr(tool, "__name__", None)
            if not name:
                continue
            description = getattr(tool, "description", None) or ""
            out.append({"name": str(name), "description": str(description)})
        return out

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
            "tools": self.tool_metadata(),
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
    spec = importlib.util.spec_from_file_location(f"skill_{skill_path.name}", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Find the Skill class (first subclass of Skill)
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if isinstance(attr, type) and issubclass(attr, Skill) and attr is not Skill:
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


# ---------------------------------------------------------------------------
# Lazy skill loading
# ---------------------------------------------------------------------------
#
# Importing every skill module at CLI startup costs seconds and can trigger
# network calls from configure() (the bookmarks skill used to call the
# embeddings API just to verify a key). A LazySkill reads only SKILL.md --
# name, description, triggers, tool names -- and imports the real module the
# first time the skill is actually selected.

_TOOL_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "skill",
    "tools",
    "your",
    "you",
    "are",
    "can",
    "will",
    "use",
    "using",
    "about",
    "into",
}


def _simple_frontmatter_parse(block):
    """Best-effort parser for SKILL.md frontmatter that is not valid YAML."""
    meta = {}
    current_key = None
    current_list = None
    for raw in block.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        stripped = raw.strip()
        indent = len(raw) - len(raw.lstrip())
        if indent == 0 and ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if value:
                meta[key] = value.strip("'\"")
                current_key = None
                current_list = None
            else:
                current_key = key
                current_list = []
                meta[key] = current_list
            continue
        if current_key and stripped.startswith("- "):
            item = stripped[2:].strip()
            if current_key == "tools" and ":" in item:
                tname, tdesc = item.split(":", 1)
                current_list.append({"name": tname.strip(), "description": tdesc.strip()})
            else:
                current_list.append(item.strip("'\""))
    return meta


def parse_skill_frontmatter(skill_root):
    """Read SKILL.md metadata without importing the skill module."""
    path = Path(skill_root) / "SKILL.md"
    if not path.exists():
        return {}
    try:
        content = path.read_text()
    except OSError:
        return {}
    if not content.startswith("---"):
        return {}
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}
    block = parts[1]
    try:
        data = yaml.safe_load(block)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return _simple_frontmatter_parse(block)


class ToolStub:
    """Name/description-only stand-in for a tool that has not been loaded."""

    def __init__(self, name, description=""):
        self.name = name
        self.description = description
        self.is_stub = True

    def __repr__(self):
        return "ToolStub(%r)" % (self.name,)


class LazySkill(Skill):
    """
    A Skill backed by SKILL.md metadata until the module is first needed.

    The public surface the router needs (name, description, triggers,
    required_config, tool names) is answered from SKILL.md. get_tools()
    imports and configures the real class on demand. This keeps startup cost
    and the per-turn tool payload proportional to what the user asks for.
    """

    def __init__(self, skill_root):
        root = Path(skill_root)
        super().__init__(root)
        self._metadata = parse_skill_frontmatter(root)
        self._delegate = None
        self._tool_cache = None

    @property
    def name(self):
        return str(self._metadata.get("name") or self.skill_root.name)

    @property
    def description(self):
        return str(self._metadata.get("description") or ("Skill: " + self.name))

    @property
    def metadata(self):
        return self._metadata

    @property
    def triggers(self):
        raw = self._metadata.get("triggers") or []
        if isinstance(raw, str):
            raw = [raw]
        out = [str(item).lower() for item in raw if str(item).strip()]
        if out:
            return out
        words = []
        for source in (self.name, self.description):
            for word in str(source).lower().replace("-", " ").split():
                word = word.strip(".,:;()[]{}'\"")
                if len(word) > 3 and word not in _TOOL_STOPWORDS and word not in words:
                    words.append(word)
        return words

    @property
    def required_config(self):
        cfg = self._metadata.get("config")
        if isinstance(cfg, dict):
            required = cfg.get("required") or []
            if isinstance(required, str):
                return [required]
            return [str(item) for item in required]
        required = self._metadata.get("required_config")
        if isinstance(required, list):
            return [str(item) for item in required]
        return []

    def tool_metadata(self):
        if self._delegate is not None and self._tool_cache is not None:
            return self._delegate.tool_metadata()
        raw = self._metadata.get("tools") or []
        out = []
        for item in raw:
            if isinstance(item, dict):
                name = item.get("name")
                if name:
                    out.append({"name": str(name), "description": str(item.get("description") or "")})
            elif isinstance(item, str) and item.strip():
                out.append({"name": item.strip(), "description": ""})
        return out

    def ensure_loaded(self):
        return self._load()

    def _load(self):
        if self._delegate is not None:
            return self._delegate
        delegate = load_skill_from_path(self.skill_root)
        if delegate is None:
            raise RuntimeError("Could not load skill module for " + self.name)
        delegate.enabled = self.enabled
        if self.config:
            delegate.configure(self.config)
        self._delegate = delegate
        return delegate

    def configure(self, config):
        super().configure(config)
        if self._delegate is not None:
            self._delegate.configure(config)

    def get_tools(self):
        if self._tool_cache is not None:
            return self._tool_cache
        self._tool_cache = list(self._load().get_tools())
        return self._tool_cache

    def to_skill_format(self):
        return {
            "name": self.name,
            "description": self.description,
            "instructions": self.instructions,
            "tools": self.tool_metadata(),
            "required_config": self.required_config,
        }
