"""
ticket exception hierarchy.

All ticket-specific exceptions live here so consumers can catch them
without importing implementation modules.
"""


class TicketError(Exception):
    """Base for all ticket-raised exceptions."""


class BrowserError(TicketError):
    """Something went wrong launching or operating the browser."""


class NavigationError(BrowserError):
    """Page navigation failed (timeout, bad URL, crash)."""


class ElementError(BrowserError):
    """Could not find, interact with, or read a page element."""


class TimeoutError(TicketError):
    """A polling/wait operation exceeded its deadline."""
