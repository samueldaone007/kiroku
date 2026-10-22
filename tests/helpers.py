"""Helpers for building fake git log text in tests."""

FIELD_SEP = "\x1f"
RECORD_SEP = "\x1e"


def record(hash, subject="", body="", author="", date="2026-01-01"):
    """One record exactly as the recommended `git log ... %x1e` command prints."""
    return FIELD_SEP.join([hash, subject, body, author, date])


def fielded_log(*records):
    """Join records with the record separator (what git prints between commits)."""
    return RECORD_SEP.join(records)


def oneline_log(lines):
    """Build text in `git log --oneline` shape: `HASH SUBJECT` per line."""
    return "\n".join(lines) + "\n"