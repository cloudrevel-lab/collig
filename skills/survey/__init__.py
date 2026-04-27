"""
Survey Automator Skill - Portable implementation following agentskills.io spec.

Automate online surveys using browser automation with Playwright.
"""
from typing import List, Dict, Any, Optional
from langchain_core.tools import tool
from ..base import Skill
from playwright.sync_api import sync_playwright


class SurveySkill(Skill):
    """Automate online surveys using browser automation."""

    _current_survey_url: Optional[str] = None
    _cookies: Optional[List[Dict]] = None

    def __init__(self, skill_root=None):
        super().__init__(skill_root)

    def _run(self, callback):
        """Execute a browser automation task."""
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            )
            if SurveySkill._cookies:
                context.add_cookies(SurveySkill._cookies)
            page = context.new_page()
            try:
                result = callback(page)
                SurveySkill._cookies = context.cookies()
                return result
            finally:
                browser.close()

    @property
    def name(self) -> str:
        return "Survey Automator"

    @property
    def description(self) -> str:
        return "Automate online surveys using browser automation"

    @property
    def triggers(self) -> List[str]:
        return ["survey", "questionnaire", "form filler"]

    def get_tools(self):
        @tool
        def load_survey(url: str) -> str:
            """
            Load survey URL, select 'None of the above' for screening, click Next.
            
            Args:
                url: The survey URL to load
            """
            try:
                SurveySkill._current_survey_url = url
                SurveySkill._cookies = None

                def run(page):
                    page.goto(url, timeout=60000)
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(2000)

                    # Auto select None of the above
                    try:
                        page.get_by_text("None of the above", exact=False).first.click()
                        page.wait_for_timeout(500)
                        page.get_by_text("Next", exact=False).first.click()
                        page.wait_for_load_state("networkidle")
                        return "✅ Survey loaded, passed screening question"
                    except Exception:
                        return "✅ Survey loaded (already past screening)"

                return self._run(run)
            except Exception as e:
                return f"Error: {str(e)}"

        @tool
        def continue_survey() -> str:
            """
            Continue survey, auto-fill known information (gender, postcode).
            """
            if not SurveySkill._current_survey_url:
                return "Load survey first"

            try:
                def run(page):
                    page.goto(SurveySkill._current_survey_url, timeout=60000)
                    page.wait_for_load_state("networkidle")

                    # Auto-fill known info
                    try:
                        # Sex/gender = male
                        page.get_by_text("Male", exact=False).first.click()
                    except Exception:
                        pass

                    try:
                        # Postcode = 2117
                        page.get_by_role(
                            "textbox",
                            name=lambda x: x and ("post" in x.lower() or "zip" in x.lower())
                        ).first.fill("2117")
                    except Exception:
                        pass

                    # Click Next
                    try:
                        page.get_by_text("Next", exact=False).first.click()
                        page.wait_for_load_state("networkidle")
                        SurveySkill._current_survey_url = page.url
                        return "✅ Moved to next page"
                    except Exception:
                        return "✅ Page processed"

                return self._run(run)
            except Exception as e:
                return f"Error: {str(e)}"

        return [load_survey, continue_survey]
