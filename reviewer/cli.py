"""Command-line interface for the AI-Assisted Code Review Tool.

Usage:
    python -m reviewer path/to/file.py
    python -m reviewer path/to/file.py --json
    python -m reviewer path/to/file.py --interactive-diff

The tool **reviews and reports only**. It never modifies the reviewed
file unless you run it with ``--interactive-diff`` and manually accept
individual suggestions.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .differ import build_diff, is_fixable
from .llm import Reviewer, get_reviewer
from .review import ReviewReport, validate_entries

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def run_review(path: Path, reviewer: Reviewer) -> ReviewReport:
    """Review one file end to end: read → review → validate → report."""
    source = path.read_text(encoding="utf-8")
    raw_entries = reviewer.review(source, path.name)
    issues, flagged = validate_entries(raw_entries, source.splitlines())
    issues.sort(key=lambda i: (SEVERITY_ORDER.get(i.severity, 3), i.line))
    return ReviewReport(
        filename=path.name,
        issues=issues,
        flagged=flagged,
        reviewer_name=reviewer.name,
    )


def format_report(report: ReviewReport) -> str:
    """Render a report as readable terminal text."""
    lines = [
        "=" * 60,
        f"Code review: {report.filename}  (reviewer: {report.reviewer_name})",
        "=" * 60,
    ]
    if not report.issues:
        lines.append("No issues found. Nice and clean!")
    for i, issue in enumerate(report.issues, start=1):
        lines.append(
            f"\n{i}. [{issue.severity.upper()}] {issue.issue} "
            f"({issue.category}, {issue.line_label})"
        )
        lines.append(f"   Suggestion: {issue.suggestion}")
        if issue.original_code:
            lines.append(f"   Code: {issue.original_code}")
    if report.flagged:
        lines.append(
            f"\n⚠ {len(report.flagged)} entr"
            f"{'y was' if len(report.flagged) == 1 else 'ies were'} "
            "discarded for failing validation:"
        )
        for entry in report.flagged:
            lines.append(f"   - {entry.reason}")
    lines.append(
        f"\nSummary: {len(report.issues)} valid issue(s), "
        f"{len(report.flagged)} flagged entr"
        f"{'y' if len(report.flagged) == 1 else 'ies'}."
    )
    lines.append("No changes were made to the file.")
    return "\n".join(lines)


def interactive_diff(path: Path, report: ReviewReport) -> int:
    """Show before/after diffs and let the user accept or reject each.

    Only suggestions the user explicitly accepts are applied, and the
    file is written once at the end. Returns the number applied.
    """
    source = path.read_text(encoding="utf-8")
    source_lines = source.splitlines()
    fixable = [i for i in report.issues if is_fixable(i, source_lines)]
    if not fixable:
        print("\nNo suggestions with a concrete code fix to show.")
        return 0

    print(f"\n{len(fixable)} suggestion(s) have a concrete fix.")
    print("Review each diff — nothing is applied unless you accept it.")
    applied = 0
    current = source
    for issue in fixable:
        diff = build_diff(current, issue, path.name)
        if diff is None:
            continue
        print("\n" + "-" * 60)
        print(f"{issue.issue} ({issue.line_label})")
        print(diff)
        try:
            choice = input("Apply this fix? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if choice == "y":
            from .differ import apply_fix

            updated = apply_fix(current, issue)
            if updated is not None:
                current = updated
                applied += 1
                print("Accepted.")
            else:
                print("Could not apply safely — skipped.")
        else:
            print("Rejected.")

    if applied:
        path.write_text(current, encoding="utf-8")
        print(f"\nWrote {applied} accepted fix(es) to {path.name}.")
    else:
        print("\nNo fixes accepted — the file is unchanged.")
    return applied


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="code-review",
        description=(
            "Review a Python file with an LLM (or offline static checks) "
            "and print a validated, structured report."
        ),
    )
    parser.add_argument("file", help="Python file to review")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the report as JSON instead of text.",
    )
    parser.add_argument(
        "--interactive-diff",
        action="store_true",
        help=(
            "After the report, show before/after diffs and ask before "
            "applying each fix. Without this flag the file is NEVER "
            "modified."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI. Returns a process exit code."""
    args = build_parser().parse_args(argv)
    path = Path(args.file)
    if not path.is_file():
        print(f"Error: file not found: {path}", file=sys.stderr)
        return 1
    if path.suffix != ".py":
        print(f"Error: {path.name} is not a Python file.", file=sys.stderr)
        return 1

    reviewer = get_reviewer()
    try:
        report = run_review(path, reviewer)
    except Exception as exc:  # API failures, unreadable files, etc.
        print(f"Error: review failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_report(report))

    if args.interactive_diff and not args.json:
        interactive_diff(path, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
