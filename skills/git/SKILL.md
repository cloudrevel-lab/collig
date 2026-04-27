---
name: Git Version Control
description: Provides tools to manage git repositories (status, add, commit, push, diff, log)
version: 1.0.0
author: Collig Team
license: MIT

tools:
  - name: git_status
    description: Get the git status of the repository
  - name: git_add
    description: Stage files for commit
  - name: git_commit
    description: Commit staged changes with a message
  - name: git_push
    description: Push commits to a remote repository
  - name: git_diff
    description: Show changes between commits or working tree
  - name: git_log
    description: Show commit logs

config:
  required: []
  optional: []

triggers:
  - git
  - commit
  - push
  - repository
  - version control
---

# Git Version Control Skill

Provides comprehensive git repository management capabilities for version control operations.

## Usage

Use this skill when the user wants to:
- Check the status of a git repository
- Stage, commit, or push changes
- View commit history or diffs
- Manage git repositories

## Examples

- "What's the git status?"
- "Add all files and commit with message 'Update docs'"
- "Push my changes to origin"
- "Show me the recent commit history"
- "What changes have I made?"

## Tools

### git_status(repo_path: str = ".") -> str

Get the current status of a git repository.

**Parameters:**
- `repo_path`: Path to the repository (default: current directory)

**Returns:** Current git status including staged/unstaged changes and branch info.

### git_add(repo_path: str = ".", files: List[str] = None) -> str

Stage files for commit.

**Parameters:**
- `repo_path`: Path to the repository (default: current directory)
- `files`: List of files to add. If None or empty, adds all changes.

**Returns:** Confirmation of staged files or error message.

### git_commit(repo_path: str = ".", message: str = "Update") -> str

Commit staged changes with a message.

**Parameters:**
- `repo_path`: Path to the repository (default: current directory)
- `message`: Commit message

**Returns:** Commit confirmation or error message.

### git_push(repo_path: str = ".", remote: str = "origin", branch: str = None) -> str

Push commits to a remote repository.

**Parameters:**
- `repo_path`: Path to the repository (default: current directory)
- `remote`: Remote name (default: origin)
- `branch`: Branch name (optional). If not provided, pushes current branch.

**Returns:** Push confirmation or error message.

### git_diff(repo_path: str = ".") -> str

Show changes between commits, commit and working tree.

**Parameters:**
- `repo_path`: Path to the repository (default: current directory)

**Returns:** Diff output showing changes.

### git_log(repo_path: str = ".", max_count: int = 5) -> str

Show commit logs.

**Parameters:**
- `repo_path`: Path to the repository (default: current directory)
- `max_count`: Number of commits to show (default: 5)

**Returns:** Formatted commit log.

## Notes

- Requires git to be installed on the system
- Works with any valid git repository path
- Supports both relative and absolute paths
