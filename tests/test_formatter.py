import helpers

from kiroku.formatter import format_markdown
from kiroku.models import Options, RawCommit
from kiroku.parser import parse_git_log
from kiroku.grouper import build_release_notes


def notes_for(*subjects, **options):
    text = helpers.oneline_log([f"{i:07x} {s}" for i, s in enumerate(subjects)])
    commits = parse_git_log(text)
    return build_release_notes(commits, Options(**options))


def test_developers_show_scope_hash_and_pr_links():
    notes = notes_for(
        "feat(auth): add login rate limiting (#12)",
        show_hashes=True,
        repo_url="https://github.com/owner/repo",
    )
    md = format_markdown(notes)
    assert "- Add login rate limiting ([#12](https://github.com/owner/repo/pull/12)) **(auth)** `0000000`" in md


def test_users_hide_scope_and_hashes():
    notes = notes_for(
        "feat(auth): add login rate limiting",
        "docs: explain install",
        audience="users",
        show_hashes=True,
    )
    md = format_markdown(notes)
    assert "**(auth)**" not in md
    assert "`0000000`" not in md
    assert "Maintenance" not in md


def test_breaking_changes_section_at_top():
    notes = notes_for("feat!: remove v1 API", "feat: add login")
    md = format_markdown(notes)
    assert md.index("### Breaking changes") < md.index("### Added")
    assert md.index("- Remove v1 API") < md.index("### Added")


def test_keep_a_changelog_header_and_compare_link():
    notes = notes_for(
        "feat: add login",
        version="1.1.0",
        date="2026-10-11",
        compare_url="https://github.com/owner/repo/compare/v1.0.0...v1.1.0",
    )
    md = format_markdown(notes)
    assert md.startswith("## [1.1.0] - 2026-10-11\n")
    assert "\n[1.1.0]: https://github.com/owner/repo/compare/v1.0.0...v1.1.0\n" in md


def test_github_release_format():
    notes = notes_for(
        "feat: add login",
        format="github-release",
        compare_url="https://example.com/compare",
        version="1.1.0",
    )
    md = format_markdown(notes)
    assert md.startswith("## What's Changed\n")
    assert "**Full Changelog**: https://example.com/compare" in md
    assert "## [1.1.0]" not in md


def test_plain_bullets_format_has_no_version_header():
    notes = notes_for("feat: add login", format="plain-bullets", version="1.1.0")
    md = format_markdown(notes)
    assert "## [1.1.0]" not in md
    assert "### Added" in md
    assert "- Add login" in md


def test_no_repo_means_no_links():
    notes = notes_for("feat: add login (#12)")
    md = format_markdown(notes)
    assert "(#12)" in md
    assert "](" not in md


def test_credit_contributors_shows_names_only():
    commits = [RawCommit(hash="a1b2c3d", subject="feat: add login", author="Jane Doe")]
    notes = build_release_notes(commits, Options(credit_contributors=True))
    md = format_markdown(notes)
    assert "(Jane Doe)" in md


def test_output_never_contains_emails():
    commits = [RawCommit(hash="a1b2c3d", subject="feat: add login", author="Jane Doe <jane@example.com>")]
    notes = build_release_notes(commits, Options(credit_contributors=True))
    md = format_markdown(notes)
    assert "jane@example.com" not in md
    assert "@" not in md