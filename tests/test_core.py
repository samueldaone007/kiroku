import pytest

import helpers

from datetime import date

from kiroku import Options, generate_release_notes, format_release_notes
from kiroku.errors import ParseError, TooManyCommitsError


def test_end_to_end_core():
    text = helpers.fielded_log(
        helpers.record("1111", "feat(auth): add login rate limiting"),
        helpers.record("2222", "fix: crash when file is empty"),
        helpers.record("3333", "feat!: remove v1 API"),
        helpers.record("4444", "feat: switch to v2 API", body="BREAKING CHANGE: old endpoints gone"),
        helpers.record("5555", "docs: explain install"),
        helpers.record("6666", "Merge pull request #12 from a/b"),
        helpers.record("7777", "wip"),
        helpers.record("8888", "bump version to 1.1"),
        helpers.record("9999", "Bump lodash from 1.0 to 2.0 (#5)", author="dependabot[bot]"),
        helpers.record("aaaa", "updated stuff"),
        helpers.record("bbbb", "fix: crash when file is empty"),
    )
    notes = generate_release_notes(text, Options(version="1.1.0", date="2026-10-11"))

    assert notes.stats.total == 11
    assert notes.stats.hidden == 4
    assert notes.stats.merged == 1
    assert notes.stats.needs_review == 1

    md = format_release_notes(notes)
    assert md.index("### Breaking changes") < md.index("### Added")
    assert "- Remove v1 API" in md
    assert "Add login rate limiting" in md
    assert "(#12)" not in md
    assert "Updated stuff" in md


def test_summary_sentence():
    notes = generate_release_notes(
        helpers.fielded_log(helpers.record("1", "feat: a")),
        Options(version="1.0.0"),
    )
    assert notes.stats.summary() == "1 commit"


def test_date_defaults_to_today():
    options = Options(version="9.9.9")
    assert options.date == date.today().isoformat()


def test_users_audience_hides_maintenance_end_to_end():
    text = helpers.fielded_log(
        helpers.record("1", "feat: add login"),
        helpers.record("2", "fix: crash"),
        helpers.record("3", "chore: update deps"),
        helpers.record("4", "ci: run tests"),
    )
    notes = generate_release_notes(text, Options(audience="users", version="1.0.0"))
    md = format_release_notes(notes)
    assert "chore" not in md
    assert "ci" not in md
    assert "Maintenance" not in md
    assert "Add login" in md
    assert "Crash" in md


def test_garbage_input_gives_friendly_error():
    with pytest.raises(ParseError) as exc_info:
        generate_release_notes("this is nonsense text", Options())
    assert "couldn't read" in str(exc_info.value).lower()


def test_too_many_commits_friendly_error():
    text = helpers.fielded_log(*[helpers.record(f"{i:04x}", "feat: x") for i in range(5001)])
    with pytest.raises(TooManyCommitsError):
        generate_release_notes(text, Options())


def test_invalid_options_rejected():
    with pytest.raises(ValueError):
        Options(audience="everyone")
    with pytest.raises(ValueError):
        Options(format="docx")