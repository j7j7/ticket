"""
browser.py — Launch and manage a Playwright browser page.
"""

import functools
import logging
import time
from pathlib import Path
from typing import Optional, TYPE_CHECKING

import yaml
from playwright.sync_api import Error as PwError
from playwright.sync_api import sync_playwright, Page, Browser
from playwright.sync_api import TimeoutError as PwTimeout

from src.exceptions import BrowserError, ElementError, NavigationError, TimeoutError
from src.auth import load_auth_state

if TYPE_CHECKING:
    from src.recorder import SessionRecorder

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _retry(max_attempts: int = 2, delay: float = 1.0):
    """Decorator: retry a *PageBot* method if it raises a transient failure.

    Only retries on ``PwError`` (network / browser glitch).  Other
    exceptions (including our own) propagate immediately.
    """

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(self, *args, **kwargs):
            last_err = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(self, *args, **kwargs)
                except PwError as exc:
                    last_err = exc
                    if attempt < max_attempts:
                        logger.warning(
                            "%s attempt %d/%d failed: %s",
                            fn.__name__, attempt, max_attempts, exc,
                        )
                        time.sleep(delay)
            raise BrowserError(
                f"{fn.__name__} failed after {max_attempts} attempts: {last_err}"
            ) from last_err

        return wrapper

    return decorator


