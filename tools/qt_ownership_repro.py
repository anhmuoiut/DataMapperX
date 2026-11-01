"""Why a Qt widget must not be left to Python's garbage collector (docs/qt-widget-ownership.md): a minimal reproduction.

A widget without a parent belongs to Python. When only a reference cycle keeps it alive, the cyclic collector destroys it, on
whichever thread runs the collection. Qt requires a QObject to be destroyed on the thread it lives in; destroyed from a worker
thread it leaves a timer registered with the GUI thread, and the next ``processEvents`` crashes in
``QTimerInfoList::activateTimers``.

Usage: QT_QPA_PLATFORM=offscreen python tools/qt_ownership_repro.py [both|worker|main]      (needs PySide6, requirements-qt.txt)

  worker  the collection runs on a worker thread: the process is expected to be killed by SIGSEGV (exit code -11, or 139)
  main    the same collection on the GUI thread: expected to print "survived"
  both    runs the two, each in a process of its own, and prints their exit codes (the default)
"""
from __future__ import annotations

import gc
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUNDS = 40


def run(mode: str) -> None:
    sys.path.insert(0, str(ROOT))
    from PySide6.QtWidgets import QApplication

    from datamapperx.palette import LIGHT
    from datamapperx.ui.widgets import ActionTable

    app = QApplication.instance() or QApplication([])
    for _ in range(ROUNDS):
        table = ActionTable(LIGHT, kind="add", name_heading="Component")  # no parent: Python owns it
        table.show()
        app.processEvents()
        table._cycle = table  # a reference cycle: reference counting never frees it, only the cyclic collector can
        del table
        if mode == "worker":
            worker = threading.Thread(target=gc.collect)  # what a collection started by a worker thread's allocations does
            worker.start()
            while worker.is_alive():  # the GUI thread keeps running its event loop, as the window does while a scan runs
                app.processEvents()
                time.sleep(0.001)
        else:
            gc.collect()
        for _ in range(5):
            app.processEvents()
            time.sleep(0.002)
    print("survived", mode)


def main(argv: list[str]) -> int:
    choice = argv[1] if len(argv) > 1 else "both"
    if choice in ("worker", "main"):
        run(choice)
        return 0
    env = {**os.environ, "QT_QPA_PLATFORM": os.environ.get("QT_QPA_PLATFORM", "offscreen")}
    for mode in ("worker", "main"):
        try:
            done = subprocess.run([sys.executable, "-X", "faulthandler", __file__, mode], env=env, capture_output=True, text=True, timeout=120)
            print(f"{mode:7s} exit code {done.returncode:4d}  " + ("survived" if done.returncode == 0 else "crashed"))
        except subprocess.TimeoutExpired:
            print(f"{mode:7s} no answer within 120 s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
