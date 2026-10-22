"""Public API for Kiroku's core.

The function below is the single entry point used by the CLI (Step 2) and the
web layer (Step 3+): take raw pasted text plus options and get back a
ReleaseNotes object you can inspect, edit, or render to Markdown.

Example:
    notes = generate_release_notes(pasted_text, version="1.1.0")
    markdown = format_release_notes(notes)
"""

from __future__ import annotations

from kiroku.errors import ParseError, TooManyCommitsError
from kiroku.formatter import format_markdown, format_release_notes
from kiroku.grouper import build_release_notes, visible_sections
from kiroku.models import Options, ParsedCommit, ReleaseNotes
from kiroku.parser import parse_git_log

__all__ = [
    "ReleaseNotes",
    "Options",
    "ParsedCommit",
    "parse_git_log",
    "build_release_notes",
    "generate_release_notes",
    "format_markdown",
    "format_release_notes",
    "visible_sections",
    "ParseError",
    "TooManyCommitsError",
]


def generate_release_notes(text: str, options: Options) -> ReleaseNotes:
    """Parse, classify, group and return a ReleaseNotes for the pasted text."""
    commits = parse_git_log(text, max_commits=options.max_commits)
    return build_release_notes(commits, options)