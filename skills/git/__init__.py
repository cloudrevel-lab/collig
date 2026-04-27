"""
Git Version Control Skill - Portable implementation following agentskills.io spec.

Provides tools to manage git repositories (status, add, commit, push, diff, log).
"""
from typing import List, Optional
import subprocess
import os
from langchain_core.tools import tool, BaseTool
from ..base import Skill


class GitSkill(Skill):
    """Provides tools to manage git repositories."""

    @property
    def name(self) -> str:
        return "Git Version Control"

    @property
    def description(self) -> str:
        return "Provides tools to manage git repositories (status, add, commit, push, diff, log)"

    @property
    def triggers(self) -> List[str]:
        return ["git", "commit", "push", "repository", "version control"]

    def get_tools(self) -> List[BaseTool]:

        def run_git(args: List[str], cwd: str) -> str:
            """Execute a git command and return the output."""
            try:
                if not os.path.exists(cwd):
                    return f"Error: Directory '{cwd}' does not exist."

                result = subprocess.run(
                    ["git"] + args,
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    check=False
                )

                if result.returncode == 0:
                    return result.stdout.strip() or "Success (no output)"
                else:
                    return f"Error: {result.stderr.strip()}"
            except Exception as e:
                return f"Execution failed: {e}"

        @tool
        def git_status(repo_path: str = ".") -> str:
            """
            Get the git status of the repository.
            
            Args:
                repo_path: Path to the repository (default: current directory)
            """
            return run_git(["status"], os.path.abspath(os.path.expanduser(repo_path)))

        @tool
        def git_add(repo_path: str = ".", files: List[str] = None) -> str:
            """
            Stage files for commit.
            
            Args:
                repo_path: Path to the repository (default: current directory)
                files: List of files to add. If None or empty, adds all changes (git add .).
            """
            path = os.path.abspath(os.path.expanduser(repo_path))
            if not files:
                return run_git(["add", "."], path)
            else:
                return run_git(["add"] + files, path)

        @tool
        def git_commit(repo_path: str = ".", message: str = "Update") -> str:
            """
            Commit staged changes with a message.
            
            Args:
                repo_path: Path to the repository (default: current directory)
                message: Commit message
            """
            return run_git(["commit", "-m", message], os.path.abspath(os.path.expanduser(repo_path)))

        @tool
        def git_push(repo_path: str = ".", remote: str = "origin", branch: str = None) -> str:
            """
            Push commits to a remote repository.
            
            Args:
                repo_path: Path to the repository (default: current directory)
                remote: Remote name (default: origin)
                branch: Branch name (optional). If not provided, pushes current branch.
            """
            args = ["push", remote]
            if branch:
                args.append(branch)
            return run_git(args, os.path.abspath(os.path.expanduser(repo_path)))

        @tool
        def git_diff(repo_path: str = ".") -> str:
            """
            Show changes between commits, commit and working tree, etc.
            Useful for generating commit messages.
            
            Args:
                repo_path: Path to the repository (default: current directory)
            """
            return run_git(["diff"], os.path.abspath(os.path.expanduser(repo_path)))

        @tool
        def git_log(repo_path: str = ".", max_count: int = 5) -> str:
            """
            Show commit logs.
            
            Args:
                repo_path: Path to the repository (default: current directory)
                max_count: Number of commits to show (default: 5)
            """
            return run_git(["log", f"-n {max_count}", "--oneline"], os.path.abspath(os.path.expanduser(repo_path)))

        return [git_status, git_add, git_commit, git_push, git_diff, git_log]
