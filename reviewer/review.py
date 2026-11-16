"""Prompt construction, response parsing, and report validation.

The LLM is asked for a strict JSON report. Its raw reply is then treated
as **untrusted input**:

* the JSON is extracted and parsed defensively;
* **every entry is validated** — it must contain ``issue``, ``line`` and
  ``suggestion`` with valid, non-empty values. Entries that fail are
  collected in a "flagged" list with the reason, never passed through
  silently;
* each surviving line number is **verified against the actual file**.
  When a line cannot be verified (out of range, or the quoted original
  code does not match that line), the issue is kept but its line is
  marked *approximate*, as the brief requires.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .models import Issue

REQUIRED_FIELDS = ("issue", "line", "suggestion")
VALID_CATEGORIES = ("bug", "pep8", "refactor")
VALID_SEVERITIES = ("high", "medium", "low")

REVIEW_PROMPT = """You are an expert Python code reviewer. Review the file
below for:
1. Bugs and logic errors
2. PEP 8 compliance problems
3. Refactoring opportunities

Return ONLY a JSON object in exactly this shape:
{{"issues": [
  {{"issue": "short description of the problem",
    "line": 12,
    "category": "bug" | "pep8" | "refactor",
    "severity": "high" | "medium" | "low",
    "suggestion": "how to fix it, in words",
    "original_code": "the exact offending line from the file",
    "suggested_code": "a replacement line, or empty string"}}
]}}

Rules:
- Report real problems only; do not invent issues.
- Line numbers refer to the numbered source below.
- If there are no problems, return {{"issues": []}}.

File: {filename}
```python
{numbered_source}
```
"""


def build_review_prompt(source: str, filename: str) -> str:
    """Build the structured review prompt with line-numbered source."""
    numbered = "\n".join(
        f"{i + 1:>4}: {line}" for i, line in enumerate(source.splitlines())
    )
    return REVIEW_PROMPT.format(filename=filename, numbered_source=numbered)


def extract_json(text: str) -> dict:
    """Extract the JSON object from an LLM reply.

    Handles plain JSON and JSON wrapped in Markdown code fences.

    Raises:
        ValueError: If no parseable JSON object is present.
    """
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    else:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("No JSON object found in the LLM response.")
        cleaned = cleaned[start : end + 1]
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM response was not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("LLM response JSON was not an object.")
    return data


@dataclass
class FlaggedEntry:
    """An LLM entry that failed validation, kept for transparency."""

    raw: object
    reason: str


@dataclass
class ReviewReport:
    """A validated review: clean issues plus anything that was flagged."""

    filename: str
    issues: list[Issue] = field(default_factory=list)
    flagged: list[FlaggedEntry] = field(default_factory=list)
    reviewer_name: str = ""

    def to_dict(self) -> dict:
        """Serialise the full report (issues + flagged entries)."""
        return {
            "file": self.filename,
            "reviewer": self.reviewer_name,
            "issues": [issue.to_dict() for issue in self.issues],
            "flagged_entries": [
                {"entry": entry.raw, "reason": entry.reason}
                for entry in self.flagged
            ],
        }


def validate_entries(
    raw_entries: object, source_lines: list[str]
) -> tuple[list[Issue], list[FlaggedEntry]]:
    """Validate raw LLM entries and verify their line numbers.

    An entry is valid only when ``issue``, ``line`` and ``suggestion``
    are all present with sensible, non-empty values. Line numbers are
    then checked against the real file; unverifiable ones are marked
    approximate rather than dropped or trusted blindly.
    """
    valid: list[Issue] = []
    flagged: list[FlaggedEntry] = []

    if not isinstance(raw_entries, list):
        flagged.append(
            FlaggedEntry(raw_entries, "'issues' was not a list.")
        )
        return valid, flagged

    for entry in raw_entries:
        if not isinstance(entry, dict):
            flagged.append(FlaggedEntry(entry, "Entry is not an object."))
            continue

        problem = _entry_problem(entry)
        if problem:
            flagged.append(FlaggedEntry(entry, problem))
            continue

        issue = Issue(
            issue=str(entry["issue"]).strip(),
            line=int(entry["line"]),
            suggestion=str(entry["suggestion"]).strip(),
            category=_clean_choice(entry.get("category"), VALID_CATEGORIES, "bug"),
            severity=_clean_choice(
                entry.get("severity"), VALID_SEVERITIES, "medium"
            ),
            original_code=str(entry.get("original_code", "")).strip(),
            suggested_code=str(entry.get("suggested_code", "")).strip(),
        )
        issue.line_approximate = not _line_verified(issue, source_lines)
        valid.append(issue)

    valid.sort(key=lambda i: i.line)
    return valid, flagged


def _entry_problem(entry: dict) -> str:
    """Return why an entry is invalid, or an empty string when it is fine."""
    for field_name in REQUIRED_FIELDS:
        if field_name not in entry:
            return f"Missing required field: '{field_name}'."
    if not str(entry["issue"]).strip():
        return "Field 'issue' is empty."
    if not str(entry["suggestion"]).strip():
        return "Field 'suggestion' is empty."
    try:
        line = int(entry["line"])
    except (TypeError, ValueError):
        return "Field 'line' is not a number."
    if line < 1:
        return "Field 'line' must be 1 or greater."
    return ""


def _clean_choice(value: object, allowed: tuple[str, ...], default: str) -> str:
    """Normalise an optional enum-like field from the LLM."""
    text = str(value or "").strip().lower()
    return text if text in allowed else default


def _line_verified(issue: Issue, source_lines: list[str]) -> bool:
    """Check an issue's line against the actual file.

    Verified when the line exists and — when the reviewer quoted the
    original code — that quote matches the line's content. Anything else
    is approximate.
    """
    if issue.line > len(source_lines):
        return False
    if issue.original_code:
        actual = source_lines[issue.line - 1].strip()
        if actual != issue.original_code.strip():
            return False
    return True
