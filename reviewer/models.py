"""Data model for one code-review issue."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class Issue:
    """A single validated review finding.

    Attributes:
        issue: Short description of the problem.
        line: Line number in the reviewed file (1-based).
        suggestion: How to fix it, in words.
        category: ``"bug"``, ``"pep8"`` or ``"refactor"``.
        severity: ``"high"``, ``"medium"`` or ``"low"``.
        line_approximate: ``True`` when the line number could not be
            verified against the actual file. LLM-reported line numbers
            are often slightly off, so the brief requires them to be
            marked "approximate" instead of presented as exact.
        original_code: The offending source line(s), when known.
        suggested_code: A proposed replacement, when the reviewer
            supplied one. It is only ever *shown* as a diff — applying
            it always requires the user's manual confirmation.
    """

    issue: str
    line: int
    suggestion: str
    category: str = "bug"
    severity: str = "medium"
    line_approximate: bool = False
    original_code: str = ""
    suggested_code: str = ""

    @property
    def line_label(self) -> str:
        """``"line 12"`` or ``"line 12 (approximate)"``."""
        if self.line_approximate:
            return f"line {self.line} (approximate)"
        return f"line {self.line}"

    def to_dict(self) -> dict:
        """Serialise the issue for the JSON report."""
        return asdict(self)
