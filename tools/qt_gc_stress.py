"""Drive the real Qt window while the cyclic garbage collector runs on a worker thread, with the collector pause switched off.

The ownership rule (docs/qt-widget-ownership.md) says every widget has a parent, so Python's collector can never destroy
one on the wrong thread. This program shows it on the real application: scans, page changes, analyses, theme changes and
dialogs run for ``rounds`` rounds while a thread calls ``gc.collect()`` all the time. Any violation ends the process with a
segmentation fault, so run it in a process of its own (tests/test_qt_ownership.py does).

Usage: QT_QPA_PLATFORM=offscreen python tools/qt_gc_stress.py <log folder of the ICT_I3070 profile> [rounds] [control]

``control`` breaks the rule on purpose each round (a widget without a parent, kept alive by a reference cycle) and is
expected to crash: it shows that the stress would notice a violation.
"""
from __future__ import annotations

import gc
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def short_lived_widgets(window, pump) -> None:
    """Open and close the dialogs and other widgets that come and go, so the collector meets them too."""


def main(argv: list[str]) -> int:
    from PySide6.QtWidgets import QApplication

    from datamapperx.settings import Settings
    from datamapperx.ui_qt.main_window import ANALYSIS, REVIEW, SELECT, MainWindow

    folder, rounds = argv[1], int(argv[2]) if len(argv) > 2 else 15
    control = len(argv) > 3 and argv[3] == "control"
    app = QApplication.instance() or QApplication([])
    window = MainWindow(app, settings=Settings(theme="light", last_folder=folder, expected_samples="4", repeats="3"))
    window.tasks._pause_gc = False  # the second layer of defence is off: the ownership rule alone must hold
    window.profile_box.setCurrentText("ICT_I3070 Test Log")
    window.show()

    stop = threading.Event()

    def collect() -> None:
        while not stop.is_set():
            gc.collect()
            time.sleep(0.0003)

    collector = threading.Thread(target=collect, daemon=True)
    collector.start()

    def pump(condition=lambda: False, seconds: float = 30.0) -> None:
        end = time.time() + seconds
        while not condition() and time.time() < end:
            app.processEvents()
            time.sleep(0.001)
        if not condition() and seconds > 1:
            raise SystemExit("timed out")

    for _ in range(rounds):
        window.scan_logs()
        pump(lambda: not window._busy and window.scan_result is not None)
        window._add(["Alpha", "Beta"])
        for step in (REVIEW, ANALYSIS, SELECT):
            window._show_step(step)
            pump(seconds=0.02)
        window._show_step(ANALYSIS)
        window.analysis.run()
        pump(lambda: bool(window.analysis.results))
        for _ in range(len(window.analysis.results)):
            window.analysis.table.select_row(0)
            pump(seconds=0.02)
        window._toggle_theme()
        short_lived_widgets(window, pump)
        if control:
            from datamapperx.palette import LIGHT
            from datamapperx.ui_qt.widgets import ActionTable

            orphan = ActionTable(LIGHT, kind="add", name_heading="Component")  # nobody owns it but Python
            orphan.show()
            orphan._cycle = orphan  # only the cyclic collector can free it, on whichever thread runs it
            del orphan
            pump(seconds=0.05)
        window.clear_selected()
        window.scan_result = None
        pump(seconds=0.02)

    stop.set()
    collector.join()
    window.close()
    app.processEvents()
    print("survived", rounds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
