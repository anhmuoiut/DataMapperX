"""Fixtures of the Qt tests: one headless QApplication, a fresh main window per test.

Qt runs on its ``offscreen`` platform, so no window opens and no keyboard focus is taken. Message boxes are replaced by
recorders (a real one would wait for a click), and the user's data folder is a temporary one.
"""
from __future__ import annotations

import gc
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from datamapperx.config import DATA_DIR_ENV
from datamapperx.settings import Settings
from datamapperx.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _gui_thread_owns_widgets():
    """A widget must be destroyed on the thread that owns it, and the cyclic collector runs on whichever thread allocates.
    The application parents every widget (test_ownership.py proves it); the widgets a test builds on its own may not, so
    nothing is collected while a test runs, and what it left behind is collected here, on the GUI thread, afterwards."""
    gc.collect()
    gc.disable()
    try:
        yield
    finally:
        gc.enable()
        gc.collect()


@pytest.fixture
def window(app, monkeypatch, tmp_path):
    """A main window that stays off the network, with message boxes recorded in ``window.shown`` and answered Yes."""
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path / "userdata"))
    shown: list[tuple[str, str]] = []
    for kind in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, kind, staticmethod(lambda parent, title, text, *a, _k=kind, **kw: shown.append((_k, text))))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    win = MainWindow(app, settings=Settings(theme="light", expected_samples="10", repeats="3"), background_checks=False)
    win.shown = shown  # type: ignore[attr-defined]
    win._ensure_page("review")  # the real window builds it a moment after the first paint (warm_up)
    win.show()
    app.processEvents()
    yield win
    win.close()
    win.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)  # processEvents() alone does not delete it: every
    app.processEvents()  # later theme change would re-style the windows of all earlier tests as well
