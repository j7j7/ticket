"""
Tests for the timeline module — event factories, Timeline container, serialization.
"""

import json
import tempfile
from pathlib import Path

import pytest

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


class TestTimelineEvent:
    """Basic event creation and serialization."""

    def test_roundtrip_json(self):
        ev = action_event(
            seq=0, timestamp=1.5,
            method="click", args=("#btn",),
            kwargs={"timeout": 5000}, result=None,
        )
        json_str = ev.to_json()
        restored = TimelineEvent.from_json(json_str)
        assert restored.kind == "action"
        assert restored.timestamp == 1.5
        assert restored.data["method"] == "click"
        assert restored.data["args"] == ["#btn"]

    def test_sensitive_headers_redacted(self):
        ev = response_event(
            seq=0, timestamp=1.0,
            url="https://api.example.com",
            status_code=200,
            headers={"authorization": "Bearer secret123", "content-type": "application/json"},
        )
        assert ev.data["headers"]["authorization"] == "***"
        assert ev.data["headers"]["content-type"] == "application/json"

    def test_body_preview_truncated(self):
        long_body = "x" * 3000
        ev = response_event(
            seq=0, timestamp=1.0,
            url="https://example.com",
            status_code=200,
            body_preview=long_body,
        )
        assert len(ev.data["body_preview"]) <= 2000


class TestEventFactories:
    """Verify each factory sets the correct kind and data shape."""

    def test_action_event(self):
        ev = action_event(seq=0, timestamp=0.0, method="go", args=("https://x.com",))
        assert ev.kind == "action"
        assert ev.data["method"] == "go"
        assert ev.data["args"] == ["https://x.com"]

    def test_navigation_event(self):
        ev = navigation_event(seq=0, timestamp=0.0, url="https://x.com", event_type="finish")
        assert ev.kind == "navigation"
        assert ev.data["url"] == "https://x.com"
        assert ev.data["event_type"] == "finish"

    def test_request_event(self):
        ev = request_event(seq=0, timestamp=0.0, method="POST", url="https://x.com/api")
        assert ev.kind == "request"
        assert ev.data["method"] == "POST"
        assert ev.data["post_data"] is None

    def test_response_event(self):
        ev = response_event(seq=0, timestamp=0.5, url="https://x.com", status_code=200,
                            duration_ms=300.0)
        assert ev.kind == "response"
        assert ev.data["status_code"] == 200
        assert ev.data["duration_ms"] == 300.0

    def test_console_event(self):
        ev = console_event(seq=0, timestamp=0.0, level="error", text="Something broke")
        assert ev.kind == "console"
        assert ev.data["level"] == "error"

    def test_exception_event(self):
        ev = exception_event(seq=0, timestamp=0.0, message="TypeError: x is not a function")
        assert ev.kind == "exception"

    def test_snapshot_event(self):
        ev = snapshot_event(seq=0, timestamp=1.0, label="loaded")
        assert ev.kind == "snapshot"
        assert ev.data["label"] == "loaded"

    def test_state_event(self):
        ev = state_event(seq=0, timestamp=2.0, selector="#timer", text="00:05:00")
        assert ev.kind == "state"
        assert ev.data["selector"] == "#timer"


class TestTimeline:
    """Timeline container operations."""

    def test_empty_timeline(self):
        tl = Timeline()
        assert len(tl.events) == 0
        assert tl.seq == 0

    def test_push_auto_sequences(self):
        tl = Timeline()
        tl.begin()
        tl.push(action_event(seq=0, timestamp=0.0, method="go", args=("https://x.com",)))
        tl.push(action_event(seq=0, timestamp=1.0, method="click", args=("#btn",)))
        assert len(tl.events) == 2
        assert tl.events[0].seq == 1
        assert tl.events[1].seq == 2

    def test_by_kind(self):
        tl = Timeline()
        tl.begin()
        tl.push(action_event(seq=0, timestamp=0.0, method="go", args=("https://x.com",)))
        tl.push(request_event(seq=0, timestamp=0.1, method="GET", url="https://x.com"))
        tl.push(response_event(seq=0, timestamp=0.5, url="https://x.com", status_code=200))
        tl.push(action_event(seq=0, timestamp=1.0, method="click", args=("#btn",)))

        assert len(tl.actions()) == 2
        assert len(tl.requests()) == 1
        assert len(tl.responses()) == 1

    def test_save_and_load(self, tmp_data_dir):
        tl = Timeline()
        tl.begin()
        tl.push(action_event(seq=0, timestamp=0.0, method="go", args=("https://x.com",)))
        tl.push(action_event(seq=0, timestamp=1.0, method="click", args=("#btn",)))

        path = tmp_data_dir / "timeline.jsonl"
        tl.save(str(path))
        assert path.exists()

        loaded = Timeline.load(str(path))
        assert len(loaded.events) == 2
        assert loaded.events[0].data["method"] == "go"
        assert loaded.seq == 2

    def test_errors_http_4xx(self):
        tl = Timeline()
        tl.begin()
        tl.push(response_event(seq=0, timestamp=0.5, url="https://x.com/404", status_code=404))
        tl.push(response_event(seq=0, timestamp=1.0, url="https://x.com/200", status_code=200))
        errs = tl.errors()
        assert len(errs) == 1
        assert errs[0].data["status_code"] == 404

    def test_errors_console_error(self):
        tl = Timeline()
        tl.begin()
        tl.push(console_event(seq=0, timestamp=0.0, level="error", text="oops"))
        assert len(tl.errors()) == 1

    def test_errors_console_warn_not_included(self):
        tl = Timeline()
        tl.begin()
        tl.push(console_event(seq=0, timestamp=0.0, level="warn", text="careful"))
        assert len(tl.errors()) == 0

    def test_search_requests(self):
        tl = Timeline()
        tl.begin()
        tl.push(request_event(seq=0, timestamp=0.0, method="GET", url="https://x.com/page"))
        tl.push(request_event(seq=0, timestamp=0.1, method="POST", url="https://x.com/api/login"))
        matches = tl.search_requests("/api/")
        assert len(matches) == 1

    def test_summary_string(self):
        tl = Timeline()
        tl.begin()
        tl.push(action_event(seq=0, timestamp=0.0, method="go", args=("https://x.com",)))
        summary = tl.summary()
        assert "Actions:" in summary
        assert "Events:" in summary
