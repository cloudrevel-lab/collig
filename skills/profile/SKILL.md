---
name: Personal Profile
description: Stores and retrieves personal information about the user using vector embeddings
version: 1.0.0
author: Collig Team
license: MIT

tools:
  - name: set_personal_info
    description: Save personal information about the user
  - name: get_personal_info
    description: Retrieve personal information based on a query

config:
  required: []
  optional:
    - LLM_PROVIDER: Provider for embeddings (openai or dashscope)
    - OPENAI_API_KEY: API key for OpenAI embeddings
    - DASHSCOPE_API_KEY: API key for DashScope embeddings

triggers:
  - remember this
  - save this about me
  - my preference
  - personal info
  - about me
---

# Personal Profile Skill

Stores and retrieves personal information about the user using vector embeddings for semantic search.

## Usage

Use this skill when the user wants to:
- Save personal preferences, facts, or information
- Retrieve previously stored information about themselves
- Build a persistent user profile

## Examples

- "Remember that I live in Sydney"
- "Set my favorite color to blue"
- "What do you know about my location?"
- "Do you know my name?"

## Tools

### set_personal_info(key: str, value: str, category: str = "general") -> str

Save personal information about the user.

**Parameters:**
- `key`: The attribute name (e.g., "location", "name", "favorite_color")
- `value`: The value of the attribute
- `category`: Optional category (e.g., "location", "identity", "preference")

**Returns:** Confirmation message.

### get_personal_info(query: str) -> str

Retrieve personal information based on a query.

**Parameters:**
- `query`: The question or keyword to search for

**Returns:** Matching information from the user's profile.

## Notes

- Uses vector embeddings for semantic search
- Requires API key for embeddings (OpenAI or DashScope)
- Information persists across sessions via ChromaDB
- Automatically updates existing entries with same key
