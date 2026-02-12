import os
import shutil
from typing import Dict, Any, List, Optional
from langchain_core.tools import tool, BaseTool
from .base import Skill

class FileSystemSkill(Skill):
    @property
    def name(self) -> str:
        return "File System Manager"

    @property
    def description(self) -> str:
        return "Manages files and directories (create, list, delete)."

    def get_tools(self) -> List[BaseTool]:

        def _resolve_path(path: str) -> str:
            """Resolves a path to its absolute form, expanding user home directory."""
            if not path:
                return os.getcwd()
            return os.path.abspath(os.path.expanduser(path))

        @tool
        def create_directory(path: str) -> str:
            """
            Creates a new directory at the specified path.
            Args:
                path: The path of the directory to create (e.g., "new_folder", "/tmp/test").
            """
            try:
                resolved_path = _resolve_path(path)
                os.makedirs(resolved_path, exist_ok=True)
                return f"Directory created successfully at: {resolved_path}"
            except Exception as e:
                return f"Error creating directory: {e}"

        @tool
        def list_directory(path: Optional[str] = None) -> str:
            """
            Lists the contents of a directory.
            Args:
                path: The directory path to list. Defaults to the current working directory.
            """
            try:
                resolved_path = _resolve_path(path or ".")
                if not os.path.exists(resolved_path):
                    return f"Path does not exist: {resolved_path}"

                items = os.listdir(resolved_path)
                if not items:
                    return f"Directory is empty: {resolved_path}"

                # Add file type indicators
                result = []
                for item in items:
                    full_path = os.path.join(resolved_path, item)
                    if os.path.isdir(full_path):
                        result.append(f"{item}/")
                    else:
                        result.append(item)

                return f"Contents of {resolved_path}:\n" + "\n".join(sorted(result))
            except Exception as e:
                return f"Error listing directory: {e}"

        @tool
        def delete_item(path: str) -> str:
            """
            Deletes a file or directory.
            Args:
                path: The path of the file or directory to delete.
            """
            try:
                resolved_path = _resolve_path(path)
                if not os.path.exists(resolved_path):
                    return f"Path does not exist: {resolved_path}"

                if os.path.isdir(resolved_path):
                    shutil.rmtree(resolved_path)
                    return f"Directory deleted: {resolved_path}"
                else:
                    os.remove(resolved_path)
                    return f"File deleted: {resolved_path}"
            except Exception as e:
                return f"Error deleting item: {e}"

        @tool
        def write_file(path: str, content: str) -> str:
            """
            Writes content to a file. Overwrites if exists.
            Args:
                path: The path of the file to write.
                content: The text content to write.
            """
            try:
                resolved_path = _resolve_path(path)
                parent_dir = os.path.dirname(resolved_path)
                if not os.path.exists(parent_dir):
                    os.makedirs(parent_dir, exist_ok=True)

                with open(resolved_path, "w", encoding="utf-8") as f:
                    f.write(content)
                return f"Successfully wrote to file: {resolved_path}"
            except Exception as e:
                return f"Error writing file: {e}"

        @tool
        def read_file(path: str) -> str:
            """
            Reads content from a file.
            Args:
                path: The path of the file to read.
            """
            try:
                resolved_path = _resolve_path(path)
                if not os.path.exists(resolved_path):
                    return f"File does not exist: {resolved_path}"

                with open(resolved_path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception as e:
                return f"Error reading file: {e}"

        return [create_directory, list_directory, delete_item, write_file, read_file]
