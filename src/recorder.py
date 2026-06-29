"""
recorder.py — Capture everything happening in a browser session.

Attach a ``SessionRecorder`` to a ``PageBot`` and it will:

- Record network HAR (all requests/responses with bodies)
- Capture console messages (log, warn, error, exception)
- Take screenshots and DOM snapshots on every action
- Build a structured timeline of events (actions, network, console, state)

All output is saved to a timestamped directory under ``recordings/``.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from playwright.sync_api import ConsoleMessage, Request, Response, Route

from src.exceptions import BrowserError
from src.timeline import (
    Timeline,
    TimelineEvent,
    action_event,
    console_event,
    exception_event,
    navigation_event,
    request_event,
    response_event,
    snapshot_event,
    state_event,
)

if TYPE_CHECKING:
    from src.browser import PageBot

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

#: Fields to redact from request bodies when recording (security).
REDACTED_FIELDS = {"password", "token", "secret", "api_key", "authorization", "cookie"}


# ------------------------------------------------------------------
# SessionRecorder
# ------------------------------------------------------------------

class SessionRecorder:
    """Records a browser session to disk.

    Usage::

        bot = PageBot()
        recorder = SessionRecorder(bot, record_dir="recordings/my-test")
        recorder.start()             # begins HAR + console capture
        bot.go(url)
        recorder.snapshot("loaded")
        bot.click_text("Start")
        recorder.snapshot("clicked_start")
        recorder.stop()              # finalises and saves everything
    """

    def __init__(
        self,
        bot: "PageBot",
        record_dir: str = None,
        *,
        capture_network: bool = True,
        capture_console: bool = True,
        capture_screenshots: bool = True,
        capture_dom: bool = True,
        max_body_bytes: int = 100_000,
    ):
        self._bot = bot
        self._record_dir = Path(record_dir or self._default_dir())
        self._capture_network = capture_network
        self._capture_console = capture_console
        self._capture_screenshots = capture_screenshots
        self._capture_dom = capture_dom
        self._max_body_bytes = max_body_bytes

        self._timeline: Timeline = Timeline()
        self._started: bool = False
        self._snapshot_counter: int = 0

        # Internal maps for matching requests to responses
        self._pending_requests: Dict[str, float] = {}  # url -> start_time

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self):
        """Begin recording: attach network and console listeners."""
        if self._started:
            return
        self._timeline.begin()
        self._record_dir.mkdir(parents=True, exist_ok=True)
        (self._record_dir / "snapshots").mkdir(exist_ok=True)
        if self._capture_dom:
            (self._record_dir / "dom").mkdir(exist_ok=True)

        page = self._bot.page

        # -- Network capture (HAR-style via route interception) --------
        if self._capture_network:
            page.on("request", self._on_request)
            page.on("response", self._on_response)
            page.on("requestfailed", self._on_request_failed)

        # -- Console capture -------------------------------------------
        if self._capture_console:
            page.on("console", self._on_console)
            page.on("pageerror", self._on_page_error)

        # -- Navigation lifecycle --------------------------------------
        page.on("framenavigated", self._on_frame_navigated)

        self._started = True
        logger.info("Recording started → %s", self._record_dir)

    def stop(self):
        """Finalise the recording and write all data to disk."""
        if not self._started:
            return

        page = self._bot.page

        # Detach all listeners
        if self._capture_network:
            page.remove_listener("request", self._on_request)
            page.remove_listener("response", self._on_response)
            page.remove_listener("requestfailed", self._on_request_failed)
        if self._capture_console:
            page.remove_listener("console", self._on_console)
            page.remove_listener("pageerror", self._on_page_error)
        page.remove_listener("framenavigated", self._on_frame_navigated)

        self._write_metadata()
        self._timeline.save(str(self._record_dir / "recording.jsonl"))
        self._started = False
        logger.info(
            "Recording saved → %s  (%d events)",
            self._record_dir,
            len(self._timeline.events),
        )

    # -- Snapshots -----------------------------------------------------

    def snapshot(self, label: str = ""):
        """Take a point-in-time capture: screenshot + DOM + page state."""
        if not self._started:
            return
        self._snapshot_counter += 1
        n = self._snapshot_counter
        screenshot_path = None
        dom_path = None
        page_title = ""
        page_url = ""

        try:
            page = self._bot.page
            page_title = page.title()
            page_url = page.url

            if self._capture_screenshots:
                sp = str(self._record_dir / "snapshots" / f"{n:04d}.png")
                page.screenshot(path=sp, full_page=True)
                screenshot_path = sp

            if self._capture_dom:
                dp = str(self._record_dir / "dom" / f"{n:04d}.html")
                html = page.content()
                with open(dp, "w") as f:
                    f.write(html)
                dom_path = dp
        except Exception as exc:
            logger.warning("Snapshot %d failed: %s", n, exc)

        self._timeline.push(
            snapshot_event(
                seq=0,
                timestamp=self._timeline.elapsed,
                label=label or f"snapshot-{n:04d}",
                screenshot_path=screenshot_path,
                dom_path=dom_path,
                page_title=page_title,
                page_url=page_url,
            )
        )

    def record_action(
        self,
        method: str,
        args: tuple = (),
        kwargs: dict = None,
        result: Any = None,
        error: str = None,
    ):
        """Log a bot method call to the timeline."""
        if not self._started:
            return
        self._timeline.push(
            action_event(
                seq=0,
                timestamp=self._timeline.elapsed,
                method=method,
                args=args,
                kwargs=kwargs,
                result=result,
                error=error,
            )
        )

    def record_state(
        self,
        selector: str = None,
        text: str = None,
        value: Any = None,
    ):
        """Log a polled page state point to the timeline."""
        if not self._started:
            return
        page = self._bot.page
        self._timeline.push(
            state_event(
                seq=0,
                timestamp=self._timeline.elapsed,
                selector=selector,
                text=text,
                value=value,
                page_url=page.url if page else None,
                page_title=page.title() if page else None,
            )
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def timeline(self) -> Timeline:
        return self._timeline

    @property
    def record_dir(self) -> Path:
        return self._record_dir

    # ------------------------------------------------------------------
    # Network event handlers (private)
    # ------------------------------------------------------------------

    def _on_request(self, request: Request):
        ts = self._timeline.elapsed
        self._pending_requests[request.url] = ts
        self._timeline.push(
            request_event(
                seq=0,
                timestamp=ts,
                method=request.method,
                url=request.url,
                headers=request.headers,
                post_data=self._redact_body(request.post_data),
                resource_type=request.resource_type,
            )
        )

    def _on_response(self, response: Response):
        ts = self._timeline.elapsed
        url = response.url
        start_ts = self._pending_requests.pop(url, ts)
        duration_ms = (ts - start_ts) * 1000 if start_ts else None

        body_preview = None
        try:
            body = response.body()
            body_preview = body[:self._max_body_bytes].decode("utf-8", errors="replace")
        except Exception:
            pass  # non-text body or body already consumed

        self._timeline.push(
            response_event(
                seq=0,
                timestamp=ts,
                url=url,
                status_code=response.status,
                status_text=response.status_text,
                headers=response.headers,
                body_preview=body_preview,
                duration_ms=duration_ms,
            )
        )

    def _on_request_failed(self, request: Request):
        url = request.url
        self._pending_requests.pop(url, None)
        ts = self._timeline.elapsed
        self._timeline.push(
            response_event(
                seq=0,
                timestamp=ts,
                url=url,
                status_code=0,
                status_text="FAILED",
                headers={},
                duration_ms=None,
            )
        )

    # -- Console event handlers ----------------------------------------

    def _on_console(self, msg: ConsoleMessage):
        self._timeline.push(
            console_event(
                seq=0,
                timestamp=self._timeline.elapsed,
                level=msg.type,
                text=msg.text,
                location=msg.location if hasattr(msg, "location") else None,
            )
        )

    def _on_page_error(self, exc):
        self._timeline.push(
            exception_event(
                seq=0,
                timestamp=self._timeline.elapsed,
                message=str(exc),
                stack=getattr(exc, "stack", None),
            )
        )

    # -- Navigation handler --------------------------------------------

    def _on_frame_navigated(self, frame):
        if frame.is_main():
            self._timeline.push(
                navigation_event(
                    seq=0,
                    timestamp=self._timeline.elapsed,
                    url=frame.url,
                    event_type="finish",
                )
            )

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _write_metadata(self):
        """Write recording.json with session metadata and summary."""
        page = self._bot.page
        meta = {
            "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "duration_seconds": round(self._timeline.elapsed, 3),
            "total_events": len(self._timeline.events),
            "snapshots": self._snapshot_counter,
            "url": page.url if page else None,
            "title": page.title() if page else None,
            "config": {
                "capture_network": self._capture_network,
                "capture_console": self._capture_console,
                "capture_screenshots": self._capture_screenshots,
                "capture_dom": self._capture_dom,
            },
        }
        with open(self._record_dir / "recording.json", "w") as f:
            json.dump(meta, f, indent=2, default=str)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _default_dir() -> str:
        ts = time.strftime("%Y%m%d_%H%M%S")
        return f"recordings/session_{ts}"

    @staticmethod
    def _redact_body(body: Optional[str]) -> Optional[str]:
        """Strip sensitive fields from a request body for safe storage."""
        if not body or len(body) > 100_000:
            return body[:100_000] + "…" if body and len(body) > 100_000 else body
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                for key in list(parsed.keys()):
                    if any(s in key.lower() for s in REDACTED_FIELDS):
                        parsed[key] = "***"
                return json.dumps(parsed)
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
        return body[:5000]


# ------------------------------------------------------------------
# Convenience
# ------------------------------------------------------------------

def load_recording(path: str) -> dict:
    """Load a recording's metadata and timeline from disk.

    Returns a dict with keys: *metadata*, *timeline* (``Timeline`` instance).
    """
    p = Path(path)
    if p.is_dir():
        meta_path = p / "recording.json"
        tl_path = p / "recording.jsonl"
    else:
        meta_path = p.parent / "recording.json"
        tl_path = p.parent / "recording.jsonl"

    metadata = {}
    if meta_path.exists():
        metadata = json.loads(meta_path.read_text())

    timeline = Timeline()
    if tl_path.exists():
        timeline = Timeline.load(str(tl_path))

    return {"metadata": metadata, "timeline": timeline, "path": str(p)}
