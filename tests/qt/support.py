"""Plain helpers of the Qt tests: waiting for the window, synthetic logs, scanning them."""
from __future__ import annotations

import time

from ..conftest import ict_block, write_ict_log


def pump(app, until=lambda: True, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if until():
            return
        time.sleep(0.003)
    raise AssertionError("timed out waiting for the window")


def make_logs(folder, sns=("VSE001", "VSE002", "VSE003"), repeats=2, components=("R1", "R2", "C1")):
    for sn in sns:
        for run in range(repeats):
            blocks = [ict_block(c, f"+{run + 1}.5E+00", "+9.0E+00", "+0.0E+00") for c in components]
            write_ict_log(folder / f"{sn}_{run + 1}.log", sn, blocks)
    return folder


def scan(app, win, folder, expected=3, repeats=2, profile="ICT_I3070 Test Log"):
    win.profile_box.setCurrentText(profile)
    win.folder_edit.setText(str(folder))
    win.expected_edit.setText(str(expected))
    win.repeats_edit.setText(str(repeats))
    win.scan_logs()
    pump(app, lambda: not win.is_busy and win.scan_result is not None)


def ready_to_review(app, win, folder, **kwargs):
    """Logs scanned and every component added, still on the first step."""
    folder.mkdir(exist_ok=True)
    make_logs(folder, **kwargs)
    scan(app, win, folder)
    win.add_all_shown()
