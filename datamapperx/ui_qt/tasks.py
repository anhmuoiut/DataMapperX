"""Run slow work off the UI thread and deliver the outcome on it.

``run(work, on_success=..., on_error=..., on_progress=...)`` calls ``work(report)`` on a pool thread; ``report(*args)``
forwards progress to ``on_progress``. Results are delivered through queued signals, so the callbacks always run on the
UI thread and no widget is touched from a worker.

Safety, in layers (see ``docs/qt-widget-ownership.md``):

1. **Ownership.** A QObject must be destroyed on the thread it lives in. Python's cyclic collector runs on whichever thread
   allocates when a collection is due, so a widget that nothing owns but a reference cycle could be destroyed by a worker.
   Every widget of the application therefore has a parent (or is deleted with ``deleteLater``), which hands its lifetime to
   Qt and the GUI thread; ``tests/test_qt_ownership.py`` checks that rule on the real window and dialogs.
2. **Collector pause.** While any task runs, the cyclic collector is switched off (``pause_gc``), as the Tk version did, in
   case something outside the rule slips through. The stress test runs with this switched off to show layer 1 holds alone.
3. **Clean shutdown.** ``close()`` drops the callbacks of tasks still running and waits for the pool, so no worker delivers
   into a window that is being destroyed.

While tasks run, the interpreter's GIL switch interval is shortened (``FAST_SWITCH``). A Qt window calls back into Python
for every paint of a Python-subclassed widget, so with several CPU-bound worker threads it can wait on the GIL for
seconds at the default 5 ms; measured on a large scan, the longest UI stall fell from about 1.2 s to 0.3 s for a ~13%
slower scan. The previous interval is restored when the last task has been delivered.
"""

from __future__ import annotations

import gc
import itertools
import logging
import sys
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

logger = logging.getLogger(__name__)

FAST_SWITCH = 0.0005  # seconds; the default is 0.005


class _Signals(QObject):
    progress = Signal(int, object)
    done = Signal(int, object)
    failed = Signal(int, object)


class _Job(QRunnable):
    def __init__(self, job_id: int, work: Callable[[Callable[..., None]], Any], signals: _Signals) -> None:
        super().__init__()
        self._id, self._work, self._signals = job_id, work, signals

    def run(self) -> None:
        try:
            result = self._work(lambda *args: self._signals.progress.emit(self._id, args))
        except BaseException as exc:  # delivered to on_error, never lost on a worker thread
            self._emit(self._signals.failed, exc)
        else:
            self._emit(self._signals.done, result)

    def _emit(self, signal, payload) -> None:
        try:
            signal.emit(self._id, payload)
        except RuntimeError:  # the runner was deleted while the job ran (the application is closing)
            logger.debug("Result of task %s dropped: its runner is gone", self._id)


class TaskRunner(QObject):
    def __init__(self, parent: QObject | None = None, *, pause_gc: bool = True) -> None:
        super().__init__(parent)
        self._signals = _Signals(self)  # lives on the UI thread, so the connected slots below run there
        self._signals.progress.connect(self._deliver_progress)
        self._signals.done.connect(self._deliver_done)
        self._signals.failed.connect(self._deliver_failed)
        self._ids = itertools.count(1)
        self._callbacks: dict[int, tuple[Callable, Callable, Callable | None]] = {}
        self._pool = QThreadPool(self)
        self._saved_interval: float | None = None
        self._pause_gc, self._gc_was_enabled = pause_gc, False
        self._closed = False

    def run(self, work: Callable[[Callable[..., None]], Any], *, on_success: Callable[[Any], None],
            on_error: Callable[[BaseException], None], on_progress: Callable[..., None] | None = None) -> None:
        if self._closed:
            return
        job_id = next(self._ids)
        if not self._callbacks:
            self._saved_interval = sys.getswitchinterval()
            sys.setswitchinterval(FAST_SWITCH)
            if self._pause_gc:
                self._gc_was_enabled = gc.isenabled()
                gc.disable()
        self._callbacks[job_id] = (on_success, on_error, on_progress)
        self._pool.start(_Job(job_id, work, self._signals))

    @property
    def busy(self) -> bool:
        return bool(self._callbacks)

    def close(self, timeout_ms: int = 5000) -> bool:
        """Stop delivering, forget the tasks still running and wait for the pool. True when every worker has finished."""
        self._closed = True
        self._callbacks.clear()
        self._pool.clear()  # queued jobs that have not started
        finished = self._pool.waitForDone(timeout_ms)
        self._settle()
        return finished

    def _deliver_progress(self, job_id: int, args: tuple) -> None:
        callbacks = self._callbacks.get(job_id)
        if callbacks and callbacks[2]:
            callbacks[2](*args)

    def _deliver_done(self, job_id: int, result: Any) -> None:
        callbacks = self._callbacks.pop(job_id, None)
        try:
            if callbacks:
                callbacks[0](result)
        finally:
            self._settle()

    def _deliver_failed(self, job_id: int, exc: BaseException) -> None:
        callbacks = self._callbacks.pop(job_id, None)
        try:
            if callbacks:
                logger.error("Background task failed: %s", exc, exc_info=exc)
                callbacks[1](exc)
        finally:
            self._settle()

    def _settle(self) -> None:
        """When the last task is over, give back the GIL interval and the collector."""
        if self._callbacks:
            return
        if self._saved_interval is not None:
            sys.setswitchinterval(self._saved_interval)
            self._saved_interval = None
        if self._pause_gc and self._gc_was_enabled:
            gc.enable()
            self._gc_was_enabled = False