class PageBot:
    """Wraps a Playwright browser tab with helpers for navigation, observation, and interaction."""

    def __init__(self, config_path: str = "config.yaml", storage_state: str = None):
        self._config = self._load_config(config_path)
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._page: Optional[Page] = None
        self._recorder: Optional["SessionRecorder"] = None
        self._storage_state = storage_state

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
        try:
            self._playwright = sync_playwright().start()
        except Exception as exc:
            raise BrowserError(
                "Failed to start Playwright. Is it installed? "
                "Try: playwright install chromium"
            ) from exc
        bc = self._config.get("browser", {})
        try:
            self._browser = self._playwright.chromium.launch(
                headless=bc.get("headless", False),
                slow_mo=bc.get("slow_mo", 100),
            )
        except Exception as exc:
            self._playwright.stop()
            self._playwright = None
            raise BrowserError(
                f"Failed to launch Chromium: {exc}"
            ) from exc
        vp = bc.get("viewport", {"width": 1280, "height": 800})
        # Load storage state for auth persistence if provided
        ss = self._storage_state
        ss_data = load_auth_state(ss) if ss else None
        ctx = self._browser.new_context(viewport=vp, storage_state=ss_data or ss)
        self._page = ctx.new_page()
        if ss_data:
            logger.info("Auth state loaded from %s", ss)
        return self

    def stop(self):
        """Close the page and browser session."""
        errors = []
        if self._page:
            try:
                self._page.close()
            except Exception as exc:
                errors.append(f"page close: {exc}")
        if self._browser:
            try:
                self._browser.close()
            except Exception as exc:
                errors.append(f"browser close: {exc}")
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception as exc:
                errors.append(f"playwright stop: {exc}")
        self._page = None
        self._browser = None
        self._playwright = None
        if errors:
            logger.warning("Non-fatal errors during stop: %s", "; ".join(errors))

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------

    def save_auth_state(self, path: str) -> str:
        """Save the current storage state (cookies + localStorage) to *path*.

        Subsequent sessions can pass this file as ``storage_state`` to skip
        re-authentication.
        """
        from src.auth import save_auth_state
        return save_auth_state(self, path)

    def __enter__(self):
        return self.start()

    def __exit__(self, *args):
        self.stop()

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    @_retry()
    def go(self, url: str):
        """Navigate to *url* and wait for the page to load."""
        try:
            self._page.goto(url, wait_until="load")
        except PwTimeout as exc:
            raise NavigationError(
                f"Timed out navigating to {url!r}"
            ) from exc
        except Exception as exc:
            raise NavigationError(
                f"Failed to navigate to {url!r}: {exc}"
            ) from exc
        self._record_action("go", (url,))
        return self

    def refresh(self):
        try:
            self._page.reload(wait_until="load")
        except Exception as exc:
            raise NavigationError(f"Failed to refresh page: {exc}") from exc
        self._record_action("refresh")
        return self

    # ------------------------------------------------------------------
    # Element interaction
    # ------------------------------------------------------------------

    @_retry()
    def click(self, selector: str, *, timeout: int = None):
        """Click the first element matching *selector*."""
        try:
            self._page.click(selector, timeout=timeout or self._timeout())
        except PwTimeout as exc:
            raise ElementError(
                f"Timed out waiting for element {selector!r} to be clickable"
            ) from exc
        except Exception as exc:
            raise ElementError(
                f"Failed to click {selector!r}: {exc}"
            ) from exc
        self._record_action("click", (selector,), {"timeout": timeout})
        return self

    @_retry()
    def click_text(self, text: str, *, timeout: int = None):
        """Click an element by its visible text content (case-insensitive partial match)."""
        try:
            self._page.get_by_text(text, exact=False).first.click(
                timeout=timeout or self._timeout()
            )
        except PwTimeout as exc:
            raise ElementError(
                f"Timed out waiting for element with text {text!r}"
            ) from exc
        except Exception as exc:
            raise ElementError(
                f"Failed to click text {text!r}: {exc}"
            ) from exc
        self._record_action("click_text", (text,), {"timeout": timeout})
        return self

    @_retry()
    def type_into(self, selector: str, text: str, *, clear: bool = True, timeout: int = None):
        """Type *text* into the element at *selector*."""
        try:
            el = self._page.locator(selector).first
            if clear:
                el.fill("")
            el.fill(text, timeout=timeout or self._timeout())
        except PwTimeout as exc:
            raise ElementError(
                f"Timed out waiting for element {selector!r} to accept input"
            ) from exc
        except Exception as exc:
            raise ElementError(
                f"Failed to type into {selector!r}: {exc}"
            ) from exc
        self._record_action("type_into", (selector, text), {"clear": clear, "timeout": timeout})
        return self

    def press(self, key: str):
        """Press a keyboard key on the focused element (e.g. 'Enter', 'Tab')."""
        try:
            self._page.keyboard.press(key)
        except Exception as exc:
            raise ElementError(f"Failed to press key {key!r}: {exc}") from exc
        self._record_action("press", (key,))
        return self

    @_retry()
    def wait_for(self, selector: str, *, timeout: int = None, state: str = "visible"):
        """Wait for an element matching *selector* to appear."""
        try:
            self._page.wait_for_selector(selector, timeout=timeout or self._timeout(), state=state)
        except PwTimeout as exc:
            raise ElementError(
                f"Timed out waiting for {selector!r} (state={state})"
            ) from exc
        except Exception as exc:
            raise ElementError(
                f"Failed waiting for {selector!r}: {exc}"
            ) from exc
        self._record_action("wait_for", (selector,), {"timeout": timeout, "state": state})
        return self

    # ------------------------------------------------------------------
    # Reading the page
    # ------------------------------------------------------------------

    def text(self, selector: str) -> str:
        """Return the trimmed inner text of the first matching element."""
        try:
            return self._page.text_content(selector) or ""
        except Exception as exc:
            raise ElementError(f"Failed to read text from {selector!r}: {exc}") from exc

    def all_text(self, selector: str) -> list[str]:
        """Return inner text of every element matching *selector*."""
        try:
            return self._page.locator(selector).all_inner_texts()
        except Exception as exc:
            raise ElementError(f"Failed to read texts from {selector!r}: {exc}") from exc

    def page_text(self) -> str:
        """Return the visible text of the whole page."""
        try:
            return self._page.inner_text("body")
        except Exception as exc:
            raise ElementError(f"Failed to read page text: {exc}") from exc

    def count(self, selector: str) -> int:
        """Return how many elements match *selector*."""
        try:
            return self._page.locator(selector).count()
        except Exception as exc:
            raise ElementError(f"Failed to count {selector!r}: {exc}") from exc

    def exists(self, selector: str) -> bool:
        try:
            return self._page.locator(selector).count() > 0
        except Exception as exc:
            raise ElementError(f"Failed to check existence of {selector!r}: {exc}") from exc

    def screenshot(self, path: str = "screenshot.png"):
        """Save a screenshot of the current page."""
        try:
            self._page.screenshot(path=path, full_page=True)
        except Exception as exc:
            raise BrowserError(f"Failed to save screenshot to {path!r}: {exc}") from exc
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
        deadline = time.time() + (
            (timeout or self._timeout()) / 1000
        )
        interval = (
            poll_interval
            if poll_interval is not None
            else self._config.get("defaults", {}).get("poll_interval", 0.5)
        )

        last_text = ""
        stable_since = None

        while time.time() < deadline:
            try:
                el = self._page.locator(selector).first
                raw = el.text_content() or ""
            except Exception:
                raw = ""
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

    # -- Recording integration -----------------------------------------

    def set_recorder(self, recorder: Optional["SessionRecorder"] = None):
        """Attach a ``SessionRecorder`` so every bot method is auto-logged.

        Pass ``None`` to detach.
        """
        self._recorder = recorder

    def _record_action(self, method: str, args: tuple = (), kwargs: dict = None, result=None):
        """Log a method call to the attached recorder (if any)."""
        if self._recorder:
            self._recorder.record_action(method, args, kwargs or {}, result)


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
