"""
browser.py — Launch and manage a Playwright browser page.
"""

import time
from pathlib import Path
from typing import Optional

import yaml
from playwright.sync_api import sync_playwright, Page, Browser


class PageBot:
    """Wraps a Playwright browser tab with helpers for navigation, observation, and interaction."""

    def __init__(self, config_path: str = "config.yaml"):
        self._config = self._load_config(config_path)
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._page: Optional[Page] = None

    # ------------------------------------------------------------------
    # Setup / teardown
    # ------------------------------------------------------------------

    @staticmethod
    def _load_config(path: str) -> dict:
        base_path = Path(path)
        cfg: dict = yaml.safe_load(base_path.read_text()) or {}

        # Merge local overrides on top
        local = base_path.with_name("config.local.yaml")
        if local.exists():
            overrides: dict = yaml.safe_load(local.read_text()) or {}
            _deep_merge(cfg, overrides)

        return cfg

    def start(self):
        """Launch the browser and open a new page."""
        self._playwright = sync_playwright().start()
        bc = self._config.get("browser", {})
        self._browser = self._playwright.chromium.launch(
            headless=bc.get("headless", False),
            slow_mo=bc.get("slow_mo", 100),
        )
        vp = bc.get("viewport", {"width": 1280, "height": 800})
        ctx = self._browser.new_context(viewport=vp)
        self._page = ctx.new_page()
        return self

    def stop(self):
        """Close the page and browser session."""
        if self._page:
            self._page.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    def __enter__(self):
        return self.start()

    def __exit__(self, *args):
        self.stop()

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def go(self, url: str):
        """Navigate to *url* and wait for the page to load."""
        self._page.goto(url, wait_until="load")
        return self

    def refresh(self):
        self._page.reload(wait_until="load")
        return self

    # ------------------------------------------------------------------
    # Element interaction
    # ------------------------------------------------------------------

    def click(self, selector: str, *, timeout: int = None):
        """Click the first element matching *selector*."""
        self._page.click(selector, timeout=timeout or self._timeout())
        return self

    def click_text(self, text: str, *, timeout: int = None):
        """Click an element by its visible text content (case-insensitive partial match)."""
        self._page.get_by_text(text, exact=False).first.click(
            timeout=timeout or self._timeout()
        )
        return self

    def type_into(self, selector: str, text: str, *, clear: bool = True, timeout: int = None):
        """Type *text* into the element at *selector*."""
        el = self._page.locator(selector).first
        if clear:
            el.fill("")
        el.fill(text, timeout=timeout or self._timeout())
        return self

    def press(self, key: str):
        """Press a keyboard key on the focused element (e.g. 'Enter', 'Tab')."""
        self._page.keyboard.press(key)
        return self

    def wait_for(self, selector: str, *, timeout: int = None, state: str = "visible"):
        """Wait for an element matching *selector* to appear."""
        self._page.wait_for_selector(selector, timeout=timeout or self._timeout(), state=state)
        return self

    # ------------------------------------------------------------------
    # Reading the page
    # ------------------------------------------------------------------

    def text(self, selector: str) -> str:
        """Return the trimmed inner text of the first matching element."""
        return self._page.text_content(selector) or ""

    def all_text(self, selector: str) -> list[str]:
        """Return inner text of every element matching *selector*."""
        return self._page.locator(selector).all_inner_texts()

    def page_text(self) -> str:
        """Return the visible text of the whole page."""
        return self._page.inner_text("body")

    def count(self, selector: str) -> int:
        """Return how many elements match *selector*."""
        return self._page.locator(selector).count()

    def exists(self, selector: str) -> bool:
        return self._page.locator(selector).count() > 0

    def screenshot(self, path: str = "screenshot.png"):
        """Save a screenshot of the current page."""
        self._page.screenshot(path=path, full_page=True)
        return path

    # ------------------------------------------------------------------
    # Observe / poll (for countdowns, changing text, etc.)
    # ------------------------------------------------------------------

    def poll_text(
        self,
        selector: str,
        *,
        timeout: int = None,
        poll_interval: float = None,
        until_contains: str = None,
        until_not_contains: str = None,
        until_stops_changing: float = None,
    ):
        """
        Repeatedly read *selector*'s text until one of the *until_* conditions
        is met.

        Returns the final text value read.

        Parameters
        ----------
        until_stops_changing : float
            How many seconds the text must stay stable before returning.
        """
        deadline = time.time() + (timeout / 1000 if timeout else self._timeout() / 1000)
        interval = poll_interval if poll_interval is not None else self._config.get("defaults", {}).get("poll_interval", 0.5)

        last_text = ""
        stable_since = None

        while time.time() < deadline:
            raw = self._page.locator(selector).first.text_content() or ""
            text = raw.strip()

            if until_contains and until_contains in text:
                return text
            if until_not_contains and until_not_contains not in text:
                return text

            if until_stops_changing:
                if text == last_text and text:
                    if stable_since is None:
                        stable_since = time.time()
                    elif time.time() - stable_since >= until_stops_changing:
                        return text
                else:
                    stable_since = None

            last_text = text
            time.sleep(interval)

        return last_text

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _timeout(self):
        return self._config.get("defaults", {}).get("timeout", 15000)

    @property
    def page(self) -> Page:
        return self._page


# ------------------------------------------------------------------
# Utilities
# ------------------------------------------------------------------

def _deep_merge(base: dict, overlay: dict):
    """Merge *overlay* into *base* recursively (mutates base)."""
    for key, val in overlay.items():
        if key in base and isinstance(base[key], dict) and isinstance(val, dict):
            _deep_merge(base[key], val)
        else:
            base[key] = val
