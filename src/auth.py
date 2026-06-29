"""
auth.py — Authentication support for ticket browser sessions.

Supports two flows:

**Manual login** — Open a visible browser, let the user log in, save the
browser's storage state (cookies + localStorage) to a JSON file. Subsequent
runs load that file so the session is already authenticated.

**Saved state** — Load a previously-saved storage state into the browser
context so the user appears already logged in.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.browser import PageBot

logger = logging.getLogger(__name__)

#: Filename used inside a recording directory for auth state.
AUTH_STATE_FILENAME = "auth_state.json"


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


def save_auth_state(bot: "PageBot", path: str) -> str:
    """Save the current browser's cookies + localStorage to *path*.

    Returns the absolute path written to.
    """
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        state = bot.page.context.storage_state()
    except Exception as exc:
        raise AuthError(f"Failed to capture storage state: {exc}") from exc

    p.write_text(json.dumps(state, indent=2, default=str))
    logger.info("Auth state saved → %s", p)
    return str(p)


def load_auth_state(path: str) -> dict:
    """Load a previously-saved storage state JSON file.

    Returns the deserialized dict suitable for passing to Playwright's
    ``browser.new_context(storage_state=...)``.
    """
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise AuthError(f"Auth state file not found: {p}")
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError as exc:
        raise AuthError(f"Invalid auth state file {p}: {exc}") from exc


def manual_login(
    bot: "PageBot",
    url: str,
    auth_state_path: str,
    *,
    instructions: str = None,
    timeout: int = 300,
) -> str:
    """Navigate to *url*, wait for the user to authenticate manually, then save state.

    The browser must be **visible** (headless=False) so the user can interact
    with the login page.

    Steps:
    1. Navigate to *url*
    2. Print instructions and wait for the user to press Enter
    3. Validate that the page context changed (URL or title differs from login page)
    4. Save storage state to *auth_state_path*

    Returns the absolute path to the saved auth state.
    """
    if not bot.page:
        raise AuthError("Bot has no active page. Call bot.start() first.")

    bot.go(url)
    print(f"\n  {'=' * 60}")
    print(f"  Manual login required")
    print(f"  {'=' * 60}")
    print(f"  URL:    {url}")
    print(f"  Title:  {bot.page.title()}")
    if instructions:
        print(f"  {instructions}")
    print(f"\n  Please log in manually in the browser window.")
    print(f"  I'll wait up to {timeout} seconds.")
    print(f"  {'=' * 60}")

    try:
        input("  Press Enter once you've logged in (or type 'skip' to save current state): ")
    except (EOFError, KeyboardInterrupt):
        print("\n  Aborted.")
        sys.exit(130)

    # Save whatever state we have after the user confirms
    result = save_auth_state(bot, auth_state_path)
    print(f"  Auth state saved → {result}")
    return result


def auth_state_in_recording(recording_dir: str) -> Optional[str]:
    """Return the path to auth_state.json inside a recording directory, if it exists."""
    p = Path(recording_dir) / AUTH_STATE_FILENAME
    return str(p) if p.exists() else None


# ------------------------------------------------------------------
# Exceptions
# ------------------------------------------------------------------


class AuthError(Exception):
    """Something went wrong during authentication."""
