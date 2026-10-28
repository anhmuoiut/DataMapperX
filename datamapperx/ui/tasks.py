"""Run slow work off the UI thread and deliver the outcome back on it.

Tkinter is not thread-safe, so worker threads never touch widgets or call ``after()``.
They put messages on a queue and the main thread drains it on a short timer.
"""

from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

_POLL_MS = 40


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
