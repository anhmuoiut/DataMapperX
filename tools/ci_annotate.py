"""Turn the output of a failed pytest run into one GitHub annotation, so that a failure is readable on the commit's checks page
(GitHub shows the log of a job only to people who are signed in).

usage (in the workflow, after the tests failed):  python tools/ci_annotate.py pytest-output.txt
"""
from __future__ import annotations

import sys
from pathlib import Path

MAX_CHARS = 3500
MAX_REASONS = 30


def escape(text: str) -> str:
    """The escaping that workflow commands need for a message: % and line breaks."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def summarise(output: str) -> str:
    """The tests that failed, then the first lines pytest gave as the reason (the ``E`` lines of the tracebacks)."""
    lines = output.splitlines()
    failed = [line.strip() for line in lines if line.startswith(("FAILED ", "ERROR "))]
    reasons = [line.rstrip() for line in lines if line.startswith("E  ")][:MAX_REASONS]
    result = [f"{len(failed)} test(s) failed or could not run:", *failed]
    if reasons:
        result += ["", "First reasons given:", *reasons]
    if not failed and not reasons:
        result += ["", "(no FAILED / ERROR lines in the output; the last lines were)", *lines[-15:]]
    text = "\n".join(result)
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + "\n..."


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else Path("pytest-output.txt")
    if not path.is_file():
        print(f"::warning title=No test output::{path} was not written (a step before the tests failed?)")
        return 0
    message = summarise(path.read_text(encoding="utf-8", errors="replace"))
    print(f"::error title=Tests failed::{escape(message)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
