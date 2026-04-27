"""
Menu Skill - Provides interactive menu capabilities.
"""
from typing import List, Callable, Any
from langchain_core.tools import tool, BaseTool
from skills.base import Skill

# Global menu functions
_menu_functions = {}

def set_menu_functions(select_func: Callable, menu_func: Callable):
    """Set the menu functions from the CLI."""
    global _menu_functions
    _menu_functions = {
        "select": select_func,
        "menu": menu_func
    }

def get_menu_functions():
    """Get the menu functions."""
    return _menu_functions


class MenuSkill(Skill):
    """Provides interactive menu capabilities."""

    def __init__(self, skill_root=None):
        super().__init__(skill_root)

    @property
    def name(self) -> str:
        return "Menu"

    @property
    def description(self) -> str:
        return "Provides interactive menu navigation and selection"

    @property
    def triggers(self) -> List[str]:
        return ["menu", "show options", "select from menu"]

    def get_tools(self) -> List[BaseTool]:

        @tool
        def show_menu(options: List[str], title: str = "Menu") -> str:
            """
            Display an interactive menu.

            Args:
                options: List of menu options
                title: Menu title
            """
            menu_text = f"{title}\n" + "=" * len(title) + "\n"
            for i, option in enumerate(options, 1):
                menu_text += f"{i}. {option}\n"
            return menu_text

        return [show_menu]
