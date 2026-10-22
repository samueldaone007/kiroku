from kiroku.grouper import build_release_notes, visible_sections
from kiroku.models import Options, RawCommit


def commit(subject="", body="", author="", hash_code="a1b2c3d"):
    return RawCommit(hash=hash_code, subject=subject, body=body, author=author)


def release(commits, **options):
    return build_release_notes(commits, Options(**options))


def test_noise_hidden_by_default_and_shown_when_off():
    commits = [
        commit("Merge pull request #12 from x/y"),
        commit("feat: real feature one"),
        commit("wip"),
        commit("feat: real feature two"),
        commit("bump version to 1.2"),
        commit("Bump lodash from 1.0 to 1.1 (#5)", author="dependabot[bot]"),
    ]
    hidden = release(commits, hide_noise=True)
    assert hidden.stats.hidden == 4
    assert {e.raw_subject for e in hidden.entries} == {
        "feat: real feature one",
        "feat: real feature two",
    }

    shown = release(commits, hide_noise=False)
    assert shown.stats.hidden == 0
    assert shown.stats.shown == 6


def test_duplicate_messages_merged():
    commits = [
        commit("feat: add login"),
        commit("feat: add login"),
        commit("feat: other"),
    ]
    notes = release(commits)
    assert len(notes.entries) == 2
    assert notes.stats.merged == 1


def test_revert_cancels_matching_fix():
    commits = [
        commit("fix: crash when file is empty"),
        commit("revert: fix crash when file is empty"),
        commit("feat: add login"),
    ]
    notes = release(commits)
    subjects = {e.raw_subject for e in notes.entries}
    assert subjects == {"feat: add login"}
    assert notes.stats.merged == 1


def test_needs_review_count():
    commits = [
        commit("feat: clean feature"),
        commit("updated stuff"),
        commit("random vague text"),
    ]
    notes = release(commits)
    assert notes.stats.needs_review == 2


def test_visible_sections_filters_maintenance_for_users():
    commits = [
        commit("feat: add login"),
        commit("docs: explain install"),
        commit("chore: update deps"),
        commit("fix: crash"),
    ]
    notes = release(commits, audience="developers")
    keys = {s.key for s, _ in visible_sections(notes)}
    assert "maintenance" in keys

    notes = release(commits, audience="users")
    keys = {s.key for s, _ in visible_sections(notes)}
    assert keys == {"added", "fixed"}  # maintenance is gone for users


def test_section_order_breaking_first():
    commits = [
        commit("feat: add login"),
        commit("feat!: remove v1 API"),
        commit("fix: crash"),
    ]
    notes = release(commits)
    order = [s.key for s, _ in visible_sections(notes)]
    assert order.index("breaking") == 0


def test_group_by_scope_sorts_within_section():
    commits = [
        commit("feat(zzz): first"),
        commit("feat(aaa): second"),
        commit("feat: third"),
    ]
    notes = release(commits, group_by_scope=True)
    pairs = list(visible_sections(notes))
    assert [s.key for s, _ in pairs] == ["added"]
    added = next(entries for s, entries in pairs if s.key == "added")
    scopes = [(e.scope or "", e.raw_subject) for e in added]
    assert scopes == [
        ("", "feat: third"),
        ("aaa", "feat(aaa): second"),
        ("zzz", "feat(zzz): first"),
    ]