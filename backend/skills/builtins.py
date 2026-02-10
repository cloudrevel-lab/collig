from typing import Dict, Any, List
from datetime import datetime
from langchain_core.tools import tool, BaseTool
from .base import Skill

class TimeSkill(Skill):
    @property
    def name(self) -> str:
        return "Time Teller"

    @property
    def description(self) -> str:
        return "Tells the current time."

    def get_tools(self) -> List[BaseTool]:
        @tool
        def get_current_time() -> str:
            """Returns the current local time."""
            return datetime.now().strftime("%H:%M")
        
        return [get_current_time]

class BrowserSkill(Skill):
    @property
    def name(self) -> str:
        return "Browser Opener"

    @property
    def description(self) -> str:
        return "Opens the web browser."

    def get_tools(self) -> List[BaseTool]:
        @tool
        def open_browser(url: str = "http://google.com") -> str:
            """Opens the default web browser to the specified URL."""
            import webbrowser
            try:
                webbrowser.open(url)
                return f"Browser opened to {url}"
            except Exception as e:
                return f"Failed to open browser: {e}"
                
        return [open_browser]
