from __future__ import annotations

import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("ci_annotate", Path(__file__).resolve().parent.parent / "tools" / "ci_annotate.py")
ci_annotate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ci_annotate)

OUTPUT = """\
............F..
=================================== FAILURES ===================================
___________________________ test_something_wide ___________________________
tests/ui/test_x.py:12: in test_something_wide
    assert width > 300
E   assert 120 > 300
E    +  where 120 = width()
=========================== short test summary info ============================
FAILED tests/ui/test_x.py::test_something_wide - assert 120 > 300
ERROR tests/ui/test_y.py::test_other - RuntimeError: boom
2 failed, 1493 passed in 154.02s
"""


def test_the_failed_tests_and_the_reasons_are_in_one_message():
    text = ci_annotate.summarise(OUTPUT)
    assert text.splitlines()[0] == "2 test(s) failed or could not run:"
    assert "FAILED tests/ui/test_x.py::test_something_wide - assert 120 > 300" in text and "ERROR tests/ui/test_y.py::test_other" in text
    assert "E   assert 120 > 300" in text and "where 120 = width()" in text


def test_the_message_is_escaped_for_a_workflow_command_and_kept_short(tmp_path, capsys):
    assert ci_annotate.escape("100%\nnext") == "100%25%0Anext"
    long = "FAILED t::a\n" + "E   " + "x" * 9000
    assert len(ci_annotate.summarise(long)) < 3600
    output = tmp_path / "pytest-output.txt"
    output.write_text(OUTPUT, encoding="utf-8")
    ci_annotate.main(["ci_annotate", str(output)])
    printed = capsys.readouterr().out.strip()
    assert printed.startswith("::error title=Tests failed::") and "\n" not in printed and "%0A" in printed


def test_a_missing_output_file_is_a_warning_not_a_crash(tmp_path, capsys):
    assert ci_annotate.main(["ci_annotate", str(tmp_path / "nothing.txt")]) == 0
    assert capsys.readouterr().out.startswith("::warning title=No test output::")
