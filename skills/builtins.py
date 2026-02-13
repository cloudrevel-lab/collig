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
        return "Tells the current date and time."

    @property
    def triggers(self) -> List[str]:
        return ["time", "clock", "what time", "date", "day", "what's the date", "what is the date"]

    def load_tools(self) -> List[object]:
        @tool
        def get_current_time() -> str:
            """Returns the current local date and time."""
            return datetime.now().strftime("%A, %B %d, %Y %H:%M:%S")
        
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
            """
            Opens the default web browser to the specified URL.
            On Linux, it uses xdg-open and validates success.
            """
            import webbrowser
            import subprocess
            import sys
            import shutil

            # Try using xdg-open directly on Linux to capture errors
            if sys.platform.startswith("linux"):
                # Check if xdg-open exists
                if not shutil.which("xdg-open"):
                    return "Error: xdg-open not found. Please install xdg-utils."

                try:
                    # Run xdg-open and capture output
                    result = subprocess.run(
                        ["xdg-open", url], 
                        capture_output=True, 
                        text=True, 
                        check=False # Don't raise exception immediately, check return code
                    )
                    
                    if result.returncode != 0:
                        return f"Failed to open browser: {result.stderr.strip()}"
                    
                    # xdg-open might return 0 but print errors to stderr if no browser is found
                    if result.stderr and "no method available" in result.stderr:
                         return f"Failed to open browser: {result.stderr.strip()}"
                         
                    return f"Browser opened to {url}"
                except Exception as e:
                    return f"Failed to open browser (subprocess error): {str(e)}"
            
            # Fallback for other OS or if xdg-open logic is bypassed
            try:
                if webbrowser.open(url):
                    return f"Browser opened to {url}"
                else:
                    return "Failed to open browser (webbrowser returned False)"
            except Exception as e:
                return f"Failed to open browser: {e}"
                
        return [open_browser]
