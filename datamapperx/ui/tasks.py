"""Run slow work off the UI thread and deliver the outcome back on it.

Tkinter is not thread-safe, so worker threads never touch widgets or call ``after()``.
They put messages on a queue and the main thread drains it on a short timer.

While tasks run, the cyclic garbage collector is paused. Python may otherwise run it on a worker thread, and it then
finalizes Tk objects (a ``tkinter.font.Font``) from that thread. Tk answers a call from another thread by waiting for
the main thread; with no main loop running that wait ends only after about a second, for every such object.
"""

from __future__ import annotations

import gc
import logging
import queue
import threading
import tkinter as tk
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

_POLL_MS = 40
_running = 0  # tasks on any runner; the collector comes back when the last one has been delivered
_lock = threading.Lock()


def _task_started() -> None:
    global _running
    with _lock:
        _running += 1
        if _running == 1:
            gc.collect()  # on the main thread, before any worker starts
            gc.disable()


def _task_finished() -> None:
    global _running
    with _lock:
        _running = max(0, _running - 1)
        if _running == 0:
            gc.enable()


class TaskRunner:
    def __init__(self, widget: tk.Misc) -> None:
        self._widget = widget
        self._queue: queue.Queue[tuple[Callable[..., Any] | None, tuple]] = queue.Queue()
        self._active = 0
        self._polling = False

    def run(
        self,
        work: Callable[[Callable[..., None]], Any],
        *,
        on_success: Callable[[Any], None],
        on_error: Callable[[BaseException], None],
        on_progress: Callable[..., None] | None = None,
    ) -> None:
        """Call ``work(report)`` on a thread. ``report(*args)`` forwards progress to ``on_progress``."""

        def report(*args: Any) -> None:
            if on_progress is not None:
                self._queue.put((on_progress, args))

        def target() -> None:
            try:
                result = work(report)
            except Exception as exc:  # delivered to the UI thread, never lost
                logger.debug("Background task failed", exc_info=True)
                self._queue.put((on_error, (exc,)))
            else:
                self._queue.put((on_success, (result,)))
            finally:
                self._queue.put((None, ()))  # marks completion

        self._active += 1
        _task_started()
        threading.Thread(target=target, daemon=True, name="dmx-task").start()
        self._ensure_polling()

    def _ensure_polling(self) -> None:
        if not self._polling:
            self._polling = True
            self._widget.after(_POLL_MS, self._drain)

    def _drain(self) -> None:
        try:
            while True:
                callback, args = self._queue.get_nowait()
                if callback is None:
                    self._active -= 1
                    _task_finished()
                    continue
                try:
                    callback(*args)
                except Exception:
                    logger.exception("Error in task callback")
        except queue.Empty:
            pass

        if self._active > 0 or not self._queue.empty():
            try:
                self._widget.after(_POLL_MS, self._drain)
            except tk.TclError:  # window destroyed while a task was still running
                self._polling = False
        else:
            self._polling = False
