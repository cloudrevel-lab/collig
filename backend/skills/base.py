from abc import ABC, abstractmethod
from typing import Dict, Any, List
from langchain_core.tools import BaseTool

class Skill(ABC):
    """
    Abstract Base Class for all Skills.
    Skills now provide tools that can be used by the main Agent.
    """

    def __init__(self):
        self.config: Dict[str, Any] = {}

    @property
    @abstractmethod
    def name(self) -> str:
        """The name of the skill."""
        pass

    @property
    def description(self) -> str:
        """A brief description of what the skill does."""
        return f"Skill: {self.name}"

    def get_tools(self) -> List[BaseTool]:
        """
        Returns a list of LangChain tools provided by this skill.
        Default implementation returns an empty list.
        """
        return []

    def configure(self, config: Dict[str, Any]):
        """
        Configure the skill with settings.
        """
        self.config.update(config)

    @property
    def required_config(self) -> List[str]:
        """List of configuration keys required by this skill."""
        return []
