from typing import Dict, Any, List, Optional
import requests
import re
from langchain_core.tools import tool, BaseTool
from .base import Skill

class WeatherSkill(Skill):
    def __init__(self):
        super().__init__()

    @property
    def name(self) -> str:
        return "Weather Reporter"

    @property
    def description(self) -> str:
        return "Provides current weather information using Open-Meteo."

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

    def get_tools(self) -> List[BaseTool]:
        @tool
        def get_weather(city: str) -> str:
            """
            Get the current weather for a specific city.
            Args:
                city: The name of the city (e.g., "London", "Tokyo", "Oatlands NSW 2117").
            """
            try:
                # Parse the query to extract city, state, postcode
                target_city, target_state, target_postcode = self._parse_location_query(city)

                # 1. Geocoding - get more results to choose from
                geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={target_city}&count=20&language=en&format=json"
                geo_resp = requests.get(geo_url)
                geo_data = geo_resp.json()

                if not geo_data.get("results"):
                    # Try with original query if parsing stripped too much
                    if target_city != city:
                        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=20&language=en&format=json"
                        geo_resp = requests.get(geo_url)
                        geo_data = geo_resp.json()

                    if not geo_data.get("results"):
                        return f"I couldn't find the location '{city}'."

                # Score and sort locations to find the best match
                locations = geo_data["results"]
                scored_locations = [
                    (loc, self._score_location_match(loc, target_city, target_state))
                    for loc in locations
                ]
                scored_locations.sort(key=lambda x: x[1], reverse=True)

                # Pick the best match
                location = scored_locations[0][0]
                lat = location["latitude"]
                lon = location["longitude"]
                name = location["name"]
                country = location.get("country", "")
                admin1 = location.get("admin1", "")

                # Build display location string
                location_parts = [name]
                if admin1:
                    location_parts.append(admin1)
                location_parts.append(country)
                display_location = ", ".join(location_parts)

                # 2. Weather
                weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m&temperature_unit=celsius&wind_speed_unit=kmh"
                weather_resp = requests.get(weather_url)
                weather_data = weather_resp.json()

                current = weather_data.get("current", {})
                temp = current.get("temperature_2m")
                humidity = current.get("relative_humidity_2m")
                wind = current.get("wind_speed_10m")
                code = current.get("weather_code")

                # Weather codes interpretation
                condition = "Unknown"
                if code == 0: condition = "Clear sky"
                elif code in [1, 2, 3]: condition = "Partly cloudy"
                elif code in [45, 48]: condition = "Foggy"
                elif code in [51, 53, 55]: condition = "Drizzle"
                elif code in [61, 63, 65]: condition = "Rain"
                elif code in [71, 73, 75]: condition = "Snow"
                elif code in [95, 96, 99]: condition = "Thunderstorm"

                return (
                    f"Weather in {display_location}:\n"
                    f"Temperature: {temp}°C\n"
                    f"Condition: {condition}\n"
                    f"Humidity: {humidity}%\n"
                    f"Wind: {wind} km/h"
                )
            except Exception as e:
                return f"Error fetching weather: {e}"

        return [get_weather]
