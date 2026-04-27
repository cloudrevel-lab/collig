---
name: System Info
description: Provides system status, uptime, and package management capabilities
version: 1.0.0
author: Collig Team
license: MIT

tools:
  - name: get_system_status
    description: Returns the current system status and uptime
  - name: clear_conversation
    description: Clears the current conversation history
  - name: install_package
    description: Installs a system package using apt-get

config:
  required: []
  optional: []

triggers:
  - system status
  - uptime
  - install package
  - clear conversation
  - system info
---

# System Info Skill

Provides system information and management capabilities.

## Usage

Use this skill when the user wants to:
- Check system status and uptime
- Clear conversation history
- Install system packages (Linux only)

## Examples

- "What's the system status?"
- "How long has the system been running?"
- "Clear the conversation history"
- "Install the w3m package"

## Tools

### get_system_status() -> str

Returns the current system status and uptime.

**Returns:** System status and uptime information.

### clear_conversation(session_id: str = None) -> str

Clears the current conversation history/memory.

**Parameters:**
- `session_id`: Optional session ID (extracted from context if not provided)

**Returns:** Confirmation message.

### install_package(package_name: str) -> str

Installs a system package using apt-get.

**Parameters:**
- `package_name`: Name of the package to install

**Returns:** Installation result or error message.

## Notes

- Package installation requires sudo/root privileges
- Only supported on Linux systems
- Session ID is typically extracted from context automatically
