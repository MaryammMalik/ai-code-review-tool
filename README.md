# AI-Assisted Code Review Tool

Point it at any Python file and get a **validated, structured code review**: bug detection, PEP 8 compliance, and refactoring suggestions — as readable text or JSON.

> Elevvo Internship — Python Programming & AI Track · **Task 8: AI-Assisted Code Review Tool** (Module 9: AI-Assisted Coding & Debugging)

## What it does

1. Reads a Python file and sends it to an LLM with a structured prompt covering **bugs, PEP 8, and refactors** (the Module 8/9 pattern, using the OpenAI API).
2. Parses the reply into a **JSON report** where every issue has `issue`, `line`, and `suggestion` fields.
3. **Validates every single entry.** An entry with a missing or empty field is not passed through silently — it is moved to a *flagged* list with the reason, shown in the report and included in the JSON.
4. **Verifies every line number against the actual file.** LLM line numbers are often slightly off, so when a line can't be verified (out of range, or the quoted code doesn't match), the issue is kept but clearly marked **"line N (approximate)"**.
5. **Never applies changes on its own.** The tool reviews and reports — full stop. Fixes change the file only in `--interactive-diff` mode, one manual yes at a time.

### No API key? It still works.

Without `OPENAI_API_KEY`, the tool runs a built-in **offline static reviewer** (real AST-based checks: mutable default arguments, bare `except:`, `== None` comparisons, unused imports, missing docstrings) through the *same* validation pipeline. The report always names which reviewer produced it.

## Features

- Structured JSON report (`--json`) with issues **and** flagged entries
- Field-level validation of every LLM entry, with reasons for rejections
- Line-number verification with honest "approximate" marking
- Severity-sorted, readable terminal report
- **Bonus:** before/after **diff view** per fixable suggestion, applied only on manual accept
- A deliberately buggy sample file in `examples/` to try it on
- 18 pytest tests, including proof that a plain run never modifies the reviewed file

## Tech stack

- Python 3.10+ (standard library: `ast`, `json`, `difflib`, `argparse`)
- `openai` — LLM reviews when a key is configured
- `python-dotenv` — loading the key from `.env`
- `pytest` — tests

## Setup

```bash
git clone https://github.com/MaryammMalik/ai-code-review-tool.git
cd ai-code-review-tool
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Optional: enable LLM reviews

```bash
cp .env.example .env
# OPENAI_API_KEY=your_openai_api_key_here
```

## How to run

```bash
# Review the bundled buggy sample
python -m reviewer examples/buggy_sample.py

# Machine-readable report
python -m reviewer path/to/your_file.py --json

# Bonus: see diffs and accept/reject each fix yourself
python -m reviewer path/to/your_file.py --interactive-diff
```

## Example output

Real output reviewing the bundled sample (offline static reviewer):

```text
============================================================
Code review: buggy_sample.py  (reviewer: offline static checks)
============================================================

1. [HIGH] Mutable default argument in 'add_item' — the same object is
   shared across every call (bug, line 11)
   Suggestion: Use None as the default and create a new object
   inside the function.
   Code: def add_item(item, items=[]):

2. [MEDIUM] Bare 'except:' catches every exception, including
   KeyboardInterrupt and real bugs (bug, line 20)
   Suggestion: Catch a specific exception, e.g. 'except OSError:'…

8. [LOW] Comparison to None using '==' or '!=' (pep8, line 26)
   Suggestion: Use 'is None' / 'is not None'…

Summary: 9 valid issue(s), 0 flagged entries.
No changes were made to the file.
```

And the bonus diff flow — the fix is applied **only** because the user typed `y`:

```text
-def add_item(item, items=[]):
+def add_item(item, items=None):
Apply this fix? [y/N] y
Accepted.
```

## How to run the tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Project structure

```text
ai-code-review-tool/
├── reviewer/
│   ├── review.py    # Prompt, JSON extraction, entry validation, line checks
│   ├── llm.py       # OpenAI reviewer + offline AST static reviewer
│   ├── models.py    # Issue dataclass (issue / line / suggestion / …)
│   ├── differ.py    # Before/after diffs; apply only on manual accept
│   └── cli.py       # Command-line interface
├── examples/
│   └── buggy_sample.py   # Deliberately flawed file to review
└── tests/test_review.py
```

## What I learned

- That LLM output is **untrusted input**: well-formed JSON can still contain empty fields, wrong types, and invented line numbers — validation has to check meaning, not just syntax.
- How to design prompts that produce machine-readable structure (`response_format`, an exact schema, line-numbered source).
- Why "approximate" is the honest label for unverifiable data, and how much trust it preserves compared to presenting guesses as facts.
- The difference between a tool that *suggests* and a tool that *acts* — and why review tooling should stay on the suggesting side unless a human says yes.
