"""
Setup Wizard Skill - Provides setup and configuration wizard.
"""
from typing import List
from langchain_core.tools import tool, BaseTool
from skills.base import Skill


class SetupWizardSkill(Skill):
    """Provides setup wizard for initial configuration."""

    def __init__(self, skill_root=None):
        super().__init__(skill_root)

    @property
    def name(self) -> str:
        return "Setup Wizard"

    @property
    def description(self) -> str:
        return "Guides users through initial setup and configuration"

    @property
    def triggers(self) -> List[str]:
        return ["setup", "configure", "wizard", "initial setup"]

    def get_tools(self) -> List[BaseTool]:

        @tool
        def run_setup_wizard() -> str:
            """
            Run the interactive setup wizard to configure the agent.
            """
            # TODO: Implement actual setup wizard
            return "Setup wizard started. Please configure your API keys and preferences."

        return [run_setup_wizard]
