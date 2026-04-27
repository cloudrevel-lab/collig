---
name: File System Manager
description: Manages files and directories (create, list, delete, read, write)
version: 1.0.0
author: Collig Team
license: MIT

tools:
  - name: create_directory
    description: Creates a new directory at the specified path
  - name: list_directory
    description: Lists the contents of a directory
  - name: delete_item
    description: Deletes a file or directory
  - name: write_file
    description: Writes content to a file
  - name: read_file
    description: Reads content from a file

config:
  required: []
  optional: []

triggers:
  - file
  - directory
  - folder
  - create file
  - save file
  - read file
---

# File System Manager Skill

Provides comprehensive file and directory management capabilities.

## Usage

Use this skill when the user wants to:
- Create, list, or delete directories
- Read from or write to files
- Navigate and explore the file system
- Manage file content

## Examples

- "Create a directory called 'projects'"
- "List the files in /tmp"
- "Read the contents of config.txt"
- "Write 'Hello World' to hello.txt"
- "Delete the old_backup folder"

## Tools

### create_directory(path: str) -> str

Creates a new directory at the specified path.

**Parameters:**
- `path`: The path of the directory to create (e.g., "new_folder", "/tmp/test")

**Returns:** Confirmation message with the created path or error.

### list_directory(path: Optional[str] = None) -> str

Lists the contents of a directory.

**Parameters:**
- `path`: The directory path to list. Defaults to current working directory.

**Returns:** Formatted list of files and directories, or error message.

### delete_item(path: str) -> str

Deletes a file or directory.

**Parameters:**
- `path`: The path of the file or directory to delete

**Returns:** Confirmation of deletion or error message.

### write_file(path: str, content: str) -> str

Writes content to a file. Overwrites if exists.

**Parameters:**
- `path`: The path of the file to write
- `content`: The text content to write

**Returns:** Confirmation of write operation or error.

### read_file(path: str) -> str

Reads content from a file.

**Parameters:**
- `path`: The path of the file to read

**Returns:** File contents or error message.

## Notes

- Paths are expanded to handle ~ for home directory
- Parent directories are created automatically when writing files
- Directories are marked with a trailing "/" in list output
