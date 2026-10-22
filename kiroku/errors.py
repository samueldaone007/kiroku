"""Errors raised by the Kiroku core.

These are intentionally plain exceptions so the core stays free of any web
framework. The web layer and the CLI translate them into friendly messages.
"""

from __future__ import annotations


class KirokuError(Exception):
    """Base class for all Kiroku errors."""


class ParseError(KirokuError):
    """Raised when the pasted text cannot be read as a git log."""


class TooManyCommitsError(KirokuError):
    """Raised when the input holds more commits than the configured limit."""

    def __init__(self, count: int, limit: int) -> None:
        self.count = count
        self.limit = limit
        super().__init__(
            "That is too many commits to process "
            f"({count} found, the limit is {limit}). "
            "Try a smaller range, for example between two closer tags."
        )
