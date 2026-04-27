---
name: Date Calculator
description: Calculates future or past dates based on natural language queries
version: 1.0.0
author: Collig Team
license: MIT

tools:
  - name: calculate_date
    description: Calculate a date based on natural language query

config:
  required: []
  optional: []

triggers:
  - date
  - time
  - calendar
  - when is
  - next monday
  - next week
  - tomorrow
  - yesterday
---

# Date Calculator Skill

Calculates future or past dates based on natural language queries.

## Usage

Use this skill when the user wants to:
- Calculate dates relative to today
- Find specific weekdays (next Monday, this Friday, etc.)
- Calculate date offsets (in 3 days, 2 weeks from now)

## Examples

- "What date is next Monday?"
- "When is tomorrow?"
- "What's the date in 2 weeks?"
- "Calculate the date 5 days from now"

## Tools

### calculate_date(query: str, base_date: str = None) -> str

Calculate a date based on a natural language query.

**Parameters:**
- `query`: Natural language date request (e.g., "next Monday", "2 weeks from now")
- `base_date`: Optional base date in ISO format (defaults to today)

**Returns:** Formatted date calculation result.

## Notes

- Supports common phrases: today, tomorrow, yesterday, next [weekday], this [weekday], next week
- Uses dateutil library for robust date parsing
- Base date defaults to current date if not specified
