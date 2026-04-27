"""
Python Programmer Skill - Portable implementation following agentskills.io spec.

Generates and saves Python scripts based on user requirements.
"""
import os
import re
from typing import Dict, Any, List
from langchain_core.tools import tool, BaseTool
from skills.base import Skill


class ProgrammingSkill(Skill):
    """Generates and saves Python scripts."""

    @property
    def name(self) -> str:
        return "Python Programmer"

    @property
    def description(self) -> str:
        return "Generates and saves Python scripts based on user requirements"

    @property
    def triggers(self) -> List[str]:
        return [
            "create a python script", "create python script",
            "write a python script", "generate python script",
            "make a python file"
        ]

    def _generate_script_content(self, requirements: str) -> tuple[str, str]:
        """Generate script content based on requirements."""
        requirements_lower = requirements.lower()

        if "weather" in requirements_lower:
            filename = "weather_check.py"
            content = """import requests

def get_weather(city):
    \"\"\"Get weather information for a city using Open-Meteo API.\"\"\"
    # Geocoding
    geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1&language=en&format=json"
    geo_resp = requests.get(geo_url)
    geo_data = geo_resp.json()
    
    if not geo_data.get("results"):
        print(f"Could not find city: {city}")
        return
    
    location = geo_data["results"][0]
    lat = location["latitude"]
    lon = location["longitude"]
    
    # Weather data
    weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,weather_code"
    weather_resp = requests.get(weather_url)
    weather_data = weather_resp.json()
    
    current = weather_data.get("current", {})
    temp = current.get("temperature_2m")
    print(f"Weather in {city}: {temp}°C")

if __name__ == "__main__":
    city = input("Enter city name: ")
    get_weather(city)
"""
        elif "fibonacci" in requirements_lower or "fib" in requirements_lower:
            filename = "fibonacci.py"
            content = """def fibonacci(n):
    \"\"\"Generate fibonacci sequence up to n terms.\"\"\"
    if n <= 0:
        return []
    elif n == 1:
        return [0]
    
    sequence = [0, 1]
    while len(sequence) < n:
        sequence.append(sequence[-1] + sequence[-2])
    
    return sequence

if __name__ == "__main__":
    n = int(input("Enter number of terms: "))
    result = fibonacci(n)
    print(f"Fibonacci sequence ({n} terms): {result}")
"""
        elif "csv" in requirements_lower:
            filename = "csv_processor.py"
            content = """import csv

def process_csv(filepath):
    \"\"\"Read and process a CSV file.\"\"\"
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            print(row)

if __name__ == "__main__":
    filepath = input("Enter CSV file path: ")
    process_csv(filepath)
"""
        else:
            filename = "script.py"
            content = """print("Hello from Collig generated script!")

# Add your code here
"""

        return filename, content

    def get_tools(self) -> List[BaseTool]:

        @tool
        def create_python_script(requirements: str, output_path: str = None) -> str:
            """
            Create a Python script based on requirements.
            
            Args:
                requirements: Description of what the script should do
                output_path: Optional path to save the script (default: current directory)
            """
            # Determine output directory and filename
            target_dir = os.getcwd()
            filename = "script.py"

            # Check for explicit path in requirements
            path_match = re.search(r"(?:save|create|put|write)\s+(?:to|in|into|at)\s+([^\s]+)", requirements)

            if output_path:
                expanded_path = os.path.expanduser(output_path)
                absolute_path = os.path.abspath(expanded_path)

                if os.path.splitext(absolute_path)[1]:
                    target_dir = os.path.dirname(absolute_path)
                    filename = os.path.basename(absolute_path)
                else:
                    target_dir = absolute_path

            elif path_match:
                raw_path = path_match.group(1).rstrip(".,;:!?")
                expanded_path = os.path.expanduser(raw_path)
                absolute_path = os.path.abspath(expanded_path)

                if os.path.splitext(absolute_path)[1]:
                    target_dir = os.path.dirname(absolute_path)
                    filename = os.path.basename(absolute_path)
                else:
                    target_dir = absolute_path

            # Check if user refers to "just created dir"
            elif "just created" in requirements_lower or "last created" in requirements:
                last_dir = None  # Would come from context in full implementation
                if last_dir:
                    target_dir = last_dir
                else:
                    return "You asked to put the file in the 'just created' directory, but I don't remember creating one recently."

            # Create directory if it doesn't exist
            if not os.path.exists(target_dir):
                try:
                    os.makedirs(target_dir)
                except OSError as e:
                    return f"Could not create directory '{target_dir}': {e}"

            # Generate content
            gen_filename, content = self._generate_script_content(requirements)
            if filename == "script.py" and gen_filename != "script.py":
                filename = gen_filename

            # Write file
            file_path = os.path.join(target_dir, filename)

            try:
                with open(file_path, "w") as f:
                    f.write(content)

                return f"I've created the Python script '{filename}' in {target_dir}."
            except Exception as e:
                return f"Failed to create file: {str(e)}"

        return [create_python_script]
