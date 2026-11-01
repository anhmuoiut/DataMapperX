"""Qt widget ownership on the real application (docs/qt-widget-ownership.md).

A QObject must be destroyed on the thread it lives in, and Python's cyclic collector runs on whichever thread allocates. So
every widget of the application has a parent, and the collector can then never destroy one on a worker thread. The first test
checks the rule on the real window; the others run it under stress in a process of their own, because a violation ends the
process with a segmentation fault: the window survives the collector running on a worker thread (with the collector pause of
the task runner switched off), and a deliberate violation does not, which shows the stress would notice one.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from datamapperx.settings import Settings
from datamapperx.ui.main_window import MainWindow

from ..conftest import ict_block, write_ict_log

ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def logs(tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    for s in range(4):
        for t in range(3):
            blocks = [ict_block("Alpha", f"{10 + s + t * 0.01:+.5E}", "+2.0E+01", "+0.0E+00"),
                      ict_block("Beta", f"{5 + s * 2 - t * 0.02:+.5E}", "+3.0E+01", "+0.0E+00")]
            write_ict_log(folder / f"S{s}_{t}.log", f"VSE{s:03d}", blocks)
    return folder


def test_every_widget_the_window_creates_has_a_parent(app, logs):
    before = set(app.allWidgets())
    window = MainWindow(app, settings=Settings(theme="light", last_folder=str(logs), expected_samples="4", repeats="3"),
                        background_checks=False)
    window.profile_box.setCurrentText("ICT_I3070 Test Log")
    window.show()
    window.scan_logs()
    end = time.time() + 15
    while (window.is_busy or window.scan_result is None) and time.time() < end:
        app.processEvents()
        time.sleep(0.002)
    window._add(["Alpha", "Beta"])
    window._show_step("review")
    window._show_workspace("validation")
    window.manage_profiles()
    window._show_about()
    window._show_shortcuts()
    app.processEvents()
    orphans = [w for w in set(app.allWidgets()) - before if w.parent() is None and w is not window]
    assert not orphans, f"widgets without a parent: {orphans}"
    window.close()


def stress(logs, *extra, timeout=240):
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "DATAMAPPERX_HOME": str(logs.parent / "home")}
    return subprocess.run([sys.executable, "-X", "faulthandler", str(ROOT / "tools" / "qt_gc_stress.py"), str(logs), *extra],
                          env=env, capture_output=True, text=True, timeout=timeout)


def test_the_window_survives_the_collector_running_on_a_worker_thread(logs):
    done = stress(logs, "8")
    assert done.returncode == 0 and "survived 8" in done.stdout, done.stderr[-2000:]


def test_the_stress_does_notice_a_widget_without_a_parent(logs):
    done = stress(logs, "40", "control")
    assert done.returncode != 0 and "survived" not in done.stdout
