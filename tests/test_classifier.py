from kiroku.classifier import classify
from kiroku.models import RawCommit


def c(subject="", body="", author="", hash_code="a1b2c3d"):
    return RawCommit(hash=hash_code, subject=subject, body=body, author=author)


def test_feat_with_scope_goes_to_added():
    parsed = classify(c("feat(auth): add login rate limiting"))
    assert parsed.section == "added"
    assert parsed.scope == "auth"
    assert parsed.type == "feat"
    assert parsed.description == "Add login rate limiting"


def test_fix_goes_to_fixed():
    parsed = classify(c("fix: crash when file is empty"))
    assert parsed.section == "fixed"
    assert parsed.description == "Crash when file is empty"


def test_feat_with_bang_goes_to_breaking():
    parsed = classify(c("feat!: remove v1 API"))
    assert parsed.section == "breaking"
    assert parsed.breaking is True


def test_breaking_change_footer_goes_to_breaking():
    body = "Some explanation.\n\nBREAKING CHANGE: the old REST endpoint is gone."
    parsed = classify(c("feat: switch to v2 API", body=body))
    assert parsed.section == "breaking"
    assert parsed.breaking is True
    assert parsed.breaking_notes == ["the old REST endpoint is gone."]


def test_dashed_breaking_change_footer():
    body = "BREAKING-CHANGE: json format changed"
    parsed = classify(c("fix: new json", body=body))
    assert parsed.section == "breaking"


def test_perf_and_refactor_go_to_changed():
    assert classify(c("perf: speed up parsing")).section == "changed"
    assert classify(c("refactor: split parser")).section == "changed"


def test_revert_goes_to_removed():
    parsed = classify(c("revert: remove feature flag"))
    assert parsed.section == "removed"


def test_hidden_types_go_to_maintenance():
    assert classify(c("docs: explain install")).section == "maintenance"
    assert classify(c("test: cover parsing")).section == "maintenance"
    assert classify(c("ci: add linter")).section == "maintenance"
    assert classify(c("chore: update deps")).section == "maintenance"


def test_security_keyword_wins_over_type():
    parsed = classify(c("fix: harden auth headers", body="security: rate limiting"))
    assert parsed.section == "security"


def test_cve_goes_to_security():
    assert classify(c("fix: prevent buffer overflow (CVE-2026-1234)")).section == "security"


def test_deprecate_goes_to_deprecated():
    parsed = classify(c("feat: mark old flag deprecated"))
    assert parsed.section == "deprecated"


def test_updated_stuff_needs_review_goes_to_other():
    parsed = classify(c("updated stuff"))
    assert parsed.section == "other"
    assert parsed.needs_review is True


def test_keyword_guessing():
    assert classify(c("add user export")).section == "added"
    assert classify(c("fixed a crash")).section == "fixed"
    assert classify(c("remove old widget")).section == "removed"
    assert classify(c("update footer")).section == "changed"
    assert classify(c("new landing page")).section == "added"
    assert classify(c("improve startup time")).section == "changed"


def test_ambiguous_word_not_matched():
    # "updated" is deliberately not in the keyword vocabulary
    assert classify(c("updated logic")).section == "other"
    assert classify(c("removed config")).section == "other"


def test_references_are_extracted():
    parsed = classify(c("fix: crash on import (#12)", body="Fixes #45"))
    assert parsed.references == [12, 45]


def test_merge_commit_is_noise():
    parsed = classify(c("Merge pull request #12 from other/branch"))
    assert parsed.is_noise is True
    assert parsed.noise_reason == "merge"


def test_wip_is_noise():
    assert classify(c("wip")).is_noise is True
    assert classify(c("wip on landing page")).is_noise is True


def test_typo_is_noise():
    assert classify(c("fix typo in header")).is_noise is True


def test_readme_update_is_noise():
    assert classify(c("update readme")).is_noise is True


def test_version_bump_is_noise():
    assert classify(c("bump version to 1.2")).is_noise is True


def test_dependabot_is_noise():
    parsed = classify(
        c("Bump lodash from 4.17.20 to 4.17.21 (#15)", author="dependabot[bot]")
    )
    assert parsed.is_noise is True
    assert parsed.noise_reason == "dependency bot"


def test_empty_subject_is_noise():
    assert classify(RawCommit(hash="abc1234", subject="")).is_noise is True


def test_author_email_is_stripped():
    parsed = classify(c("feat: add login", author="Jane Doe <jane@example.com>"))
    assert parsed.author == "Jane Doe"