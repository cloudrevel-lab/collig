"""
Built-in Skills - Core skills required by the agent.

Provides TimeSkill, BrowserSkill, and ThinkingToggleSkill.
"""
from typing import List
import datetime
import webbrowser
from langchain_core.tools import tool, BaseTool
from skills.base import Skill


# Global agent instance reference for browser skill
_agent_instance = None


def set_agent_instance(agent):
    """Set the global agent instance for use in browser skill."""
    global _agent_instance
    _agent_instance = agent


class TimeSkill(Skill):
    """Provides time and date information."""

    def __init__(self, skill_root=None):
        super().__init__(skill_root)

    @property
    def name(self) -> str:
        return "Time"

    @property
    def description(self) -> str:
        return "Provides current time and date information"

    @property
    def triggers(self) -> List[str]:
        return ["time", "date", "current time", "what time", "today"]

    def get_tools(self) -> List[BaseTool]:

        @tool
        def get_current_time() -> str:
            """
            Returns the current time and date.
            """
            now = datetime.datetime.now()
            return f"Current time: {now.strftime('%Y-%m-%d %H:%M:%S')}"

        return [get_current_time]


class BrowserSkill(Skill):
    """Provides web browser capabilities."""

    def __init__(self, skill_root=None):
        super().__init__(skill_root)

    @property
    def name(self) -> str:
        return "Browser"

    @property
    def description(self) -> str:
        return "Opens URLs in the system web browser"

    @property
    def triggers(self) -> List[str]:
        return ["open url", "open link", "browse", "website"]

    def get_tools(self) -> List[BaseTool]:

        @tool
        def open_url(url: str) -> str:
            """
            Opens a URL in the system web browser.

            Args:
                url: The URL to open
            """
            try:
                webbrowser.open(url)
                return f"Opened {url} in browser"
            except Exception as e:
                return f"Failed to open {url}: {e}"

        return [open_url]


class ThinkingToggleSkill(Skill):
    """Provides ability to toggle thinking/verbose mode."""

    def __init__(self, skill_root=None):
        super().__init__(skill_root)

    @property
    def name(self) -> str:
        return "Thinking Toggle"

    @property
    def description(self) -> str:
        return "Toggle thinking/verbose mode for agent responses"

    @property
    def triggers(self) -> List[str]:
        return ["toggle thinking", "verbose mode", "quiet mode", "thinking"]

    def get_tools(self) -> List[BaseTool]:

        @tool
        def toggle_thinking(enable: bool = None) -> str:
            """
            Toggle thinking/verbose mode on or off.
            If no argument is provided, toggles the current state.

            Args:
                enable: True to enable, False to disable, None to toggle
            """
            global _agent_instance
            if _agent_instance is None:
                return "Error: Agent instance not initialized"

            if enable is None:
                # Toggle current state
                _agent_instance.verbose = not getattr(_agent_instance, 'verbose', True)
            else:
                _agent_instance.verbose = bool(enable)

            state = "enabled" if _agent_instance.verbose else "disabled"
            return f"Thinking mode {state}"

        return [toggle_thinking]
