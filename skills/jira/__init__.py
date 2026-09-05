"""
Jira Skill - Integration with Atlassian Jira for task management.

This skill provides tools to query and manage Jira issues.
"""

import os
import base64
import urllib.parse
import urllib.request
import json
from typing import List, Dict, Any, Optional
from langchain_core.tools import BaseTool, tool
from skills.base import Skill


class JiraSkill(Skill):
    """Skill for interacting with Jira API."""

    @property
    def name(self) -> str:
        return "jira"

    @property
    def description(self) -> str:
        return "Interact with Jira API to query tasks, sprints, and issues"

    @property
    def triggers(self) -> List[str]:
        return [
            "jira", "sprint", "my plate", "on my plate", "ticket", "tickets",
            "issue", "issues", "task", "tasks", "story", "stories", "backlog",
            "scrum", "agile", "board", "AIE-"
        ]

    @property
    def instructions(self) -> str:
        return """Use this skill to:
- List issues assigned to you on your sprint board
- List all your open issues across projects
- Get details for a specific Jira issue

Required configuration:
- JIRA_EMAIL: Your NSW Education email
- JIRA_API_TOKEN: Your Atlassian API token
- JIRA_DOMAIN: Jira domain (default: nsw-education.atlassian.net)

The skill is pre-configured for:
- Board ID: 1726 (AIE project)
- Your assignee ID from the board URL
"""

    def __init__(self, skill_root: str = None):
        super().__init__()
        self.jira_domain = "nsw-education.atlassian.net"
        self.board_id = "1726"
        self.project_key = "AIE"  # Primary project from board
        self.assignee_id = "712020:c6ef9d14-053a-42a4-8cb2-10213fc673c7"
        self.base_url = f"https://{self.jira_domain}/rest/api/3"

    def _get_auth_header(self) -> Optional[str]:
        """Create Basic Auth header with email and API token."""
        email = self.config.get("JIRA_EMAIL") or os.getenv("JIRA_EMAIL")
        api_token = self.config.get("JIRA_API_TOKEN") or os.getenv("JIRA_API_TOKEN")

        if not email or not api_token:
            return None

        credentials = f"{email}:{api_token}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return f"Basic {encoded}"

    def _jira_request(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        """Make a request to the Jira API."""
        auth_header = self._get_auth_header()
        if not auth_header:
            return None

        url = f"{self.base_url}/{endpoint}"
        
        # For search endpoint, use POST with JQL in body (new API requirement)
        method = "GET"
        data = None
        if endpoint == "search" and params and "jql" in params:
            # Use new /search/jql endpoint with POST
            url = f"{self.base_url}/search/jql"
            method = "POST"
            data = json.dumps({
                "jqlQuery": params["jql"],
                "fields": params.get("fields", "*all").split(",") if params.get("fields") else ["*all"]
            }).encode("utf-8")
            headers = {
                "Authorization": auth_header,
                "Accept": "application/json",
                "Content-Type": "application/json"
            }
        else:
            if params:
                url += "?" + urllib.parse.urlencode(params)
            headers = {
                "Authorization": auth_header,
                "Accept": "application/json"
            }

        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req) as response:
                return json.loads(response.read().decode())
        except Exception as e:
            print(f"Jira API error: {e}")
            return None

    def _agile_request(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        """Make a GET request to the Jira Agile (Software) API (rest/agile/1.0)."""
        auth_header = self._get_auth_header()
        if not auth_header:
            return None

        url = f"https://{self.jira_domain}/rest/agile/1.0/{endpoint}"
        if params:
            url += "?" + urllib.parse.urlencode(params)

        headers = {
            "Authorization": auth_header,
            "Accept": "application/json",
        }

        try:
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req) as response:
                return json.loads(response.read().decode())
        except Exception as e:
            print(f"Jira Agile API error: {e}")
            return None

    def get_board_name(self, board_id) -> Optional[str]:
        """Fetch the display name of a board by id (None if unavailable)."""
        data = self._agile_request(f"board/{board_id}")
        if data:
            return data.get("name")
        return None

    def get_board_issues(self, board_id, max_results: int = 100) -> Optional[List[Dict]]:
        """
        Fetch issues for a board via the Agile API.

        Returns a list of issue dicts, or None on request failure.
        """
        all_issues: List[Dict] = []
        start_at = 0
        fields = "key,summary,status,priority,assignee,updated"
        while True:
            data = self._agile_request(
                f"board/{board_id}/issue",
                {
                    "startAt": start_at,
                    "maxResults": max_results,
                    "fields": fields,
                },
            )
            if data is None:
                return None
            issues = data.get("issues", [])
            all_issues.extend(issues)
            total = data.get("total", len(all_issues))
            start_at += len(issues)
            if not issues or start_at >= total:
                break
        return all_issues

    @staticmethod
    def _status_sort_key(status_name: str, status_category: str):
        """
        Sort key placing done/completed statuses last.

        Uses Jira's statusCategory ("new", "indeterminate", "done") first,
        then falls back to a name heuristic, then the name for stability.
        """
        category = (status_category or "").lower()
        name = (status_name or "").lower()

        done_names = {"done", "closed", "resolved", "complete", "completed", "cancelled", "canceled"}
        in_progress_names = {"in progress", "in review", "peer review", "review", "testing"}

        if category == "done" or name in done_names:
            bucket = 2
        elif category == "indeterminate" or name in in_progress_names:
            bucket = 1
        else:
            bucket = 0
        return (bucket, name)

    @property
    def required_config(self) -> List[str]:
        return ["JIRA_EMAIL", "JIRA_API_TOKEN"]

    def get_tools(self) -> List[BaseTool]:
        """Return list of tools provided by this skill."""

        @tool
        def list_sprint_tasks() -> str:
            """
            List all issues assigned to you on your current sprint board.
            Use this when asked about "what's on my plate", "my sprint tasks", "current sprint", "sprint board", or "my tickets this sprint".
            Shows issues from the AIE project (board 1726) filtered by your assignee ID.

            Returns:
                Formatted list of issues with key, summary, status, and priority
            """
            auth_header = self._get_auth_header()
            if not auth_header:
                return "Jira not configured. Please set JIRA_EMAIL and JIRA_API_TOKEN via /config"

            # Use project filter since board filter doesn't work in JQL directly
            jql = f"assignee = '{self.assignee_id}' AND project = {self.project_key} AND status != Done ORDER BY status, priority DESC"
            
            url = f"{self.base_url}/search/jql"
            data = json.dumps({
                "jql": jql,
                "fields": ["key", "summary", "status", "priority", "assignee"]
            }).encode("utf-8")
            
            headers = {
                "Authorization": auth_header,
                "Accept": "application/json",
                "Content-Type": "application/json"
            }
            
            try:
                req = urllib.request.Request(url, data=data, headers=headers, method="POST")
                with urllib.request.urlopen(req) as response:
                    data = json.loads(response.read().decode())
            except Exception as e:
                return f"Failed to fetch issues from Jira: {e}"

            issues = data.get("issues", [])
            if not issues:
                return f"No issues found assigned to you in project {self.project_key}."

            result = [f"📋 Your Sprint Tasks (Project: {self.project_key}, Board: {self.board_id})\n{'='*60}"]
            for issue in issues:
                fields = issue["fields"]
                key = issue["key"]
                summary = fields["summary"]
                status = fields["status"]["name"]
                priority = fields["priority"]["name"] if fields["priority"] else "None"
                issue_url = f"https://{self.jira_domain}/browse/{key}"

                status_icon = {"To Do": "⬜", "In Progress": "🔄", "Done": "✅", 
                              "Backlog": "📦", "Peer Review": "👀"}.get(status, "◻️")
                result.append(f"{status_icon} {key}: {summary}")
                result.append(f"   🔗 {issue_url}")
                result.append(f"   Status: {status} | Priority: {priority}")

            result.append(f"\nTotal: {len(issues)} issue(s)")
            result.append("\n[Note: Please show all ticket URLs to the user - they are clickable links in the terminal]")
            return "\n".join(result)

        @tool
        def list_my_issues() -> str:
            """
            List all open issues assigned to you across ALL projects (not just sprint board).
            Use this when asked about "all my issues", "my open tickets", or "what am I working on".
            Excludes Done status, ordered by most recently updated.

            Returns:
                Formatted list of all open issues with project, key, summary, status, priority
            """
            auth_header = self._get_auth_header()
            if not auth_header:
                return "Jira not configured. Please set JIRA_EMAIL and JIRA_API_TOKEN via /config"

            jql = f"assignee = '{self.assignee_id}' AND status != Done ORDER BY updated DESC"
            
            url = f"{self.base_url}/search/jql"
            data = json.dumps({
                "jql": jql,
                "fields": ["key", "summary", "status", "priority", "project", "updated"]
            }).encode("utf-8")
            
            headers = {
                "Authorization": auth_header,
                "Accept": "application/json",
                "Content-Type": "application/json"
            }
            
            try:
                req = urllib.request.Request(url, data=data, headers=headers, method="POST")
                with urllib.request.urlopen(req) as response:
                    data = json.loads(response.read().decode())
            except Exception as e:
                return f"Failed to fetch issues from Jira: {e}"

            issues = data.get("issues", [])
            if not issues:
                return "No open issues found assigned to you."

            result = [f"📋 All Your Open Issues\n{'='*60}"]
            for issue in issues:
                fields = issue["fields"]
                key = issue["key"]
                summary = fields["summary"]
                status = fields["status"]["name"]
                priority = fields["priority"]["name"] if fields["priority"] else "None"
                project = fields["project"]["name"]
                updated = fields["updated"][:10]
                issue_url = f"https://{self.jira_domain}/browse/{key}"

                result.append(f"{key} ({project}): {summary}")
                result.append(f"   🔗 {issue_url}")
                result.append(f"   Status: {status} | Priority: {priority} | Updated: {updated}")

            result.append(f"\nTotal: {len(issues)} open issue(s)")
            return "\n".join(result)

        @tool
        def get_issue(issue_key: str) -> str:
            """
            Get detailed information about a specific Jira issue by key.
            Use this when asked about a specific ticket like "AIE-1234", "tell me about issue XYZ", or "what's the status of ABC-999".
            
            Args:
                issue_key: The Jira issue key (e.g., AIE-1234, ABC-999)
            
            Returns:
                Detailed issue information including status, priority, assignee, reporter, description, dates
            """
            auth_header = self._get_auth_header()
            if not auth_header:
                return "Jira not configured. Please set JIRA_EMAIL and JIRA_API_TOKEN via /config"

            data = self._jira_request(f"issue/{issue_key}", {"fields": "*all"})

            if not data:
                return f"Issue '{issue_key}' not found or failed to fetch."

            fields = data["fields"]
            key = data["key"]
            summary = fields.get("summary", "No summary")
            status = fields.get("status", {}).get("name", "Unknown")
            priority = fields.get("priority", {}).get("name", "None")

            result = [f"📄 {key} - {summary}", f"{'='*60}"]
            result.append(f"URL: https://{self.jira_domain}/browse/{key}")
            result.append(f"Status: {status}")
            result.append(f"Priority: {priority}")

            assignee = fields.get("assignee")
            result.append(f"Assignee: {assignee.get('displayName', 'Unassigned') if assignee else 'Unassigned'}")

            reporter = fields.get("reporter")
            if reporter:
                result.append(f"Reporter: {reporter.get('displayName', 'Unknown')}")

            # Description
            description = fields.get("description")
            if description:
                result.append("\nDescription:")
                if isinstance(description, dict):
                    for content in description.get("content", []):
                        if content.get("type") == "paragraph":
                            for para in content.get("content", []):
                                result.append(f"  {para.get('text', '')}")
                else:
                    result.append(f"  {description}")

            result.append(f"\nCreated: {fields.get('created', '')[:10]}")
            result.append(f"Updated: {fields.get('updated', '')[:10]}")

            return "\n".join(result)

        @tool
        def list_board_issues(board_id: str) -> str:
            """
            List all issues on a specific Jira board, grouped by status.
            Use this when asked to "show issues on board 1726", "list board tickets",
            or "what's on board X". Done/closed/completed issues are shown last.

            Args:
                board_id: The numeric Jira board id (e.g., "1726")

            Returns:
                Formatted list of issues grouped by status with key, summary, status, priority
            """
            auth_header = self._get_auth_header()
            if not auth_header:
                return "Jira not configured. Please set JIRA_EMAIL and JIRA_API_TOKEN via /config"

            board_id = str(board_id).strip()
            board_name = self.get_board_name(board_id)
            issues = self.get_board_issues(board_id)

            if issues is None:
                return f"Failed to fetch issues for board {board_id} (check credentials / board id)."
            if not issues:
                return f"No issues found on board {board_id}."

            def sort_key(issue):
                fields = issue.get("fields", {})
                status = fields.get("status") or {}
                status_name = status.get("name", "")
                category = (status.get("statusCategory") or {}).get("key", "")
                priority = fields.get("priority") or {}
                priority_name = priority.get("name") or "ZZZ"
                return self._status_sort_key(status_name, category) + (priority_name,)

            issues_sorted = sorted(issues, key=sort_key)

            status_icons = {"To Do": "⬜", "In Progress": "🔄", "Done": "✅",
                            "Backlog": "📦", "Peer Review": "👀", "In Review": "👀",
                            "Closed": "✅", "Resolved": "✅"}

            header = f"Board {board_id}" + (f" - {board_name}" if board_name else "")
            result = [f"📋 {header}\n{'='*60}"]

            current_status = None
            open_count = 0
            done_count = 0
            done_names = {"done", "closed", "resolved", "complete", "completed", "cancelled", "canceled"}
            for issue in issues_sorted:
                fields = issue.get("fields", {})
                key = issue.get("key", "?")
                summary = fields.get("summary", "")
                status = fields.get("status") or {}
                status_name = status.get("name", "Unknown")
                category = (status.get("statusCategory") or {}).get("key", "")
                priority = fields.get("priority") or {}
                priority_name = priority.get("name") or "None"
                assignee = fields.get("assignee") or {}
                assignee_name = assignee.get("displayName") if assignee else "Unassigned"
                issue_url = f"https://{self.jira_domain}/browse/{key}"

                if category == "done" or status_name.lower() in done_names:
                    done_count += 1
                else:
                    open_count += 1

                if status_name != current_status:
                    current_status = status_name
                    result.append(f"\n[{status_name}]")

                icon = status_icons.get(status_name, "◻️")
                result.append(f"{icon} {key}: {summary}")
                result.append(f"   🔗 {issue_url}")
                result.append(f"   Status: {status_name} | Priority: {priority_name} | Assignee: {assignee_name or 'Unassigned'}")

            result.append(f"\n{'='*60}")
            result.append(f"Total: {len(issues_sorted)} issue(s) | Open/active: {open_count} | Done/closed: {done_count}")
            result.append("\n[Note: Please show all ticket URLs to the user - they are clickable links in the terminal]")
            return "\n".join(result)

        return [list_sprint_tasks, list_my_issues, get_issue, list_board_issues]
