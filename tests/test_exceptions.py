"""
Tests for the exception hierarchy.
"""

from src.exceptions import (
    BrowserError,
    ElementError,
    NavigationError,
    TicketError,
    TimeoutError,
)


class TestExceptions:
    """Verify the exception hierarchy and that each type is catchable by its parent."""

    def test_ticket_error_base(self):
        assert issubclass(BrowserError, TicketError)
        assert issubclass(ElementError, TicketError)
        assert issubclass(NavigationError, TicketError)
        assert issubclass(TimeoutError, TicketError)

    def test_browser_error_chain(self):
        assert issubclass(NavigationError, BrowserError)
        assert issubclass(ElementError, BrowserError)

    def test_raises_and_catches(self):
        """Verify that custom exceptions can be raised and caught by their parent."""
        try:
            raise NavigationError("Failed to navigate")
        except BrowserError as e:
            assert "Failed to navigate" in str(e)

    def test_timeout_error_separate(self):
        """TimeoutError is a TicketError but NOT a BrowserError."""
        assert issubclass(TimeoutError, TicketError)
        assert not issubclass(TimeoutError, BrowserError)

    def test_element_error_message(self):
        e = ElementError("Could not click #btn")
        assert "Could not click #btn" in str(e)
