"""
Shared test fixtures and helpers.
"""

import json
import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_data_dir():
    """Yield a temporary directory that is cleaned up after the test."""
    d = tempfile.mkdtemp(prefix="ticket_test_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def sample_recording_dir(tmp_data_dir):
    """Create a minimal fake recording directory with metadata + timeline."""
    record_dir = tmp_data_dir / "test_recording"
    record_dir.mkdir(parents=True)

    metadata = {
        "created": "2025-04-01T12:00:00+0000",
        "duration_seconds": 12.5,
        "total_events": 10,
        "snapshots": 2,
        "url": "https://example.com/page",
        "title": "Test Page",
        "config": {
            "capture_network": True,
            "capture_console": True,
            "capture_screenshots": True,
            "capture_dom": True,
        },
    }
    (record_dir / "recording.json").write_text(json.dumps(metadata, indent=2))

    # Create a timeline file with various event types
    timeline_lines = [
        # seq=1: navigation start
        '{"timestamp": 0.0, "kind": "navigation", "seq": 1, "data": {"url": "https://example.com/page", "event_type": "start"}}',
        # seq=2: request
        '{"timestamp": 0.1, "kind": "request", "seq": 2, "data": {"method": "GET", "url": "https://example.com/page", "headers": {}, "resource_type": "document"}}',
        # seq=3: response
        '{"timestamp": 0.5, "kind": "response", "seq": 3, "data": {"url": "https://example.com/page", "status_code": 200, "headers": {}, "duration_ms": 400.0}}',
        # seq=4: navigation finish
        '{"timestamp": 0.5, "kind": "navigation", "seq": 4, "data": {"url": "https://example.com/page", "event_type": "finish"}}',
        # seq=5: action — go
        '{"timestamp": 0.0, "kind": "action", "seq": 5, "data": {"method": "go", "args": ["https://example.com/page"]}}',
        # seq=6: snapshot
        '{"timestamp": 0.6, "kind": "snapshot", "seq": 6, "data": {"label": "landing", "screenshot_path": "", "dom_path": "", "page_title": "Test Page", "page_url": "https://example.com/page"}}',
        # seq=7: action — click
        '{"timestamp": 1.0, "kind": "action", "seq": 7, "data": {"method": "click_text", "args": ["Start"]}}',
        # seq=8: request (XHR)
        '{"timestamp": 1.1, "kind": "request", "seq": 8, "data": {"method": "POST", "url": "https://example.com/api/submit", "headers": {}, "post_data": "{\\"action\\":\\"start\\"}", "resource_type": "xhr"}}',
        # seq=9: response 500
        '{"timestamp": 1.5, "kind": "response", "seq": 9, "data": {"url": "https://example.com/api/submit", "status_code": 500, "headers": {}, "duration_ms": 400.0}}',
        # seq=10: console error
        '{"timestamp": 1.6, "kind": "console", "seq": 10, "data": {"level": "error", "text": "API call failed: Internal Server Error"}}',
    ]
    (record_dir / "recording.jsonl").write_text("\n".join(timeline_lines) + "\n")

    # Screenshot/DOM dirs
    (record_dir / "snapshots").mkdir()
    (record_dir / "dom").mkdir()

    return record_dir


@pytest.fixture
def page_bot_mock(mocker):
    """Return a Mock for PageBot with common attributes pre-configured."""
    bot = mocker.MagicMock()
    bot._timeout.return_value = 15000
    bot._config = {
        "defaults": {"timeout": 15000, "poll_interval": 0.5},
        "browser": {"headless": True},
    }
    bot.page = mocker.MagicMock()
    bot.page.url = "https://example.com"
    bot.page.title.return_value = "Test Page"
    bot.page.content.return_value = "<html><body>Test</body></html>"
    return bot
