---
name: General Assistant
description: Handles general conversation, questions, math problems, and small talk
version: 1.0.0
author: Collig Team
license: MIT

tools:
  - name: chat
    description: Engage in general conversation and answer questions

config:
  required:
    - OPENAI_API_KEY
  optional:
    - LLM_PROVIDER: Provider for chat (openai or dashscope)
    - DASHSCOPE_API_KEY: API key for DashScope

triggers:
  - chat
  - say
  - speak
  - calculate
  - what is
  - who is
  - tell me
  - explain
---

# General Assistant Skill

Handles general conversation, questions, math problems, and small talk when no other specific skill matches.

## Usage

Use this skill when the user wants to:
- Have a general conversation
- Ask questions about various topics
- Get help with math problems
- Engage in small talk

## Examples

- "What is the capital of France?"
- "Can you help me calculate 15% of 200?"
- "Tell me about quantum physics"
- "Who invented the telephone?"

## Tools

### chat(message: str) -> str

Engage in general conversation and get answers to questions.

**Parameters:**
- `message`: The user's message or question

**Returns:** AI-generated response.

## Notes

- Requires OpenAI API key or DashScope API key
- Uses GPT-4o by default for responses
- Acts as a fallback when no other skill matches the user's intent
