import datetime
from dateutil import parser, relativedelta
from typing import List
# Fix import path: core.skill doesn't exist directly if running from project root
# It should be imported as:
from skills.base import Skill
from langchain_core.tools import tool

class DateCalculatorSkill(Skill):
    def __init__(self):
        super().__init__()
        self.state = "IDLE"

    @property
    def name(self) -> str:
        return "Date Calculator"

    @property
    def description(self) -> str:
        return "Calculates future or past dates based on natural language queries like 'next Monday', 'in 3 days', etc."

    @property
    def triggers(self) -> List[str]:
        return ["date", "time", "calendar", "when is", "next monday", "next week", "tomorrow", "yesterday"]

    def load_tools(self) -> List[object]:
        @tool
        def calculate_date(query: str, base_date: str = None) -> str:
            """
            Calculates a specific date based on a natural language query relative to the current date.
            Args:
                query: The natural language date request (e.g., "next Monday", "2 weeks from now").
                base_date: Optional base date string (ISO format preferred) to calculate from. Defaults to today.
            """
            try:
                # Set base date
                if base_date:
                    try:
                        current = parser.parse(base_date)
                    except:
                        return f"Error: Invalid base_date format '{base_date}'."
                else:
                    current = datetime.datetime.now()
                
                query = query.lower().strip()
                
                # Simple heuristic handling for common phrases
                # Note: For production, a library like 'parsedatetime' or 'dateparser' is better, 
                # but we'll use dateutil + custom logic to avoid heavy dependencies if not present.
                
                target_date = current

                if "today" in query:
                    target_date = current
                elif "tomorrow" in query:
                    target_date = current + datetime.timedelta(days=1)
                elif "yesterday" in query:
                    target_date = current - datetime.timedelta(days=1)
                elif "next monday" in query:
                    # 'relativedelta' handles "next Monday" as the Monday of next week usually,
                    # but simple logic: find next occurrence of Monday.
                    # weekday(): Mon=0, Sun=6
                    days_ahead = 0 - current.weekday()
                    if days_ahead <= 0: # Target day already happened this week
                        days_ahead += 7
                    target_date = current + datetime.timedelta(days=days_ahead)
                    
                    # If user specifically said "next monday" and today is Tuesday, 
                    # standard "next Monday" usually means the one in the *following* week (7+ days away) 
                    # vs "this coming Monday". Ambiguity exists.
                    # Let's assume "next Monday" means the very next Monday on the calendar.
                    pass

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
                        # "This Friday" usually means the upcoming Friday in current week
                        days_ahead = i - current.weekday()
                        # If today is Friday, "this Friday" might mean today or next week? Assume today.
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
