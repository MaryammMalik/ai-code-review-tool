"""Reviewers: where raw review entries come from.

Two implementations share one interface and one validation pipeline:

* :class:`OpenAIReviewer` — sends the file to the OpenAI API with the
  structured prompt from :mod:`reviewer.review` (the Module 8/9 pattern).
* :class:`StaticReviewer` — an offline fallback that runs real AST-based
  checks locally. It exists so the tool can be run and tested end to end
  without an API key; its findings are genuine, and the active reviewer
  is always named in the report.

Both return *raw* entries. Nothing reaches the user until
:func:`reviewer.review.validate_entries` has validated every entry.
"""

from __future__ import annotations

import ast
import os
from typing import Protocol

from .review import build_review_prompt, extract_json

DEFAULT_MODEL = "gpt-4o-mini"


class Reviewer(Protocol):
    """Anything that can produce raw review entries for a source file."""

    name: str

    def review(self, source: str, filename: str) -> list:
        """Return the raw ``issues`` list for ``source``."""
        ...


class OpenAIReviewer:
    """Review code by sending it to the OpenAI chat API.

    Args:
        api_key: OpenAI API key (read from ``OPENAI_API_KEY`` if omitted).
        model: Chat model name; override with ``OPENAI_MODEL``.
    """

    name = "OpenAI"

    def __init__(
        self, api_key: str | None = None, model: str | None = None
    ) -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key or os.environ["OPENAI_API_KEY"])
        self._model = model or os.environ.get("OPENAI_MODEL", DEFAULT_MODEL)

    def review(self, source: str, filename: str) -> list:
        """Send the file to the LLM and return its raw issues list."""
        response = self._client.chat.completions.create(
            model=self._model,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert Python code reviewer. "
                        "Output ONLY valid JSON."
                    ),
                },
                {
                    "role": "user",
                    "content": build_review_prompt(source, filename),
                },
            ],
            temperature=0.2,
        )
        data = extract_json(response.choices[0].message.content or "")
        issues = data.get("issues")
        return issues if isinstance(issues, list) else []


class StaticReviewer:
    """Offline reviewer: real AST-based checks, no API key needed.

    Detects a focused set of genuine problems — mutable default
    arguments, bare ``except:`` blocks, ``== None`` comparisons, unused
    imports, and missing function docstrings — with exact line numbers
    taken from the AST, so its lines always verify.
    """

    name = "offline static checks (no API key set)"

    def review(self, source: str, filename: str) -> list:
        """Run the static checks and return raw issue entries."""
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            return [
                {
                    "issue": f"Syntax error: {exc.msg}",
                    "line": exc.lineno or 1,
                    "category": "bug",
                    "severity": "high",
                    "suggestion": "Fix the syntax error so the file can run.",
                    "original_code": (exc.text or "").strip(),
                    "suggested_code": "",
                }
            ]
        lines = source.splitlines()
        entries: list[dict] = []
        entries.extend(self._mutable_defaults(tree, lines))
        entries.extend(self._bare_excepts(tree, lines))
        entries.extend(self._none_comparisons(tree, lines))
        entries.extend(self._unused_imports(tree, lines))
        entries.extend(self._missing_docstrings(tree, lines))
        return entries

    # ------------------------------------------------------------------
    # Individual checks — each returns raw entries in the shared schema
    # ------------------------------------------------------------------
    @staticmethod
    def _line(lines: list[str], lineno: int) -> str:
        if 1 <= lineno <= len(lines):
            return lines[lineno - 1].strip()
        return ""

    def _mutable_defaults(self, tree: ast.AST, lines: list[str]) -> list[dict]:
        entries = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for default in node.args.defaults:
                if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                    original = self._line(lines, default.lineno)
                    suggested = ""
                    if isinstance(default, ast.List) and not default.elts:
                        suggested = original.replace("[]", "None", 1)
                    elif isinstance(default, ast.Dict) and not default.keys:
                        suggested = original.replace("{}", "None", 1)
                    entries.append(
                        {
                            "issue": (
                                f"Mutable default argument in "
                                f"'{node.name}' — the same object is "
                                "shared across every call"
                            ),
                            "line": default.lineno,
                            "category": "bug",
                            "severity": "high",
                            "suggestion": (
                                "Use None as the default and create a new "
                                "object inside the function."
                            ),
                            "original_code": original,
                            "suggested_code": suggested,
                        }
                    )
        return entries

    def _bare_excepts(self, tree: ast.AST, lines: list[str]) -> list[dict]:
        entries = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                original = self._line(lines, node.lineno)
                entries.append(
                    {
                        "issue": (
                            "Bare 'except:' catches every exception, "
                            "including KeyboardInterrupt and real bugs"
                        ),
                        "line": node.lineno,
                        "category": "bug",
                        "severity": "medium",
                        "suggestion": (
                            "Catch a specific exception, e.g. "
                            "'except OSError:' or 'except Exception:'."
                        ),
                        "original_code": original,
                        "suggested_code": original.replace(
                            "except:", "except Exception:", 1
                        ),
                    }
                )
        return entries

    def _none_comparisons(self, tree: ast.AST, lines: list[str]) -> list[dict]:
        entries = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            operands = [node.left, *node.comparators]
            has_none = any(
                isinstance(o, ast.Constant) and o.value is None
                for o in operands
            )
            has_equality = any(
                isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops
            )
            if has_none and has_equality:
                original = self._line(lines, node.lineno)
                suggested = original.replace("== None", "is None").replace(
                    "!= None", "is not None"
                )
                entries.append(
                    {
                        "issue": "Comparison to None using '==' or '!='",
                        "line": node.lineno,
                        "category": "pep8",
                        "severity": "low",
                        "suggestion": (
                            "Use 'is None' / 'is not None' — identity, "
                            "not equality, is the correct check for None "
                            "(PEP 8)."
                        ),
                        "original_code": original,
                        "suggested_code": suggested,
                    }
                )
        return entries

    def _unused_imports(self, tree: ast.AST, lines: list[str]) -> list[dict]:
        imported: dict[str, int] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name.split(".")[0]
                    imported[name] = node.lineno
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported[alias.asname or alias.name] = node.lineno
        used = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name)
        } | {
            node.value.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
        }
        entries = []
        for name, lineno in imported.items():
            if name not in used and name != "*":
                entries.append(
                    {
                        "issue": f"Unused import '{name}'",
                        "line": lineno,
                        "category": "refactor",
                        "severity": "low",
                        "suggestion": (
                            "Remove the unused import to keep the "
                            "module clean."
                        ),
                        "original_code": self._line(lines, lineno),
                        "suggested_code": "",
                    }
                )
        return entries

    def _missing_docstrings(self, tree: ast.AST, lines: list[str]) -> list[dict]:
        entries = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("_"):
                    continue
                if ast.get_docstring(node) is None:
                    entries.append(
                        {
                            "issue": (
                                f"Function '{node.name}' has no docstring"
                            ),
                            "line": node.lineno,
                            "category": "pep8",
                            "severity": "low",
                            "suggestion": (
                                "Add a short docstring explaining what "
                                "the function does, its arguments, and "
                                "what it returns."
                            ),
                            "original_code": self._line(lines, node.lineno),
                            "suggested_code": "",
                        }
                    )
        return entries


def get_reviewer() -> Reviewer:
    """Return the OpenAI reviewer when a key exists, else static checks."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    if os.environ.get("OPENAI_API_KEY", "").strip():
        return OpenAIReviewer()
    return StaticReviewer()
