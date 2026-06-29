"""
actions.py — Higher-level composed action helpers for common interaction patterns.

Use these when you don't want to chain individual bot calls yourself.
"""

from src.browser import PageBot


def fill_and_submit(bot: PageBot, input_selector: str, text: str, submit_selector: str = None):
    """
    Fill a text field and submit.

    *submit_selector* — element to click (default: presses Enter).
    """
    bot.type_into(input_selector, text)
    if submit_selector:
        bot.click(submit_selector)
    else:
        bot.press("Enter")
    return bot


def click_link_by_text(bot: PageBot, text: str):
    """Find and click a link/button with visible *text*."""
    bot.click_text(text)
    return bot


def wait_for_text_and_click(bot: PageBot, wait_selector: str, click_selector: str):
    """Wait for an element to appear, then click something else."""
    bot.wait_for(wait_selector)
    bot.click(click_selector)
    return bot
