"""
observer.py — Monitor page elements that change over time (countdowns, statuses, etc.).

Designed to be composed with a PageBot instance.
"""

import re
import time
from typing import Optional

# ------------------------------------------------------------------
# Countdown watcher
# ------------------------------------------------------------------


class CountdownWatcher:
    """
    Watch an element whose text contains a countdown (e.g. "00:05:12")
    and report when it hits zero or a target value.
    """

    # Common time patterns — will match the *last* occurrence in the text
    PATTERNS = [
        re.compile(r"(\d{2}:\d{2}:\d{2})"),           # 01:23:45
        re.compile(r"(\d{2}:\d{2})"),                  # 01:23  (minutes:seconds)
        re.compile(r"(\d+)\s*(seconds?|sec|s)\b", re.I),  # 45 seconds / 45 sec
        re.compile(r"(\d+)\s*(minutes?|min|m)\b", re.I),  # 5 minutes / 5 min
    ]

    def __init__(self, bot, selector: str):
        self.bot = bot
        self.selector = selector
        self._latest_raw = ""
        self._latest_seconds: Optional[int] = None

    @property
    def raw_text(self) -> str:
        """Current text of the watched element."""
        return self._latest_raw

    @property
    def seconds(self) -> Optional[int]:
        """Current countdown value in seconds (None if couldn't parse)."""
        return self._latest_seconds

    def read(self) -> tuple[str, Optional[int]]:
        """Fetch the element text and parse it. Returns (raw_text, seconds)."""
        self._latest_raw = self.bot.text(self.selector)
        self._latest_seconds = self._parse(self._latest_raw)
        return self._latest_raw, self._latest_seconds

    def wait_until(self, target: int = 0, *, timeout: int = None, poll_interval: float = 0.5):
        """
        Poll until the countdown reaches *target* (default 0, meaning expired).
        Returns the final (raw_text, seconds).
        Raises TimeoutError if the value never reaches target.
        """
        deadline = time.time() + ((timeout or self.bot._timeout()) / 1000)
        while time.time() < deadline:
            raw, secs = self.read()
            if secs is not None and secs <= target:
                return raw, secs
            time.sleep(poll_interval)
        raise TimeoutError(
            f"Countdown never reached {target}s (last value: {self._latest_raw})"
        )

    def wait_until_changes(self, *, timeout: int = None, poll_interval: float = 0.5):
        """
        Wait until the countdown value decreases (moves forward).
        Returns the new (raw_text, seconds).
        """
        _, initial = self.read()
        deadline = time.time() + ((timeout or self.bot._timeout()) / 1000)
        while time.time() < deadline:
            raw, secs = self.read()
            if secs is not None and initial is not None and secs < initial:
                return raw, secs
            time.sleep(poll_interval)
        raise TimeoutError("Countdown value never changed")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @classmethod
    def _parse(cls, raw: str) -> Optional[int]:
        raw = raw.strip()
        for pat in cls.PATTERNS:
            m = pat.search(raw)
            if not m:
                continue
            token = m.group(1)

            colons = token.count(":")
            if colons == 2:  # HH:MM:SS
                parts = token.split(":")
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif colons == 1:  # MM:SS
                parts = token.split(":")
                return int(parts[0]) * 60 + int(parts[1])
            else:  # bare number + unit — check second group for time unit
                val = int(m.group(1))
                unit = (m.group(2) or "").lower()
                if unit in ("m", "min", "minute", "minutes"):
                    return val * 60
                return val  # seconds
        return None


# ------------------------------------------------------------------
# Generic text-change watcher
# ------------------------------------------------------------------


class TextWatcher:
    """Wait for a page element's text to contain/stop containing a string."""

    def __init__(self, bot, selector: str):
        self.bot = bot
        self.selector = selector

    def wait_until_contains(self, text: str, *, timeout: int = None, poll_interval: float = 0.5):
        deadline = time.time() + ((timeout or self.bot._timeout()) / 1000)
        while time.time() < deadline:
            val = self.bot.text(self.selector)
            if text in val:
                return val
            time.sleep(poll_interval)
        raise TimeoutError(f"Element '{self.selector}' never contained '{text}'")

    def wait_until_not_contains(self, text: str, *, timeout: int = None, poll_interval: float = 0.5):
        deadline = time.time() + ((timeout or self.bot._timeout()) / 1000)
        while time.time() < deadline:
            val = self.bot.text(self.selector)
            if text not in val:
                return val
            time.sleep(poll_interval)
        raise TimeoutError(f"Element '{self.selector}' never stopped containing '{text}'")


# ------------------------------------------------------------------
# Page-state waiter
# ------------------------------------------------------------------


def wait_for_url_change(bot, *, timeout: int = None, poll_interval: float = 0.3):
    """Return the new URL after the page navigates (waits for change from current URL)."""
    current = bot.page.url
    deadline = time.time() + ((timeout or bot._timeout()) / 1000)
    while time.time() < deadline:
        time.sleep(poll_interval)
        try:
            new_url = bot.page.url
        except Exception:
            continue
        if new_url != current:
            return new_url
    raise TimeoutError("URL never changed from " + current)
