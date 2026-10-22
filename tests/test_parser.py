import pytest

import helpers

from kiroku.errors import ParseError, TooManyCommitsError
from kiroku.parser import FIELD_SEP, RECORD_SEP, parse_git_log


def test_parses_recommended_fielded_format():
    body = "This is a multi-line\ncommit body."
    text = helpers.fielded_log(
        helpers.record("abc1234", "feat: add login", body, "Jane Doe", "2026-01-02"),
        helpers.record("def5678", "fix: crash", "", "Jane Doe", "2026-01-03"),
    )
    commits = parse_git_log(text)
    assert len(commits) == 2
    assert commits[0].hash == "abc1234"
    assert commits[0].subject == "feat: add login"
    assert commits[0].body == "This is a multi-line\ncommit body."
    assert commits[0].author == "Jane Doe"
    assert commits[0].date == "2026-01-02"
    assert commits[1].hash == "def5678"


def test_parses_oneline_format():
    text = helpers.oneline_log([
        "abc1234 feat: add login",
        "def5678 fix: crash",
        "feedbeef docs: update readme",
    ])
    commits = parse_git_log(text)
    assert [c.subject for c in commits] == [
        "feat: add login",
        "fix: crash",
        "docs: update readme",
    ]
    assert commits[2].hash == "feedbeef"


def test_handles_trailing_newline_and_crlf():
    text = helpers.fielded_log(helpers.record("abc1234", "feat: add login")).replace(RECORD_SEP, RECORD_SEP + "\r\n")
    commits = parse_git_log(f"{text}\r\n")
    assert len(commits) == 1
    assert commits[0].subject == "feat: add login"


def test_empty_input_raises_parse_error():
    with pytest.raises(ParseError):
        parse_git_log("")
    with pytest.raises(ParseError):
        parse_git_log("   \n   ")


def test_garbage_input_raises_friendly_parse_error():
    with pytest.raises(ParseError) as exc_info:
        parse_git_log("this is not a git log\njust random words")
    assert "couldn't read" in str(exc_info.value).lower()


def test_too_many_commits_raises():
    text = helpers.oneline_log([f"{i:07x} subject {i}" for i in range(5001)])
    with pytest.raises(TooManyCommitsError):
        parse_git_log(text, max_commits=5000)


def test_custom_max_commits_respected():
    text = helpers.oneline_log([f"{i:07x} subject {i}" for i in range(3)])
    assert len(parse_git_log(text, max_commits=3)) == 3


def test_ignores_blanks_and_missing_subjects_in_fielded_format():
    text = helpers.fielded_log(
        helpers.record("abc1234", "feat: one"),
        "",
        helpers.record("def5678", "feat: two"),
    )
    commits = parse_git_log(text)
    assert [c.subject for c in commits] == ["feat: one", "feat: two"]


def test_field_separator_is_required_detection():
    # a line that only has the field separator but no record separator
    text = "abc1234" + FIELD_SEP + "feat: one\n" + "def5678" + FIELD_SEP + "feat: two\n"
    commits = parse_git_log(text)
    assert [c.subject for c in commits] == ["feat: one", "feat: two"]