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

        @tool
        def clear_conversation(session_id: str = None) -> str:
            """
            Clears the current conversation history/memory.
            Use this when the user asks to "delete conversation", "clean history", or "start over".
            The session_id should be retrieved from the context if possible, otherwise it will try to find it.
            """
            # Accessing session_manager is tricky here because Skill is isolated.
            # However, we can use the 'runtime_context' passed during execution if we architect it that way.
            # OR, we can instantiate a SessionManager here (since it works on file system).
            from session import SessionManager
            
            # How do we get the session_id? 
            # The agent injects it into the system prompt, but tools don't automatically get it unless passed as arg.
            # We can ask the LLM to extract it from context?
            # Or better, we can assume the agent passes it?
            # Actually, the most robust way is to require session_id as an argument, 
            # and the LLM will extract it from the "Current Session ID: ..." system message we injected!
            
            if not session_id:
                return "Error: Session ID is required to clear conversation."
                
            try:
                manager = SessionManager()
                manager.clear_history(session_id)
                return "Conversation history has been cleared."
            except Exception as e:
                return f"Failed to clear conversation: {e}"

        @tool
        def install_package(package_name: str) -> str:
            """
            Installs a system package using apt-get (requires sudo/root).
            Use this to install missing software or dependencies.
            Example: install_package("w3m") or install_package("chromium-browser")
            """
            import subprocess
            import sys
            
            if not sys.platform.startswith("linux"):
                 return "Error: Package installation is only supported on Linux."

            try:
                # Update apt-get first? Maybe too slow.
                # Just try install.
                # -y to answer yes automatically
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

        return [get_system_status, install_package]
