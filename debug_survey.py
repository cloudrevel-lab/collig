#!/usr/bin/env python3
"""Debug script to see exactly what content is on the survey page."""

import sys
sys.path.insert(0, '.')

from playwright.sync_api import sync_playwright

url = "https://survey.confirmit.com.au/wix/p133817785613.aspx?__sid__=3zkWbibhSzShjU_LxsHiImnm_MbhPiFMKNd3kJZqOBf4baGpVW0cZJkEp57fvOjfKOEHiqwoZCiqWfixMkKXQQ2"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    )
    page = context.new_page()

    print("Loading page...")
    page.goto(url, timeout=60000)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(3000)

    # Check for iframes
    iframes = page.query_selector_all('iframe')
    print(f"\nFound {len(iframes)} iframes:")
    for i, iframe in enumerate(iframes):
        print(f"  Iframe {i}: {iframe.get_attribute('src') or 'no src'}")

    # Switch to first iframe if exists
    if iframes:
        print("\nSwitching to first iframe...")
        frame = page.frame_locator('iframe').first
        page = frame.page

    # Get page title
    print(f"\nPage title: {page.title()}")

    # Get all text on page
    all_text = page.text_content('body') or ""

    # Search for all none variants
    print("\nSearching for 'none' in page text:")
    lines = all_text.split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue
        lower_line = line.lower()
        if 'none' in lower_line or 'no' in lower_line:
            print(f"  Found: {line}")

    # Get all radio buttons
    print("\nAll radio buttons found:")
    radios = page.query_selector_all('input[type="radio"]')
    for i, radio in enumerate(radios):
        # Get parent text
        parent = radio.evaluate_handle('el => el.parentElement')
        parent_text = parent.text_content().strip() if parent else "No text"
        value = radio.get_attribute('value') or "No value"
        print(f"  Radio {i}: value='{value}', text='{parent_text}'")

    # Check for next button
    print("\nChecking for Next buttons:")
    next_selectors = [
        'button:has-text("Next")',
        'input[type="submit"][value*="Next"]',
        'button',
        'input[type="submit"]'
    ]
    for sel in next_selectors:
        btns = page.query_selector_all(sel)
        for btn in btns:
            text = btn.text_content().strip() if btn.text_content() else btn.get_attribute('value') or "No text"
            enabled = btn.is_enabled()
            print(f"  Button: text='{text}', enabled={enabled}")

    browser.close()
