---
name: Python Programmer
description: Generates and saves Python scripts based on user requirements
version: 1.0.0
author: Collig Team
license: MIT

tools:
  - name: create_python_script
    description: Create a Python script based on user requirements

config:
  required: []
  optional: []

triggers:
  - create a python script
  - create python script
  - write a python script
  - generate python script
  - make a python file
---

# Python Programmer Skill

Generates and saves Python scripts based on user requirements.

## Usage

Use this skill when the user wants to:
- Create a new Python script
- Generate code for a specific task
- Save a Python file to disk

## Examples

- "Create a Python script that checks the weather"
- "Write a script to calculate fibonacci numbers"
- "Generate a Python file to process CSV data"
- "Create a script and save it to /tmp/my_script.py"

## Tools

### create_python_script(requirements: str, output_path: str = None) -> str

Generate and save a Python script based on requirements.

**Parameters:**
- `requirements`: Description of what the script should do
- `output_path`: Optional path to save the script (default: current directory)

**Returns:** Confirmation message with script location.

## Notes

- Scripts are saved with .py extension by default
- If a path is specified, parent directories are created automatically
- Supports relative and absolute paths
- Can reference "just created directory" for output location
