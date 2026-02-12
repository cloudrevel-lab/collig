import os
from typing import Dict, Any, List
from .base import Skill

class ProgrammingSkill(Skill):
    @property
    def name(self) -> str:
        return "Python Programmer"

    @property
    def description(self) -> str:
        return "Generates and saves Python scripts."

    @property
    def triggers(self) -> List[str]:
        return ["create a python script", "create python script", "write a python script", "generate python script"]

    def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        message = context.get("message", "").lower()

        # 1. Determine Output Directory and Filename
        target_dir = os.getcwd() # Default
        filename = "script.py"

        # Check for explicit path in message
        import re
        # Look for "save to/in X" or "create in X"
        path_match = re.search(r"(?:save|create|put|write)\s+(?:to|in|into|at)\s+([^\s]+)", message)

        if path_match:
            raw_path = path_match.group(1).rstrip(".,;:!?")
            expanded_path = os.path.expanduser(raw_path)
            absolute_path = os.path.abspath(expanded_path)

            # Check if it looks like a file (has extension)
            if os.path.splitext(absolute_path)[1]:
                target_dir = os.path.dirname(absolute_path)
                filename = os.path.basename(absolute_path)
            else:
                target_dir = absolute_path

            # Create directory if it doesn't exist
            if not os.path.exists(target_dir):
                try:
                    os.makedirs(target_dir)
                except OSError as e:
                    return {
                        "response": f"Could not create directory '{target_dir}': {e}",
                        "action": "error"
                    }

        # Check if user refers to "just created dir" (overrides explicit path if ambiguous, but usually mutually exclusive)
        elif "just created" in message or "last created" in message:
            last_dir = context.get("last_created_dir")
            if last_dir:
                target_dir = last_dir
            else:
                 return {
                    "response": "You asked to put the file in the 'just created' directory, but I don't remember creating one recently. Please specify the path.",
                    "action": "error"
                }

        # 2. Generate Content (Mocking LLM for now)
        content = ""

        if "weather" in message:
            filename = "weather_check.py"
            content = """import requests

def get_weather(city):
    # This is a placeholder. You would need a real API key.
    print(f"Getting weather for {city}...")
    print("It's sunny and 25°C! (Simulated)")

if __name__ == "__main__":
    city = input("Enter city name: ")
    get_weather(city)
"""
        else:
             content = """print("Hello from Collig generated script!")"""

        # 3. Write File
        file_path = os.path.join(target_dir, filename)

        try:
            with open(file_path, "w") as f:
                f.write(content)

            return {
                "response": f"I've created the Python script '{filename}' in {target_dir}.",
                "action": "create_file",
                "data": {"path": file_path}
            }
        except Exception as e:
            return {
                "response": f"Failed to create file: {str(e)}",
                "action": "error"
            }
