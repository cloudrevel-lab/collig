from typing import Dict, Any, List
from langchain_core.tools import tool, BaseTool
from .base import Skill

# Global reference to menu functions - will be set by CLI
_menu_functions = None

def set_menu_functions(select_func, menu_func):
    """Set the menu functions from the CLI."""
    global _menu_functions
    _menu_functions = {
        "select": select_func,
        "menu": menu_func
    }

class MenuSkill(Skill):
    """Skill for interactive menu selection with arrow keys."""

    @property
    def name(self) -> str:
        return "Interactive Menu"

    @property
    def description(self) -> str:
        return "Provides interactive menu selection with arrow key navigation."

    def get_tools(self) -> List[BaseTool]:

        @tool
        def select_from_menu(title: str, options: str) -> str:
            """
            Display an interactive menu and let the user select an option using arrow keys.

            Args:
                title: The menu title or question to display
                options: Comma-separated list of options (e.g., "Option 1, Option 2, Option 3")

            Returns:
                The selected option text
            """
            if not _menu_functions:
                return "Error: Interactive menu not available in this environment."

            # Parse options - split by comma and trim whitespace
            option_list = [opt.strip() for opt in options.split(",")]
            option_list = [opt for opt in option_list if opt]  # Remove empty

            if not option_list:
                return "Error: No options provided."

            select_func = _menu_functions["select"]
            result = select_func(title, option_list, 0)

            if result is None:
                return "User cancelled the menu selection."

            return result

        @tool
        def select_option_by_number(title: str, options: str) -> str:
            """
            Legacy method - lets user type a number to select an option.
            Prefer using select_from_menu for interactive arrow key selection.

            Args:
                title: The menu title or question
                options: Comma-separated list of options

            Returns:
                The selected option text
            """
            # Just delegate to the interactive menu for consistency
            return select_from_menu(title, options)

        return [select_from_menu, select_option_by_number]
