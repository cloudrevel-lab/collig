import datetime
from typing import List

from langchain_core.tools import tool

from skills.base import Skill


class LunarCalendarSkill(Skill):
    def __init__(self):
        super().__init__()
        self.state = "IDLE"

        # Chinese zodiac animals (12-year cycle)
        self.zodiac_animals = [
            "Rat",
            "Ox",
            "Tiger",
            "Rabbit",
            "Dragon",
            "Snake",
            "Horse",
            "Goat",
            "Monkey",
            "Rooster",
            "Dog",
            "Pig",
        ]

        # Chinese zodiac elements (10-year cycle)
        self.zodiac_elements = ["Metal", "Metal", "Water", "Water", "Wood", "Wood", "Fire", "Fire", "Earth", "Earth"]

        # Chinese zodiac stems (heavenly stems)
        self.heavenly_stems = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]

        # Chinese zodiac branches (earthly branches)
        self.earthly_branches = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]

        # Lunar month names
        self.lunar_months = [
            "正月",
            "杏月",
            "桃月",
            "槐月",
            "蒲月",
            "荷月",
            "巧月",
            "桂月",
            "菊月",
            "阳月",
            "冬月",
            "腊月",
        ]

        # Chinese New Year dates (Gregorian) for 2020-2030
        # Format: year -> (month, day) of Chinese New Year
        self.chinese_new_years = {
            2020: (1, 25),
            2021: (2, 12),
            2022: (2, 1),
            2023: (1, 22),
            2024: (2, 10),
            2025: (1, 29),
            2026: (2, 17),
            2027: (2, 6),
            2028: (1, 26),
            2029: (2, 13),
            2030: (2, 3),
        }

        # Lunar month info for each year (2020-2030)
        # Format: year -> (leap_month, [month_lengths])
        # leap_month = 0 means no leap month that year
        # month_lengths: 29 or 30 days per month
        # If there's a leap month, it's inserted after the specified month
        self.lunar_year_info = {
            2020: (4, [29, 30, 29, 30, 29, 30, 29, 29, 30, 29, 30, 30, 29]),  # leap 4
            2021: (0, [29, 30, 29, 30, 29, 30, 29, 29, 30, 29, 30, 29]),  # no leap
            2022: (0, [30, 29, 30, 29, 30, 29, 30, 29, 29, 30, 29, 30]),  # no leap
            2023: (2, [30, 29, 29, 30, 29, 30, 29, 30, 29, 29, 30, 30, 29]),  # leap 2
            2024: (0, [30, 29, 30, 29, 30, 29, 30, 29, 29, 30, 29, 30]),  # no leap
            2025: (6, [29, 30, 29, 30, 29, 30, 29, 29, 30, 29, 30, 29, 30]),  # leap 6
            2026: (0, [29, 30, 30, 29, 30, 29, 30, 29, 29, 30, 29, 30]),  # no leap
            2027: (0, [29, 29, 30, 30, 29, 30, 29, 30, 29, 29, 30, 29]),  # no leap
            2028: (5, [30, 29, 29, 30, 30, 29, 30, 29, 30, 29, 29, 30, 29]),  # leap 5
            2029: (0, [30, 29, 29, 30, 29, 30, 30, 29, 30, 29, 29, 30]),  # no leap
            2030: (0, [29, 30, 29, 29, 30, 29, 30, 30, 29, 30, 29, 29]),  # no leap
        }

    @property
    def name(self) -> str:
        return "Chinese Lunar Calendar"

    @property
    def description(self) -> str:
        return (
            "Converts Gregorian dates to Chinese lunar calendar dates and provides zodiac information. "
            "Always use this tool when asked about Chinese calendar, lunar calendar, zodiac, "
            "or traditional Chinese dates."
        )

    @property
    def triggers(self) -> List[str]:
        return ["lunar", "chinese calendar", "农历", "阴历", "zodiac", "chinese zodiac", "chinese year"]

    def _get_zodiac_animal(self, year: int) -> str:
        """Get the Chinese zodiac animal for a given year."""
        # The zodiac cycle starts with Rat in 1900
        return self.zodiac_animals[(year - 1900) % 12]

    def _get_zodiac_element(self, year: int) -> str:
        """Get the Chinese zodiac element for a given year."""
        return self.zodiac_elements[(year - 1900) % 10]

    def _get_zodiac_chinese(self, year: int) -> str:
        """Get the Chinese zodiac name (stem + branch) for a given year."""
        stem = self.heavenly_stems[(year - 4) % 10]
        branch = self.earthly_branches[(year - 4) % 12]
        return f"{stem}{branch}"

    def _get_month_lengths_for_year(self, lunar_year: int) -> List[int]:
        """Get the list of month lengths for a lunar year."""
        if lunar_year in self.lunar_year_info:
            leap_month, month_lengths = self.lunar_year_info[lunar_year]
            return month_lengths
        return [30, 29] * 6  # fallback

    def _gregorian_to_lunar(self, gregorian_date: datetime.date) -> tuple:
        """
        Convert Gregorian date to Chinese lunar date.
        Returns: (lunar_year, lunar_month, lunar_day, is_leap_month)
        """
        year = gregorian_date.year

        # Get Chinese New Year date for this year
        if year not in self.chinese_new_years:
            return None

        cny_month, cny_day = self.chinese_new_years[year]
        cny_date = datetime.date(year, cny_month, cny_day)

        # Determine which lunar year we're in
        if gregorian_date < cny_date:
            # Date is before CNY, belongs to previous lunar year
            lunar_year = year - 1
            prev_cny_month, prev_cny_day = self.chinese_new_years[lunar_year]
            start_date = datetime.date(lunar_year, prev_cny_month, prev_cny_day)
        else:
            # Date is on or after CNY, belongs to current lunar year
            lunar_year = year
            start_date = cny_date

        # Get month lengths for the lunar year
        if lunar_year not in self.lunar_year_info:
            return None

        leap_month, month_lengths = self.lunar_year_info[lunar_year]

        # Calculate days since start of lunar year
        days_diff = (gregorian_date - start_date).days

        if days_diff < 0:
            return None

        # Find which lunar month and day
        remaining_days = days_diff

        for i, month_len in enumerate(month_lengths):
            if remaining_days < month_len:
                # Found the month
                lunar_day = remaining_days + 1

                if leap_month == 0:
                    # No leap month this year
                    lunar_month = i + 1
                    is_leap = False
                else:
                    # There is a leap month this year
                    if i < leap_month:
                        # Before the leap month - normal numbering
                        lunar_month = i + 1
                        is_leap = False
                    elif i == leap_month:
                        # This is the leap month
                        lunar_month = leap_month
                        is_leap = True
                    else:
                        # After the leap month - subtract 1 from index
                        lunar_month = i
                        is_leap = False

                return (lunar_year, lunar_month, lunar_day, is_leap)
            remaining_days -= month_len

        return None

    def _get_lunar_day_chinese(self, day: int) -> str:
        """Convert lunar day number to Chinese representation."""
        if day == 10:
            return "初十"
        elif day == 20:
            return "二十"
        elif day == 30:
            return "三十"
        elif day < 10:
            chinese_nums = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九"]
            return f"初{chinese_nums[day]}"
        elif 10 < day < 20:
            chinese_nums = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九"]
            return f"十{chinese_nums[day - 10]}"
        elif 20 < day < 30:
            chinese_nums = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九"]
            return f"廿{chinese_nums[day - 20]}"
        else:
            return str(day)

    def get_tools(self) -> List[object]:
        @tool
        def get_lunar_date(date_str: str = None) -> str:
            """
            Get the Chinese lunar calendar date for a given Gregorian date.
            ALWAYS USE THIS TOOL when asked about Chinese calendar, lunar calendar,
            Chinese zodiac, or traditional Chinese dates.

            Args:
                date_str: Optional date string in format 'YYYY-MM-DD'. Defaults to today.
            """
            try:
                if date_str:
                    try:
                        gregorian_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
                    except ValueError:
                        return f"Error: Invalid date format '{date_str}'. Use 'YYYY-MM-DD' format."
                else:
                    gregorian_date = datetime.date.today()

                # Convert to lunar date
                lunar_result = self._gregorian_to_lunar(gregorian_date)

                if not lunar_result:
                    return f"Error: Lunar calendar conversion not available for year {gregorian_date.year}."

                lunar_year, lunar_month, lunar_day, is_leap = lunar_result

                # Get zodiac information
                zodiac_animal = self._get_zodiac_animal(lunar_year)
                zodiac_element = self._get_zodiac_element(lunar_year)
                zodiac_chinese = self._get_zodiac_chinese(lunar_year)

                # Get lunar month name
                if lunar_month <= 12:
                    lunar_month_name = self.lunar_months[lunar_month - 1]
                else:
                    lunar_month_name = f"第{lunar_month}月"

                if is_leap:
                    lunar_month_name = f"闰{lunar_month_name}"

                # Get lunar day in Chinese
                lunar_day_chinese = self._get_lunar_day_chinese(lunar_day)

                # Format the response
                leap_note = " (leap month)" if is_leap else ""
                response = (
                    f"Gregorian Date: {gregorian_date.strftime('%B %d, %Y')}\n"
                    f"Chinese Lunar Date: {lunar_day_chinese} ({lunar_day}日) of the {lunar_month_name}{leap_note} "
                    f"in the year of the {zodiac_element} {zodiac_animal} ({zodiac_chinese}年)\n"
                    f"Lunar Year: {lunar_year}\n"
                    f"Lunar Month: {lunar_month}{leap_note}\n"
                    f"Lunar Day: {lunar_day}"
                )

                return response

            except Exception as e:
                return f"Error converting to lunar calendar: {str(e)}"

        @tool
        def get_zodiac_sign(year: int = None) -> str:
            """
            Get the Chinese zodiac sign for a given year.

            Args:
                year: Optional Gregorian year. Defaults to current year.
            """
            try:
                if year is None:
                    year = datetime.date.today().year

                zodiac_animal = self._get_zodiac_animal(year)
                zodiac_element = self._get_zodiac_element(year)
                zodiac_chinese = self._get_zodiac_chinese(year)

                return (
                    f"Year {year} is the year of the {zodiac_element} {zodiac_animal} ({zodiac_chinese}年).\n"
                    f"Zodiac Animal: {zodiac_animal}\n"
                    f"Zodiac Element: {zodiac_element}"
                )

            except Exception as e:
                return f"Error getting zodiac sign: {str(e)}"

        return [get_lunar_date, get_zodiac_sign]
