"""
Weather Reporter Skill - Portable implementation following agentskills.io spec.

Provides current weather information and forecasts using Open-Meteo API.
"""
from typing import List, Optional, Dict, Any
import requests
import re
from datetime import datetime, timedelta
from langchain_core.tools import tool, BaseTool
from skills.base import Skill


class WeatherSkill(Skill):
    """Provides current weather information and forecasts using Open-Meteo API."""

    def __init__(self, skill_root=None):
        super().__init__(skill_root)

    @property
    def name(self) -> str:
        return "Weather Reporter"

    @property
    def description(self) -> str:
        return "Provides current weather information and forecasts using Open-Meteo API"

    @property
    def triggers(self) -> List[str]:
        return [
            "weather", "forecast", "temperature", "is it raining",
            "what's the weather", "what is the weather"
        ]

    def _parse_location_query(self, query: str) -> tuple[str, Optional[str], Optional[str]]:
        """
        Parse a location query to extract city, state/region, and postcode.
        Handles formats like "Oatlands NSW 2117" or "Sydney, Australia".
        """
        query = query.strip()

        # Australian state abbreviations mapping
        state_abbrevs = {
            "NSW": "New South Wales",
            "VIC": "Victoria",
            "QLD": "Queensland",
            "WA": "Western Australia",
            "SA": "South Australia",
            "TAS": "Tasmania",
            "ACT": "Australian Capital Territory",
            "NT": "Northern Territory"
        }

        # Look for postcode (4 digits)
        postcode = None
        postcode_match = re.search(r'\b(\d{4})\b', query)
        if postcode_match:
            postcode = postcode_match.group(1)
            query = re.sub(r'\b\d{4}\b', '', query).strip()

        # Look for state abbreviations or names
        state = None
        for abbrev, full in state_abbrevs.items():
            if re.search(r'\b' + re.escape(abbrev) + r'\b', query, re.IGNORECASE):
                state = full
                query = re.sub(r'\b' + re.escape(abbrev) + r'\b', '', query, flags=re.IGNORECASE).strip()
                break
            if re.search(r'\b' + re.escape(full) + r'\b', query, re.IGNORECASE):
                state = full
                query = re.sub(r'\b' + re.escape(full) + r'\b', '', query, flags=re.IGNORECASE).strip()
                break

        # Clean up separators
        query = re.sub(r'[,\s]+', ' ', query).strip()

        return query, state, postcode

    def _score_location_match(self, location: Dict, target_city: str, target_state: Optional[str]) -> int:
        """Score how well a location matches the target query."""
        score = 0
        target_city_lower = target_city.lower()

        # Exact name match is best
        if location.get("name", "").lower() == target_city_lower:
            score += 100

        # Name contains target city
        elif target_city_lower in location.get("name", "").lower():
            score += 50

        # State/region match
        if target_state:
            admin1 = location.get("admin1", "")
            if admin1 and target_state.lower() in admin1.lower():
                score += 75

        # Prefer higher population (more likely to be the desired location)
        population = location.get("population", 0)
        if population:
            score += min(population // 1000, 50)  # Cap at 50

        return score

    # Phrases that ask for more than one day rather than a single date.
    WEEK_RANGE_HINTS = (
        "rest of the week",
        "the rest of the week",
        "this week",
        "next few days",
        "coming days",
        "week forecast",
        "7-day",
        "7 day",
        "seven day",
        "weekend",
    )

    def _parse_date_hint(self, query: str) -> tuple[int, bool, str]:
        """
        Split a query into ``(days_ahead, week_range, query_without_the_hint)``.

        ``week_range`` is True for "rest of the week" / "next few days" style
        requests, which need a multi-day answer: the assistant offers exactly
        that as a follow-up, so the tool has to be able to deliver it.
        """
        query_lower = (query or "").lower()

        days_ahead = 0  # 0 = today/current
        week_range = any(hint in query_lower for hint in self.WEEK_RANGE_HINTS)

        if week_range:
            days_ahead = 0
        elif 'day after tomorrow' in query_lower:
            days_ahead = 2
        elif any(w in query_lower for w in ['tomorrow', 'tmr', 'tmrw']):
            days_ahead = 1
        elif 'today' in query_lower or 'current' in query_lower or 'now' in query_lower:
            days_ahead = 0
        elif 'next week' in query_lower:
            days_ahead = 7
        else:
            # Check for specific day names (e.g. "on Monday", "next Monday")
            day_names = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
            today_weekday = datetime.now().weekday()
            for i, day in enumerate(day_names):
                if day in query_lower:
                    days_until = (i - today_weekday) % 7
                    if days_until == 0:
                        days_until = 7  # If same day, assume next week
                    days_ahead = days_until
                    break

        # Remove the date hint before geocoding, or the hint itself is looked
        # up as part of the place name.
        hints = (
            r'day\s+after\s+tomorrow'
            r'|rest\s+of\s+the\s+week|the\s+rest\s+of\s+the\s+week'
            r'|this\s+week|next\s+few\s+days|coming\s+days|week\s+forecast'
            r'|7[\s-]?day|seven\s+day|weekend'
            r'|tomorrow|tmr|tmrw|today|current|now|next\s+week'
            r'|next\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)'
            r'|on\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)'
        )
        clean_query = re.sub(r'\b(' + hints + r')\b', '', query, flags=re.IGNORECASE)
        clean_query = re.sub(r'\s+', ' ', clean_query).strip()
        return days_ahead, week_range, clean_query

    def get_tools(self) -> List[BaseTool]:
        @tool
        def get_weather(query: str) -> str:
            """
            Get the current weather or forecast for a specific city.
            Supports queries like "Sydney", "Oatlands NSW 2117", "Sydney tomorrow",
            "London next week", "Paris on Monday", "Sydney rest of the week",
            "Oatlands next few days".

            Args:
                query: The city and optional date, e.g. "London",
                    "Sydney tomorrow", "Oatlands NSW 2117 next Monday",
                    "Sydney rest of the week".
            """
            try:
                # Parse the query for location and date hints.
                days_ahead, week_range, clean_query = self._parse_date_hint(query)

                target_city, target_state, target_postcode = self._parse_location_query(clean_query)

                # 1. Geocoding
                geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={target_city}&count=20&language=en&format=json"
                geo_resp = requests.get(geo_url)
                geo_data = geo_resp.json()

                if not geo_data.get("results"):
                    if target_city != clean_query:
                        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={clean_query}&count=20&language=en&format=json"
                        geo_resp = requests.get(geo_url)
                        geo_data = geo_resp.json()

                    if not geo_data.get("results"):
                        return f"I couldn't find the location '{clean_query or query}'."

                # Score and sort locations
                locations = geo_data["results"]
                scored_locations = [
                    (loc, self._score_location_match(loc, target_city, target_state))
                    for loc in locations
                ]
                scored_locations.sort(key=lambda x: x[1], reverse=True)

                location = scored_locations[0][0]
                lat = location["latitude"]
                lon = location["longitude"]
                name = location["name"]
                country = location.get("country", "")
                admin1 = location.get("admin1", "")

                location_parts = [name]
                if admin1:
                    location_parts.append(admin1)
                location_parts.append(country)
                display_location = ", ".join(location_parts)

                # 2. Weather data - always fetch forecast (up to 16 days)
                weather_url = (
                    f"https://api.open-meteo.com/v1/forecast?"
                    f"latitude={lat}&longitude={lon}"
                    f"&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m"
                    f"&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max"
                    f"&temperature_unit=celsius&wind_speed_unit=kmh"
                )
                weather_resp = requests.get(weather_url)
                weather_data = weather_resp.json()

                # Weather code interpretation
                def get_condition(code):
                    conditions = {
                        0: "Clear sky",
                        1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
                        45: "Foggy", 48: "Depositing rime fog",
                        51: "Light drizzle", 53: "Drizzle", 55: "Dense drizzle",
                        56: "Light freezing drizzle", 57: "Dense freezing drizzle",
                        61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
                        66: "Light freezing rain", 67: "Heavy freezing rain",
                        71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
                        77: "Snow grains",
                        80: "Slight showers", 81: "Moderate showers", 82: "Violent showers",
                        85: "Slight snow showers", 86: "Heavy snow showers",
                        95: "Thunderstorm", 96: "Thunderstorm with slight hail",
                        99: "Thunderstorm with heavy hail",
                    }
                    return conditions.get(code, "Unknown")

                # If days_ahead == 0, show current weather
                if days_ahead == 0:
                    current = weather_data.get("current", {})
                    temp = current.get("temperature_2m")
                    humidity = current.get("relative_humidity_2m")
                    wind = current.get("wind_speed_10m")
                    code = current.get("weather_code")
                    condition = get_condition(code)

                    return (
                        f"Current weather in {display_location}:\n"
                        f"Temperature: {temp}°C\n"
                        f"Condition: {condition}\n"
                        f"Humidity: {humidity}%\n"
                        f"Wind: {wind} km/h"
                    )
                if week_range:
                    # "rest of the week" / "next few days": one line per day,
                    # starting tomorrow and running to Sunday (at least three
                    # days, at most a week, capped by the API's 16-day window).
                    daily = weather_data.get("daily", {})
                    dates = daily.get("time", [])
                    if not dates:
                        return f"No forecast data available for {display_location}."

                    today = datetime.now()
                    first = 1
                    last = min(6 - today.weekday(), first + 5, len(dates) - 1)
                    if last < first + 2:
                        last = min(first + 2, len(dates) - 1)

                    rows = [f"Weather forecast for {display_location} — rest of the week:"]
                    for offset in range(first, last + 1):
                        target = (today + timedelta(days=offset)).strftime("%Y-%m-%d")
                        if target not in dates:
                            continue
                        idx = dates.index(target)
                        day_max = daily.get("temperature_2m_max", [None] * len(dates))[idx]
                        day_min = daily.get("temperature_2m_min", [None] * len(dates))[idx]
                        day_code = daily.get("weather_code", [None] * len(dates))[idx]
                        day_precip = daily.get("precipitation_probability_max", [None] * len(dates))[idx]
                        day_wind = daily.get("wind_speed_10m_max", [None] * len(dates))[idx]
                        label = (today + timedelta(days=offset)).strftime("%A, %B %d")
                        row = f"{label}: {get_condition(day_code)} — {day_max}°C / {day_min}°C"
                        if day_precip is not None:
                            row += f", rain {day_precip}%"
                        if day_wind is not None:
                            row += f", wind {day_wind} km/h"
                        rows.append(row)
                    return "\n".join(rows)

                # Show forecast for the requested day
                daily = weather_data.get("daily", {})
                dates = daily.get("time", [])
                target_date_str = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

                if target_date_str not in dates:
                    return (
                        f"Sorry, I can only provide forecasts for the next 16 days. "
                        f"'{query}' is beyond the forecast range."
                    )

                idx = dates.index(target_date_str)
                temp_max = daily.get("temperature_2m_max", [None] * len(dates))[idx]
                temp_min = daily.get("temperature_2m_min", [None] * len(dates))[idx]
                code = daily.get("weather_code", [None] * len(dates))[idx]
                precip = daily.get("precipitation_probability_max", [None] * len(dates))[idx]
                wind = daily.get("wind_speed_10m_max", [None] * len(dates))[idx]
                condition = get_condition(code)

                day_label = "Tomorrow" if days_ahead == 1 else f"In {days_ahead} days"
                date_display = (datetime.now() + timedelta(days=days_ahead)).strftime("%A, %B %d")

                result = f"Weather forecast for {display_location} — {day_label} ({date_display}):\n"
                result += f"Condition: {condition}\n"
                result += f"High: {temp_max}°C / Low: {temp_min}°C\n"
                if precip is not None:
                    result += f"Precipitation chance: {precip}%\n"
                if wind is not None:
                    result += f"Max wind: {wind} km/h"
                return result

            except Exception as e:
                return f"Error fetching weather: {e}"

        return [get_weather]
