#!/usr/bin/env python3
"""
Example automation script — run with:

    python src/main.py <url> --script scripts/example.py
    python src/main.py <url> --script scripts/example.py --record recordings/test
    python src/main.py <url> --script scripts/example.py --manual-login --record recordings/test

This script receives `bot` (a PageBot instance) already navigated to the target URL.
If recording is active, `recorder` is also available.
"""

import time


def run(bot):
    print("--- Example script started ---")

    # 1. See what's on the page
    print(f"Page title: {bot.page.title()}")
    body = bot.page_text()
    print(f"Body length: {len(body)} chars")

    # 2. Click something by its text
    if bot.exists("text=Start"):
        print("Clicking 'Start' button...")
        bot.click_text("Start")

    # 3. Wait for a countdown element and watch it tick down
    from src.observer import CountdownWatcher, TextWatcher

    if bot.exists("#timer"):
        watcher = CountdownWatcher(bot, "#timer")
        raw, secs = watcher.read()
        print(f"Countdown at start: {raw} ({secs}s)")
        raw, secs = watcher.wait_until(target=0, timeout=60000)
        print(f"Countdown finished: {raw} ({secs}s)")
    else:
        print("No #timer element found on the page")

    # 4. Watch for text to appear
    status_watcher = TextWatcher(bot, "#status")
    try:
        val = status_watcher.wait_until_contains("Done", timeout=30000)
        print(f"Status shows: {val}")
    except TimeoutError:
        print("Status never showed 'Done'")

    # 5. Take a screenshot
    path = bot.screenshot("result.png")
    print(f"Screenshot saved: {path}")

    # 6. If recording, take named snapshots
    if "recorder" in dir() and recorder:
        recorder.snapshot("after_actions")
        print("Recording snapshot taken: after_actions")

    print("--- Example script finished ---")


if __name__ == "__main__":
    # When invoked stand-alone (not via main.py), create the bot ourselves.
    import sys
    from src.browser import PageBot
    url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
    with PageBot() as bot:
        bot.go(url)
        run(bot)
