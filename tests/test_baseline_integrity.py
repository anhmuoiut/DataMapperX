"""The baseline fixtures are what the application computed before the statistical modules were extended. They are never regenerated
to make a test pass.

The content of the committed files is pinned here by hash, so that a changed fixture fails a test in any checkout, with or without
Git history, and a deliberate change has to say so by updating the hashes with it. The Git blob hash is what ``git ls-files -s``
prints for the file (``git hash-object <file>`` computes it), so the pin can be checked against Git directly; the SHA-256 is for
a check without Git. Neither file contains a line break, so a checkout's line-ending conversion cannot change them.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

BASELINE = Path(__file__).parent / "fixtures" / "baseline"
PINNED = {
    "analyze_baseline.json": ("6fc414ea06f6f1d7ac9bac20e9874c8b1e1f2a95", "21351a87dbe4e577e635033c9e63686effc38715338dbc8e1ae704977ddbbc00"),
    "rawdata_baseline.json": ("66a0de9418030ab051f3099813653bbfa1d54c51", "721b45ac088139a10e3eba4d98fcb4ee2573d0e209c7296a84147b23957433ac"),
}


@pytest.mark.parametrize("name", sorted(PINNED))
def test_a_baseline_fixture_is_the_committed_one(name):
    data = (BASELINE / name).read_bytes()
    blob, sha256 = PINNED[name]
    assert hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest() == blob, f"{name} differs from the committed fixture (git blob)"
    assert hashlib.sha256(data).hexdigest() == sha256, f"{name} differs from the committed fixture (sha256)"


def test_no_baseline_fixture_is_missing_or_added():
    assert sorted(path.name for path in BASELINE.iterdir()) == sorted(PINNED)
