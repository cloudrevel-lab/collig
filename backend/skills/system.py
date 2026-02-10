from typing import Dict, Any, List
import datetime
from langchain_core.tools import tool, BaseTool
from .base import Skill

class SystemSkill(Skill):
    def __init__(self):
        super().__init__()
        self.start_time = datetime.datetime.now()

    @property
    def name(self) -> str:
        return "System Info"

    @property
    def description(self) -> str:
        return "Provides information about the system status and agent configuration."

    def get_tools(self) -> List[BaseTool]:
        
        @tool
        def get_system_status() -> str:
            """
            Returns the current system status and uptime.
            """
            uptime = datetime.datetime.now() - self.start_time
            return f"System Status: Online\nUptime: {str(uptime).split('.')[0]}"

        return [get_system_status]
