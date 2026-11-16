"""Before/after diffs for review suggestions (Task 8 bonus).

Safety rule, straight from the brief: **this tool never applies a change
on its own.** A diff is only ever *shown*; the file is written solely
when the user manually accepts a specific suggestion in interactive
mode.
"""

from __future__ import annotations

import difflib

from .models import Issue


def locate_line(issue: Issue, source_lines: list[str]) -> int | None:
    """Find the 0-based index of the line an issue refers to.

    Uses the issue's line when its content matches the quoted original
    code; otherwise falls back to a unique text match. Returns ``None``
    when the line cannot be located safely.
    """
    if not issue.original_code:
        return None
    target = issue.original_code.strip()
    if 1 <= issue.line <= len(source_lines):
        if source_lines[issue.line - 1].strip() == target:
            return issue.line - 1
    matches = [
        i for i, line in enumerate(source_lines) if line.strip() == target
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def is_fixable(issue: Issue, source_lines: list[str]) -> bool:
    """True when a concrete before/after replacement exists for an issue."""
    return bool(issue.suggested_code) and locate_line(issue, source_lines) is not None


def apply_fix(source: str, issue: Issue) -> str | None:
    """Return ``source`` with one issue's suggested replacement applied.

    The replacement preserves the original line's indentation. Returns
    ``None`` when the target line cannot be located safely — in that
    case nothing is changed.
    """
    lines = source.splitlines()
    index = locate_line(issue, lines)
    if index is None or not issue.suggested_code:
        return None
    original_line = lines[index]
    indent = original_line[: len(original_line) - len(original_line.lstrip())]
    lines[index] = indent + issue.suggested_code.strip()
    return "\n".join(lines) + ("\n" if source.endswith("\n") else "")


def build_diff(source: str, issue: Issue, filename: str) -> str | None:
    """Build a unified diff showing one suggestion's before/after.

    Returns ``None`` when the suggestion cannot be applied safely.
    """
    updated = apply_fix(source, issue)
    if updated is None:
        return None
    diff = difflib.unified_diff(
        source.splitlines(keepends=True),
        updated.splitlines(keepends=True),
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
    )
    return "".join(diff)
