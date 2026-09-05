"""
Specialist sub-agents for the heavy, self-contained tool clusters.

These four clusters carry the largest schemas and are the ones least likely to
be needed on any given turn, so they sit behind ``sub_agents``: their tool
declarations stay out of the root request until ADK's generated
``transfer_to_agent`` routes a turn to them.

Each ``description`` is load-bearing -- it is the only thing the root model
sees about a sub-agent, and the only basis on which it decides to transfer.

None of them set ``model``. An ``LlmAgent`` with no model walks up to its
parent, so switching provider on ``root_agent`` switches all of these too.
"""
from typing import List

from google.adk.agents import LlmAgent

from .toolsets import skill_tools

# Skills owned by a sub-agent. The root toolset excludes these so the two
# selection mechanisms never both offer the same tool.
SUBAGENT_SKILLS = ["jira", "Email Manager", "File System Manager",
                   "Git Version Control", "Survey Automator"]


def build_subagents() -> List[LlmAgent]:
    """
    Build the specialists, skipping any whose skills are all disabled.

    An agent with no tools would still be advertised to the root model as a
    transfer target and then have nothing to do, so it is left out entirely.
    """
    specs = [
        (
            "jira_agent",
            ["jira"],
            "Handles Jira: sprint boards, backlogs, and issues. Use for anything "
            "about tickets, issues, stories, tasks assigned to the user, what is "
            "on their plate, the current sprint, or a specific issue key.",
            "You are Collig's Jira specialist. Answer the user's Jira question "
            "using the Jira tools, then summarise the result plainly -- issue "
            "key, summary, status and assignee. Do not invent issue keys; if a "
            "lookup returns nothing, say so.",
        ),
        (
            "email_agent",
            ["Email Manager"],
            "Handles email: reading the inbox, searching, downloading and sending "
            "mail, and configuring the mail account.",
            "You are Collig's email specialist. Use the email tools to answer. "
            "Before sending anything, echo the recipient, subject and body back "
            "to the user and wait for confirmation.",
        ),
        (
            "devtools_agent",
            ["File System Manager", "Git Version Control"],
            "Handles the local filesystem and git: reading, writing, listing and "
            "deleting files and directories, and git status, diff, log, add, "
            "commit and push.",
            "You are Collig's developer-tools specialist. Use the filesystem and "
            "git tools to answer. Read before you write, and state the full path "
            "of anything you create, modify or delete.",
        ),
        (
            "survey_agent",
            ["Survey Automator"],
            "Fills in web surveys and questionnaires by driving a browser.",
            "You are Collig's survey specialist. Load the survey, then work "
            "through it one question at a time, reporting progress as you go.",
        ),
    ]

    agents = []
    for name, skills, description, instruction in specs:
        tools = skill_tools(skills)
        if not tools:
            continue
        agents.append(
            LlmAgent(
                name=name,
                description=description,
                instruction=instruction,
                tools=tools,
            )
        )
    return agents
