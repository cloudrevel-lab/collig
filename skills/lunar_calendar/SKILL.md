---
name: Chinese Lunar Calendar
description: Converts Gregorian dates to Chinese lunar calendar and provides zodiac information
version: 1.0.0
author: Collig Team
license: MIT

tools:
  - name: get_lunar_date
    description: Get Chinese lunar calendar date for a Gregorian date
  - name: get_zodiac_sign
    description: Get Chinese zodiac sign for a given year

config:
  required: []
  optional: []

triggers:
  - lunar
  - chinese calendar
  - 农历
  - 阴历
  - zodiac
  - chinese zodiac
  - chinese year
---

# Chinese Lunar Calendar Skill

Converts Gregorian dates to Chinese lunar calendar dates and provides zodiac information.

## Usage

Use this skill when the user wants to:
- Convert dates to Chinese lunar calendar
- Find their Chinese zodiac sign
- Get traditional Chinese date information
- Look up lunar calendar dates

## Examples

- "What is my lunar birthday for 1990-05-15?"
- "What's the Chinese calendar date today?"
- "What zodiac sign is 2024?"
- "Convert my birthday to lunar calendar"

## Tools

### get_lunar_date(date_str: str = None) -> str

Get the Chinese lunar calendar date for a Gregorian date.

**Parameters:**
- `date_str`: Optional date string in format 'YYYY-MM-DD' (defaults to today)

**Returns:** Full lunar calendar date with zodiac information.

### get_zodiac_sign(year: int = None) -> str

Get the Chinese zodiac sign for a given year.

**Parameters:**
- `year`: Optional Gregorian year (defaults to current year)

**Returns:** Zodiac animal, element, and Chinese name.

## Notes

- Supports years 2020-2030 with accurate lunar calendar data
- Includes leap month handling
- Provides both English and Chinese zodiac information
- Always use when asked about Chinese calendar or zodiac
