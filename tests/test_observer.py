"""
Tests for the observer module — CountdownWatcher, TextWatcher, wait_for_url_change.
"""

import time
from unittest.mock import MagicMock, PropertyMock

import pytest

from src.exceptions import TimeoutError as TicketTimeoutError
from src.observer import CountdownWatcher, TextWatcher, wait_for_url_change


# ==================================================================
# CountdownWatcher — parsing
# ==================================================================


@pytest.mark.parametrize("raw,expected", [
    # HH:MM:SS
    ("01:23:45", 5025),
    ("00:00:00", 0),
    ("99:59:59", 359999),
    # MM:SS
    ("05:30", 330),
    ("00:00", 0),
    ("59:59", 3599),
    # N seconds
    ("45 seconds", 45),
    ("0 seconds", 0),
    ("30 sec", 30),
    ("10 s", 10),
    ("1 second", 1),
    # N minutes
    ("5 minutes", 300),
    ("2 min", 120),
    ("1 m", 60),
    ("0 minutes", 0),
    # Trimmed / extra whitespace
    ("  00:05:00  ", 300),
    # Embedded in longer text
    ("Countdown: 00:02:30 remaining", 150),
    ("Time left: 01:00", 60),
])
def test_countdown_parse(raw, expected):
    assert CountdownWatcher._parse(raw) == expected


@pytest.mark.parametrize("raw", [
    "",
    "no numbers here",
    "abc:def",
])
def test_countdown_parse_invalid(raw):
    assert CountdownWatcher._parse(raw) is None


# ==================================================================
# CountdownWatcher — read & wait
# ==================================================================


def test_countdown_read(page_bot_mock):
    page_bot_mock.text.return_value = "00:05:00"
    cw = CountdownWatcher(page_bot_mock, "#timer")
    raw, secs = cw.read()
    assert raw == "00:05:00"
    assert secs == 300
    assert cw.raw_text == "00:05:00"
    assert cw.seconds == 300


def test_countdown_wait_until_target(page_bot_mock):
    """Simulate countdown ticking down from 3 to 0."""
    values = iter(["00:00:03", "00:00:02", "00:00:01", "00:00:00"])
    page_bot_mock.text.side_effect = values

    cw = CountdownWatcher(page_bot_mock, "#timer")
    raw, secs = cw.wait_until(target=0, timeout=5000, poll_interval=0.05)
    assert raw == "00:00:00"
    assert secs == 0


def test_countdown_wait_until_timeout(page_bot_mock):
    """Countdown stuck at the same value should time out."""
    page_bot_mock.text.return_value = "00:05:00"
    cw = CountdownWatcher(page_bot_mock, "#timer")
    with pytest.raises(TicketTimeoutError, match="never reached"):
        cw.wait_until(target=0, timeout=200, poll_interval=0.05)


def test_countdown_wait_until_changes(page_bot_mock):
    """Simulate countdown starting to tick."""
    values = iter(["00:05:00", "00:05:00", "00:04:59"])
    page_bot_mock.text.side_effect = values

    cw = CountdownWatcher(page_bot_mock, "#timer")
    raw, secs = cw.wait_until_changes(timeout=5000, poll_interval=0.05)
    assert secs < 300  # decreased


def test_countdown_wait_until_changes_stuck(page_bot_mock):
    """Countdown that never changes should time out."""
    page_bot_mock.text.return_value = "00:05:00"
    cw = CountdownWatcher(page_bot_mock, "#timer")
    with pytest.raises(TicketTimeoutError, match="never changed"):
        cw.wait_until_changes(timeout=200, poll_interval=0.05)


# ==================================================================
# TextWatcher
# ==================================================================


def test_text_watcher_until_contains(page_bot_mock):
    values = iter(["Loading...", "Loading...", "Done!"])
    page_bot_mock.text.side_effect = values
    tw = TextWatcher(page_bot_mock, "#status")
    val = tw.wait_until_contains("Done", timeout=5000, poll_interval=0.05)
    assert "Done" in val


def test_text_watcher_until_contains_timeout(page_bot_mock):
    page_bot_mock.text.return_value = "Loading..."
    tw = TextWatcher(page_bot_mock, "#status")
    with pytest.raises(TicketTimeoutError, match="never contained"):
        tw.wait_until_contains("Done", timeout=200, poll_interval=0.05)


def test_text_watcher_until_not_contains(page_bot_mock):
    values = iter(["Error: bad", "Error: bad", "OK"])
    page_bot_mock.text.side_effect = values
    tw = TextWatcher(page_bot_mock, "#status")
    val = tw.wait_until_not_contains("Error", timeout=5000, poll_interval=0.05)
    assert "Error" not in val


def test_text_watcher_until_not_contains_timeout(page_bot_mock):
    page_bot_mock.text.return_value = "Error: bad"
    tw = TextWatcher(page_bot_mock, "#status")
    with pytest.raises(TicketTimeoutError, match="never stopped"):
        tw.wait_until_not_contains("Error", timeout=200, poll_interval=0.05)


# ==================================================================
# wait_for_url_change
# ==================================================================


def test_wait_for_url_change(page_bot_mock):
    """Simulate page URL changing after a click."""
    from unittest.mock import PropertyMock
    type(page_bot_mock.page).url = PropertyMock(side_effect=["https://old.com", "https://old.com", "https://new.com"])
    new_url = wait_for_url_change(page_bot_mock, timeout=5000, poll_interval=0.05)
    assert new_url == "https://new.com"


def test_wait_for_url_change_timeout(page_bot_mock):
    type(page_bot_mock.page).url = PropertyMock(return_value="https://stuck.com")
    with pytest.raises(TicketTimeoutError, match="never changed"):
        wait_for_url_change(page_bot_mock, timeout=200, poll_interval=0.05)


def test_wait_for_url_change_skips_exceptions(page_bot_mock):
    """Should retry if accessing page.url raises temporarily."""
    calls = 0

    def url_side_effect():
        nonlocal calls
        calls += 1
        if calls <= 2:
            raise Exception("navigating...")
        return "https://new.com"

    type(page_bot_mock.page).url = PropertyMock(side_effect=url_side_effect)
    new_url = wait_for_url_change(page_bot_mock, timeout=5000, poll_interval=0.05)
    assert new_url == "https://new.com"
