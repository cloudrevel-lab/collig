# Portable Skills Structure

This directory contains skills implemented following the **agentskills.io** specification for portable, reusable agent capabilities.

## Structure

Each skill is contained in its own directory with the following structure:

```
skills/
├── {skill_name}/
│   ├── SKILL.md          # Metadata and documentation (required)
│   └── __init__.py       # Skill implementation (required)
├── base.py               # Base Skill class
└── manager.py            # Skill discovery and management
```

## SKILL.md Format

Each skill includes a `SKILL.md` file with YAML frontmatter:

```yaml
---
name: Skill Name
description: Brief description of what the skill does
version: 1.0.0
author: Author Name
license: MIT

tools:
  - name: tool_name
    description: What the tool does

config:
  required:
    - REQUIRED_CONFIG_KEY
  optional:
    - OPTIONAL_CONFIG_KEY

triggers:
  - trigger phrase 1
  - trigger phrase 2
---

# Detailed Documentation

Usage instructions, examples, and notes.
```

## Available Skills

| Skill | Description |
|-------|-------------|
| **Weather Reporter** | Current weather and forecasts using Open-Meteo API |
| **Git Version Control** | Git repository management (status, add, commit, push, diff, log) |
| **File System Manager** | File and directory operations (create, list, delete, read, write) |
| **Email Manager** | Email management via IMAP/SMTP with semantic search |
| **News Search** | News search with DuckDuckGo and caching |
| **Survey Automator** | Automated survey completion using browser automation |
| **Personal Profile** | Store and retrieve user information with vector embeddings |
| **System Info** | System status, uptime, and package management |
| **General Assistant** | General conversation and Q&A using LLM |
| **Python Programmer** | Generate and save Python scripts |
| **Date Calculator** | Calculate dates from natural language queries |
| **Chinese Lunar Calendar** | Convert dates to Chinese lunar calendar and zodiac |

## Usage

### Loading Skills

```python
from skills.manager import SkillManager

manager = SkillManager()
manager.discover_and_load_skills()  # Auto-discovers skills with SKILL.md
manager.configure({"OPENAI_API_KEY": "sk-..."})
```

### Getting Tools

```python
# Get all tools from all skills
tools = manager.get_tools()

# Find a skill by intent
skill = manager.find_skill("What's the weather in Sydney?")

# List all skills
skills_list = manager.list_skills()
```

### Exporting Skills Manifest

```python
# Export in agentskills.io compatible format
manifest = manager.export_skills_manifest()
```

## Creating New Skills

1. Create a new directory under `skills/`
2. Add `SKILL.md` with metadata
3. Implement skill class extending `Skill` base class
4. Implement `get_tools()` method returning list of tools

Example:

```python
from langchain_core.tools import tool
from ..base import Skill

class MySkill(Skill):
    @property
    def name(self) -> str:
        return "My Skill"
    
    @property
    def description(self) -> str:
        return "Does something useful"
    
    def get_tools(self):
        @tool
        def my_tool(param: str) -> str:
            """Tool description."""
            return f"Result: {param}"
        
        return [my_tool]
```

## Portability

Skills are designed to be:
- **Portable**: Copy skill directories between projects
- **Self-contained**: Each skill includes its documentation
- **Discoverable**: Auto-discovered via SKILL.md presence
- **Configurable**: Support required and optional configuration
- **Composable**: Multiple skills can be loaded together

## Configuration

Skills can require or optionally use configuration keys:

```python
# In skill implementation
@property
def required_config(self) -> List[str]:
    return ["API_KEY"]

# Access config in tools
def my_tool(self):
    api_key = self.config.get("API_KEY")
```

## License

All skills are released under the MIT License unless otherwise specified in their SKILL.md.
