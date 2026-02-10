from typing import Dict, Any, List, Optional
import requests
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

    def get_tools(self) -> List[BaseTool]:
        @tool
        def get_weather(city: str) -> str:
            """
            Get the current weather for a specific city.
            Args:
                city: The name of the city (e.g., "London", "Tokyo").
            """
            try:
                # 1. Geocoding
                geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1&language=en&format=json"
                geo_resp = requests.get(geo_url)
                geo_data = geo_resp.json()

                if not geo_data.get("results"):
                    return f"I couldn't find the location '{city}'."

                location = geo_data["results"][0]
                lat = location["latitude"]
                lon = location["longitude"]
                name = location["name"]
                country = location.get("country", "")

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
                    f"Weather in {name}, {country}:\n"
                    f"Temperature: {temp}°C\n"
                    f"Condition: {condition}\n"
                    f"Humidity: {humidity}%\n"
                    f"Wind: {wind} km/h"
                )
            except Exception as e:
                return f"Error fetching weather: {e}"

        return [get_weather]
