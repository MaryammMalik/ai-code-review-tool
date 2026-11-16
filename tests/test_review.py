"""Tests for the code review tool.

The behaviours under test are the ones the brief calls out: structured
JSON output, **validation of every entry**, "approximate" marking for
unverifiable line numbers, and the guarantee that the tool **never
modifies a file on its own**.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reviewer.cli import main, run_review
from reviewer.differ import apply_fix, build_diff, is_fixable
from reviewer.llm import StaticReviewer
from reviewer.models import Issue
from reviewer.review import extract_json, validate_entries

SOURCE = '''def add_item(item, items=[]):
    items.append(item)
    return items


def check(value):
    if value == None:
        return "missing"
    return "ok"
'''
SOURCE_LINES = SOURCE.splitlines()


def valid_entry(**overrides: object) -> dict:
    """A minimal entry that passes validation."""
    entry = {
        "issue": "Mutable default argument",
        "line": 1,
        "suggestion": "Use None as the default.",
        "original_code": "def add_item(item, items=[]):",
        "suggested_code": "def add_item(item, items=None):",
    }
    entry.update(overrides)
    return entry


# ----------------------------------------------------------------------
# JSON extraction
# ----------------------------------------------------------------------
def test_extract_json_plain_and_fenced() -> None:
    assert extract_json('{"issues": []}') == {"issues": []}
    fenced = 'Here you go:\n```json\n{"issues": [1]}\n```'
    assert extract_json(fenced) == {"issues": [1]}


def test_extract_json_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        extract_json("no json here at all")


# ----------------------------------------------------------------------
# Validation — the heart of Task 8
# ----------------------------------------------------------------------
def test_valid_entry_passes_and_verifies() -> None:
    valid, flagged = validate_entries([valid_entry()], SOURCE_LINES)
    assert len(valid) == 1
    assert flagged == []
    assert valid[0].line_approximate is False


def test_missing_field_is_flagged_not_passed_through() -> None:
    entry = valid_entry()
    del entry["suggestion"]
    valid, flagged = validate_entries([entry], SOURCE_LINES)
    assert valid == []
    assert len(flagged) == 1
    assert "suggestion" in flagged[0].reason


def test_empty_issue_is_flagged() -> None:
    valid, flagged = validate_entries(
        [valid_entry(issue="   ")], SOURCE_LINES
    )
    assert valid == []
    assert "empty" in flagged[0].reason


def test_non_numeric_line_is_flagged() -> None:
    valid, flagged = validate_entries(
        [valid_entry(line="soon")], SOURCE_LINES
    )
    assert valid == []
    assert "not a number" in flagged[0].reason


def test_non_dict_entry_is_flagged() -> None:
    valid, flagged = validate_entries(["just a string"], SOURCE_LINES)
    assert valid == []
    assert len(flagged) == 1


def test_unverifiable_line_is_marked_approximate() -> None:
    # Line 99 does not exist in an 8-line file.
    valid, _ = validate_entries([valid_entry(line=99)], SOURCE_LINES)
    assert len(valid) == 1
    assert valid[0].line_approximate is True
    assert valid[0].line_label == "line 99 (approximate)"


def test_mismatched_original_code_is_marked_approximate() -> None:
    entry = valid_entry(line=2, original_code="completely different code")
    valid, _ = validate_entries([entry], SOURCE_LINES)
    assert valid[0].line_approximate is True


def test_mixed_entries_are_separated() -> None:
    entries = [valid_entry(), valid_entry(issue=""), "junk", valid_entry(line=5)]
    valid, flagged = validate_entries(entries, SOURCE_LINES)
    assert len(valid) == 2
    assert len(flagged) == 2


# ----------------------------------------------------------------------
# Static reviewer (offline fallback) finds the planted problems
# ----------------------------------------------------------------------
def test_static_reviewer_finds_planted_bugs() -> None:
    reviewer = StaticReviewer()
    entries = reviewer.review(SOURCE, "sample.py")
    valid, flagged = validate_entries(entries, SOURCE_LINES)
    assert flagged == []
    texts = " ".join(i.issue for i in valid)
    assert "Mutable default" in texts
    assert "Comparison to None" in texts
    # AST line numbers are exact, so nothing may be approximate.
    assert all(not i.line_approximate for i in valid)


def test_static_reviewer_reports_syntax_errors() -> None:
    entries = StaticReviewer().review("def broken(:\n", "bad.py")
    assert len(entries) == 1
    assert "Syntax error" in entries[0]["issue"]


# ----------------------------------------------------------------------
# Diff bonus — shown, never auto-applied
# ----------------------------------------------------------------------
def test_diff_shows_before_and_after() -> None:
    issue = Issue(
        issue="Mutable default argument",
        line=1,
        suggestion="Use None as the default.",
        original_code="def add_item(item, items=[]):",
        suggested_code="def add_item(item, items=None):",
    )
    assert is_fixable(issue, SOURCE_LINES)
    diff = build_diff(SOURCE, issue, "sample.py")
    assert diff is not None
    assert "-def add_item(item, items=[]):" in diff
    assert "+def add_item(item, items=None):" in diff


def test_apply_fix_returns_new_source_only() -> None:
    issue = Issue(
        issue="Comparison to None",
        line=6,
        suggestion="Use 'is None'.",
        original_code="if value == None:",
        suggested_code="if value is None:",
    )
    updated = apply_fix(SOURCE, issue)
    assert updated is not None
    assert "if value is None:" in updated
    assert "if value == None:" in SOURCE  # original string untouched


# ----------------------------------------------------------------------
# CLI — a plain run must never modify the reviewed file
# ----------------------------------------------------------------------
def test_cli_review_does_not_modify_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "sample.py"
    target.write_text(SOURCE, encoding="utf-8")
    assert main([str(target)]) == 0
    out = capsys.readouterr().out
    assert "Mutable default" in out
    assert "No changes were made to the file." in out
    assert target.read_text(encoding="utf-8") == SOURCE


def test_cli_json_output_is_structured(tmp_path: Path, capsys) -> None:
    target = tmp_path / "sample.py"
    target.write_text(SOURCE, encoding="utf-8")
    assert main([str(target), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["file"] == "sample.py"
    assert all(
        {"issue", "line", "suggestion"} <= set(issue)
        for issue in data["issues"]
    )


def test_cli_missing_file_errors(tmp_path: Path) -> None:
    assert main([str(tmp_path / "nope.py")]) == 1


def test_run_review_sorts_by_severity() -> None:
    class FakeReviewer:
        name = "fake"

        def review(self, source: str, filename: str) -> list:
            return [
                valid_entry(issue="Low one", severity="low", line=6,
                            original_code="if value == None:"),
                valid_entry(issue="High one", severity="high"),
            ]

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "s.py"
        path.write_text(SOURCE, encoding="utf-8")
        report = run_review(path, FakeReviewer())
    assert [i.issue for i in report.issues] == ["High one", "Low one"]
