"""
System Info Skill - Portable implementation following agentskills.io spec.

Provides system status, uptime, and package management capabilities.
"""
from typing import List
import datetime
import subprocess
import sys
from langchain_core.tools import tool, BaseTool
from skills.base import Skill


class SystemSkill(Skill):
    """Provides system information and management capabilities."""

    def __init__(self, skill_root=None):
        super().__init__(skill_root)
        self.start_time = datetime.datetime.now()

    @property
    def name(self) -> str:
        return "System Info"

    @property
    def description(self) -> str:
        return "Provides system status, uptime, and package management"

    @property
    def triggers(self) -> List[str]:
        return ["system status", "uptime", "install package", "clear conversation", "system info"]

    def get_tools(self) -> List[BaseTool]:

        @tool
        def get_system_status() -> str:
            """
            Returns the current system status and uptime.
            """
            uptime = datetime.datetime.now() - self.start_time
            return f"System Status: Online\nUptime: {str(uptime).split('.')[0]}"

        @tool
        def clear_conversation(session_id: str = None) -> str:
            """
            Clears the current conversation history/memory.
            
            Args:
                session_id: Optional session ID (extracted from context if not provided)
            """
            if not session_id:
                return "Error: Session ID is required to clear conversation."

            try:
                from session import SessionManager
                manager = SessionManager()
                manager.clear_history(session_id)
                return "Conversation history has been cleared."
            except Exception as e:
                return f"Failed to clear conversation: {e}"

        @tool
        def install_package(package_name: str) -> str:
            """
            Installs a system package using apt-get.
            
            Args:
                package_name: Name of the package to install
            """
            if not sys.platform.startswith("linux"):
                return "Error: Package installation is only supported on Linux."

            try:
                cmd = ["sudo", "apt-get", "install", "-y", package_name]

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=False
                )

                if result.returncode == 0:
                    return f"Successfully installed {package_name}.\nOutput: {result.stdout}"
                else:
                    return f"Failed to install {package_name}.\nError: {result.stderr}\nOutput: {result.stdout}"
            except Exception as e:
                return f"Error executing installation: {str(e)}"

        return [get_system_status, clear_conversation, install_package]
