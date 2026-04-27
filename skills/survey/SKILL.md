---
name: Survey Automator
description: Automate online surveys using browser automation
version: 1.0.0
author: Collig Team
license: MIT

tools:
  - name: load_survey
    description: Load survey URL and pass screening questions
  - name: continue_survey
    description: Continue survey with auto-fill for known information

config:
  required: []
  optional:
    - SURVEY_POSTCODE: Default postcode for survey forms (default: 2117)
    - SURVEY_GENDER: Default gender selection (default: Male)

triggers:
  - survey
  - questionnaire
  - form filler
---

# Survey Automator Skill

Automates online survey completion using browser automation with Playwright.

## Usage

Use this skill when the user wants to:
- Load and complete online surveys
- Pass screening questions automatically
- Auto-fill known information (postcode, gender, etc.)

## Examples

- "Load this survey: https://example.com/survey"
- "Continue the survey"
- "Fill out the questionnaire"

## Tools

### load_survey(url: str) -> str

Load survey URL, select 'None of the above' for screening, click Next.

**Parameters:**
- `url`: The survey URL to load

**Returns:** Confirmation of survey load status.

### continue_survey() -> str

Continue survey, auto-fill male/gender, postcode 2117, click Next.

**Returns:** Progress confirmation.

## Notes

- Uses Playwright with headless Chromium
- Maintains session cookies between calls
- Auto-selects "None of the above" for screening questions
- Auto-fills common fields (postcode: 2117, gender: Male)
- Session persists during survey completion

## Configuration

Configure default values via environment variables or config:
- `SURVEY_POSTCODE`: Default postcode (default: 2117)
- `SURVEY_GENDER`: Default gender selection (default: Male)
