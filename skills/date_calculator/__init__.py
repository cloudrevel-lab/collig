"""
Date Calculator Skill - Portable implementation following agentskills.io spec.

Calculates future or past dates based on natural language queries.
"""
import datetime
from dateutil import parser, relativedelta
from typing import List
from langchain_core.tools import tool
from skills.base import Skill


class DateCalculatorSkill(Skill):
    """Calculates future or past dates based on natural language queries."""

    def __init__(self, skill_root=None):
        super().__init__(skill_root)
        self.state = "IDLE"

    @property
    def name(self) -> str:
        return "Date Calculator"

    @property
    def description(self) -> str:
        return "Calculates future or past dates based on natural language queries"

    @property
    def triggers(self) -> List[str]:
        return [
            "date", "time", "calendar", "when is",
            "next monday", "next week", "tomorrow", "yesterday"
        ]

    def get_tools(self) -> List[object]:
        @tool
        def calculate_date(query: str, base_date: str = None) -> str:
            """
            Calculate a date based on a natural language query.
            
            Args:
                query: Natural language date request (e.g., "next Monday", "2 weeks from now")
                base_date: Optional base date in ISO format (defaults to today)
            """
            try:
                # Set base date
                if base_date:
                    try:
                        current = parser.parse(base_date)
                    except Exception:
                        return f"Error: Invalid base_date format '{base_date}'."
                else:
                    current = datetime.datetime.now()

                query = query.lower().strip()
                target_date = current

                if "today" in query:
                    target_date = current
                elif "tomorrow" in query:
                    target_date = current + datetime.timedelta(days=1)
                elif "yesterday" in query:
                    target_date = current - datetime.timedelta(days=1)
                else:
                    # Using a robust logic for "next X"
                    weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
                    matched_day = False
                    for i, day in enumerate(weekdays):
                        if f"next {day}" in query:
                            days_ahead = i - current.weekday()
                            if days_ahead <= 0:
                                days_ahead += 7
                            target_date = current + datetime.timedelta(days=days_ahead)
                            matched_day = True
                            break
                        elif f"this {day}" in query:
                            days_ahead = i - current.weekday()
                            target_date = current + datetime.timedelta(days=days_ahead)
                            matched_day = True
                            break

                    # If no specific day matched, check for "next week"
                    if not matched_day and "next week" in query:
                        target_date = current + datetime.timedelta(weeks=1)

                # Output formatted date
                return f"Today is {current.strftime('%A, %B %d, %Y')}. Date calculation for '{query}': {target_date.strftime('%A, %B %d, %Y')}"

            except Exception as e:
                return f"Error calculating date: {str(e)}"

        return [calculate_date]
