"""Read raw git log text and turn it into a list of RawCommit.

The recommended command prints fields separated by the ASCII unit and record
separators (0x1f and 0x1e), so multi-line commit bodies survive copy-paste:

    git log --pretty=format:'%H%x1f%s%x1f%b%x1f%an%x1f%ad%x1e' --date=short v1.0.0..v1.1.0

The parser also accepts plain ``git log --oneline`` output (hash + subject),
and anything with no separators at all is treated as "hash subject" lines.
If none of the lines look like commits, a ParseError is raised instead of
guessing.
"""

from __future__ import annotations

import re
from typing import List

from kiroku.errors import ParseError, TooManyCommitsError
from kiroku.models import RawCommit

FIELD_SEP = "\x1f"
RECORD_SEP = "\x1e"

_ONELINE_RE = re.compile(r"^([0-9a-fA-F]{7,40})\s+([^\n]*)$")

EMPTY_MESSAGE = "I couldn't read that. It looks empty. Did you run the command above?"
UNREADABLE_MESSAGE = (
    "I couldn't read that. Did you use the command above?\n"
    f"Please give me a pasted git log, not the raw command text."
)


def parse_git_log(text: str, *, max_commits: int = 5000) -> List[RawCommit]:
    """Parse pasted git log text into RawCommit objects.

    Raises ParseError if the text does not look like a git log, and
    TooManyCommitsError if there are more than ``max_commits`` commits.
    """
    if not text:
        raise ParseError(EMPTY_MESSAGE)

    text = text.replace("\r\n", "\n").replace("\r", "\n")

    if not text.strip():
        raise ParseError(EMPTY_MESSAGE)

    if RECORD_SEP in text and FIELD_SEP in text:
        commits = _parse_record_separated(text)
    elif FIELD_SEP in text:
        commits = _parse_field_separated_lines(text)
    else:
        commits = _parse_oneline(text)

    if not commits:
        raise ParseError(UNREADABLE_MESSAGE)

    if len(commits) > max_commits:
        raise TooManyCommitsError(len(commits), max_commits)

    return commits


# --------------------------------------------------------------------------- #
# Field + record separator format (the recommended command)
# --------------------------------------------------------------------------- #
def _parse_record_separated(text: str) -> List[RawCommit]:
    commits: List[RawCommit] = []
    for record in text.split(RECORD_SEP):
        record = record.strip("\n").strip()
        if not record:
            continue
        fields = record.split(FIELD_SEP)
        if len(fields) < 2:
            continue
        commits.append(
            RawCommit(
                hash=fields[0].strip(),
                subject=fields[1].strip(),
                body=fields[2].strip() if len(fields) > 2 else "",
                author=fields[3].strip() if len(fields) > 3 else "",
                date=fields[4].strip() if len(fields) > 4 else "",
            )
        )
    return commits


def _parse_field_separated_lines(text: str) -> List[RawCommit]:
    commits: List[RawCommit] = []
    for line in text.splitlines():
        if FIELD_SEP not in line:
            continue
        fields = line.split(FIELD_SEP)
        if len(fields) < 2:
            continue
        commits.append(
            RawCommit(
                hash=fields[0].strip(),
                subject=fields[1].strip(),
                body=fields[2].strip() if len(fields) > 2 else "",
                author=fields[3].strip() if len(fields) > 3 else "",
                date=fields[4].strip() if len(fields) > 4 else "",
            )
        )
    return commits


# --------------------------------------------------------------------------- #
# Plain "hash subject" lines, e.g. git log --oneline
# --------------------------------------------------------------------------- #
def _parse_oneline(text: str) -> List[RawCommit]:
    commits: List[RawCommit] = []
    for line in text.splitlines():
        line = line.rstrip("\n")
        if not line.strip():
            continue
        match = _ONELINE_RE.match(line)
        if match:
            commits.append(RawCommit(hash=match.group(1), subject=match.group(2).strip()))
        # lines without a hash are ignored if valid commits exist
    if not commits:
        raise ParseError(UNREADABLE_MESSAGE)
    return commits