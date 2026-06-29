"""
timeline.py — Structured event model for recording and replaying browser sessions.

Every event in a recording is a ``TimelineEvent`` with a *kind* discriminator.
Events are written as JSONL lines in ``recording.json`` so they can be streamed
back without loading the whole file into memory.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


# ------------------------------------------------------------------
# Event enumerations
# ------------------------------------------------------------------

#: Discriminator values for TimelineEvent.kind
EVENT_KINDS = frozenset({
    "action",        # a bot method call (click, type, navigate …)
    "navigation",    # page navigation event (start / commit / finish)
    "request",       # outgoing HTTP request
    "response",      # incoming HTTP response
    "console",       # console.log / warn / error message
    "snapshot",      # a manual screenshot + DOM capture point
    "exception",     # uncaught JS exception on the page
    "state",         # a poll/snapshot of element text or page state
})


# ------------------------------------------------------------------
# Event data classes
# ------------------------------------------------------------------

@dataclass
class TimelineEvent:
    """A single event in the recording timeline.

    Fields
    ------
    timestamp : float
        ``time.monotonic()`` value (relative to session start).
    kind : str
        One of EVENT_KINDS.
    seq : int
        Monotonically-increasing sequence number (1-based).
    data : dict
        Kind-specific payload (see per-kind helpers below).
    """
    timestamp: float
    kind: str
    seq: int
    data: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)

    @classmethod
    def from_json(cls, line: str) -> "TimelineEvent":
        d = json.loads(line)
        return cls(**d)


# ------------------------------------------------------------------
# Factory helpers — each returns a TimelineEvent with the right *data* shape.
# ------------------------------------------------------------------

def action_event(
    seq: int,
    timestamp: float,
    method: str,
    args: tuple = (),
    kwargs: dict = None,
    result: Any = None,
    error: str = None,
) -> TimelineEvent:
    """Record that a bot method was called."""
    return TimelineEvent(
        timestamp=timestamp,
        kind="action",
        seq=seq,
        data={
            "method": method,
            "args": _safe(args),
            "kwargs": _safe(kwargs or {}),
            "result": _safe(result),
            "error": error,
        },
    )


def navigation_event(
    seq: int,
    timestamp: float,
    url: str,
    event_type: str,  # "start" | "commit" | "finish"
    status_code: int = None,
    error: str = None,
) -> TimelineEvent:
    """Record a page navigation lifecycle event."""
    return TimelineEvent(
        timestamp=timestamp,
        kind="navigation",
        seq=seq,
        data={
            "url": url,
            "event_type": event_type,
            "status_code": status_code,
            "error": error,
        },
    )


def request_event(
    seq: int,
    timestamp: float,
    method: str,
    url: str,
    headers: dict = None,
    post_data: str = None,
    resource_type: str = None,
) -> TimelineEvent:
    """Record an outgoing HTTP request."""
    return TimelineEvent(
        timestamp=timestamp,
        kind="request",
        seq=seq,
        data={
            "method": method,
            "url": url,
            "headers": _safe_headers(headers),
            "post_data": post_data[:5000] if post_data else None,
            "resource_type": resource_type,
        },
    )


def response_event(
    seq: int,
    timestamp: float,
    url: str,
    status_code: int,
    status_text: str = None,
    headers: dict = None,
    body_preview: str = None,
    duration_ms: float = None,
) -> TimelineEvent:
    """Record an incoming HTTP response."""
    return TimelineEvent(
        timestamp=timestamp,
        kind="response",
        seq=seq,
        data={
            "url": url,
            "status_code": status_code,
            "status_text": status_text,
            "headers": _safe_headers(headers),
            "body_preview": body_preview[:2000] if body_preview else None,
            "duration_ms": duration_ms,
        },
    )


def console_event(
    seq: int,
    timestamp: float,
    level: str,       # "log" | "warn" | "error" | "info" | "debug"
    text: str,
    location: dict = None,
) -> TimelineEvent:
    """Record a console message from the page."""
    return TimelineEvent(
        timestamp=timestamp,
        kind="console",
        seq=seq,
        data={
            "level": level,
            "text": text[:5000],
            "location": location,
        },
    )


def snapshot_event(
    seq: int,
    timestamp: float,
    label: str,
    screenshot_path: str = None,
    dom_path: str = None,
    page_title: str = None,
    page_url: str = None,
) -> TimelineEvent:
    """Record a manual snapshot point (screenshot + optional DOM capture)."""
    return TimelineEvent(
        timestamp=timestamp,
        kind="snapshot",
        seq=seq,
        data={
            "label": label,
            "screenshot_path": screenshot_path,
            "dom_path": dom_path,
            "page_title": page_title,
            "page_url": page_url,
        },
    )


def exception_event(
    seq: int,
    timestamp: float,
    message: str,
    stack: str = None,
    source: str = None,
    lineno: int = None,
) -> TimelineEvent:
    """Record an uncaught JS exception from the page."""
    return TimelineEvent(
        timestamp=timestamp,
        kind="exception",
        seq=seq,
        data={
            "message": message[:5000],
            "stack": stack[:5000] if stack else None,
            "source": source,
            "lineno": lineno,
        },
    )


def state_event(
    seq: int,
    timestamp: float,
    selector: str = None,
    text: str = None,
    value: Any = None,
    page_url: str = None,
    page_title: str = None,
) -> TimelineEvent:
    """Record a polled / observed page state."""
    return TimelineEvent(
        timestamp=timestamp,
        kind="state",
        seq=seq,
        data={
            "selector": selector,
            "text": text,
            "value": value,
            "page_url": page_url,
            "page_title": page_title,
        },
    )


# ------------------------------------------------------------------
# Timeline container
# ------------------------------------------------------------------

class Timeline:
    """Ordered collection of events backed by an in-memory list.

    Also supports writing to / reading from JSONL files for persistence.
    """

    def __init__(self):
        self._events: List[TimelineEvent] = []
        self._seq: int = 0
        self._start_time: float = 0.0

    # -- construction ---------------------------------------------------

    @property
    def events(self) -> List[TimelineEvent]:
        return list(self._events)

    @property
    def seq(self) -> int:
        return self._seq

    def begin(self, start_time: float = None):
        """Call when recording starts — resets seq and stores base time."""
        import time
        self._seq = 0
        self._events.clear()
        self._start_time = start_time or time.monotonic()

    def push(self, event: TimelineEvent):
        """Append an event, assigning its seq automatically."""
        self._seq += 1
        event.seq = self._seq
        self._events.append(event)

    @property
    def elapsed(self) -> float:
        """Seconds since ``begin()`` was called (monotonic)."""
        import time
        return time.monotonic() - self._start_time

    # -- query ----------------------------------------------------------

    def by_kind(self, kind: str) -> List[TimelineEvent]:
        return [e for e in self._events if e.kind == kind]

    def actions(self) -> List[TimelineEvent]:
        return self.by_kind("action")

    def requests(self) -> List[TimelineEvent]:
        return self.by_kind("request")

    def responses(self) -> List[TimelineEvent]:
        return self.by_kind("response")

    def console_messages(self) -> List[TimelineEvent]:
        return self.by_kind("console")

    def snapshots(self) -> List[TimelineEvent]:
        return self.by_kind("snapshot")

    def errors(self) -> List[TimelineEvent]:
        """All events that likely indicate a problem."""
        results: List[TimelineEvent] = []
        for e in self._events:
            if e.kind == "console" and e.data.get("level") in ("error", "assert"):
                results.append(e)
            elif e.kind == "exception":
                results.append(e)
            elif e.kind == "action" and e.data.get("error"):
                results.append(e)
            elif e.kind == "response" and (e.data.get("status_code", 200) or 0) >= 400:
                results.append(e)
        return results

    def search_requests(self, query: str) -> List[TimelineEvent]:
        """Find requests whose URL contains *query*."""
        return [
            e for e in self._events
            if e.kind == "request" and query in e.data.get("url", "")
        ]

    def search_responses(self, status: int = None, url_contains: str = None) -> List[TimelineEvent]:
        """Find responses filtered by status and/or URL."""
        results = self.responses()
        if status is not None:
            results = [e for e in results if e.data.get("status_code") == status]
        if url_contains:
            results = [e for e in results if url_contains in e.data.get("url", "")]
        return results

    # -- persistence ----------------------------------------------------

    def save(self, path: str):
        """Write all events as JSONL to *path*."""
        with open(path, "w") as f:
            for ev in self._events:
                f.write(ev.to_json() + "\n")

    @classmethod
    def load(cls, path: str) -> "Timeline":
        """Load events from a JSONL file."""
        tl = cls()
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    tl._events.append(TimelineEvent.from_json(line))
        # Reconstruct seq from the last event
        tl._seq = tl._events[-1].seq if tl._events else 0
        return tl

    # -- summary --------------------------------------------------------

    def summary(self) -> str:
        """Return a human-readable summary of the timeline."""
        if not self._events:
            return "(empty timeline)"
        lines = [
            f"Events:     {len(self._events)}",
            f"Actions:    {len(self.actions())}",
            f"Requests:   {len(self.requests())}",
            f"Responses:  {len(self.responses())}",
            f"Console:    {len(self.console_messages())}",
            f"Snapshots:  {len(self.snapshots())}",
            f"Errors:     {len(self.errors())}",
        ]
        return "\n".join(lines)

    def print_timeline(self, max_events: int = 50):
        """Pretty-print events to stdout."""
        for ev in self._events[:max_events]:
            print(f"  #{ev.seq:04d}  [{ev.kind:>10}]  {ev.data}")
        if len(self._events) > max_events:
            print(f"  … and {len(self._events) - max_events} more")


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _safe(value: Any) -> Any:
    """Convert a value to a JSON-safe representation."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, tuple):
        return [_safe(v) for v in value]
    if isinstance(value, list):
        return [_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _safe(v) for k, v in value.items()}
    if hasattr(value, "name"):  # enums, named objects
        return str(value)
    return str(value)


def _safe_headers(headers: dict = None) -> dict:
    """Return headers dict, omitting security-sensitive keys."""
    if not headers:
        return {}
    sensitive = {"authorization", "cookie", "set-cookie", "x-api-key", "token"}
    return {k: "***" if k.lower() in sensitive else v for k, v in headers.items()}
