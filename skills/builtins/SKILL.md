---
name: Built-in Skills
description: Core skills required by the agent (Time, Browser, Thinking Toggle)
version: 1.0.0
author: Collig Team
license: MIT

tools:
  - name: get_current_time
    description: Returns the current time and date
  - name: open_url
    description: Opens a URL in the system web browser
  - name: toggle_thinking
    description: Toggle thinking/verbose mode for agent responses

triggers:
  - time
  - date
  - open url
  - toggle thinking
  - verbose mode
---

# Built-in Skills

These are core skills required by the agent for basic functionality.

## Time Skill
Provides current time and date information.

## Browser Skill
Opens URLs in the system web browser.

## Thinking Toggle Skill
Allows toggling the agent's thinking/verbose mode on and off.
