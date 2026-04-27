---
name: Weather Reporter
description: Provides current weather information and forecasts using Open-Meteo API
version: 1.0.0
author: Collig Team
license: MIT

tools:
  - name: get_weather
    description: Get the current weather or forecast for a specific city

config:
  required: []
  optional:
    - WEATHER_UNITS: Temperature units (celsius or fahrenheit), default: celsius

triggers:
  - weather
  - forecast
  - temperature
  - is it raining
  - what's the weather
---

# Weather Reporter Skill

Provides accurate weather information and forecasts for any location worldwide using the Open-Meteo API.

## Usage

Use this skill when the user asks about:
- Current weather conditions
- Weather forecasts for today or upcoming days
- Temperature, humidity, wind, or precipitation information
- Weather conditions for a specific city or location

## Examples

- "What's the weather in Sydney?"
- "Will it rain in London tomorrow?"
- "What's the forecast for Paris next week?"
- "Is it sunny in Tokyo right now?"

## Tools

### get_weather(query: str) -> str

Get weather information for a location.

**Parameters:**
- `query`: Location query with optional date hint (e.g., "Sydney", "London tomorrow", "Paris next Monday")

**Supported date hints:**
- today, now, current
- tomorrow, tmr, tmrw
- day after tomorrow
- next week
- Specific day names (Monday, Tuesday, etc.)

**Returns:** Formatted weather report with temperature, conditions, and relevant metrics.

## Notes

- Uses Open-Meteo API (no API key required)
- Supports forecasts up to 16 days
- Temperature in Celsius, wind speed in km/h by default
- Automatically handles location geocoding
