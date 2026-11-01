# Qt widget ownership, worker threads and the garbage collector

A Qt object must be destroyed on the thread it lives in. Python's cyclic garbage collector runs on whichever thread happens to
allocate when a collection is due. If a widget is kept alive only by a reference cycle, the collector may destroy it on a
worker thread (a scan, an analysis, a report). The widget then leaves a timer registered with the GUI thread, and the next
`processEvents` crashes inside Qt (`QTimerInfoList::activateTimers`). It is a segmentation fault, not an exception.

`tools/qt_ownership_repro.py` shows it in thirty lines (`QT_QPA_PLATFORM=offscreen python tools/qt_ownership_repro.py`): a widget
without a parent, kept alive by a cycle and collected on a worker thread, ends the process every time; the same collection on
the GUI thread survives. It reproduces on Windows as well as on macOS.

## The rules the application follows

1. **Every widget has a parent.** The parent owns its lifetime, so it is Qt on the GUI thread that destroys it, never the
   collector. The main window is the root; pages are children of its stacked widget; every dialog is created with the window
   (or another dialog) as its parent and deletes itself when it closes (`Dialog` in `ui/dialogs.py`).
2. **Short-lived widgets are deleted with `deleteLater()`** (chips that are replaced, the days of the calendar), never dropped.
3. **Work on a pool thread never touches a widget.** `TaskRunner` (`ui/tasks.py`) runs `work(report)` on a `QThreadPool` thread
   and delivers `on_success` / `on_error` / `on_progress` through queued signals, so the callbacks run on the GUI thread.
   A callback that arrives after its dialog was closed checks `shiboken6.isValid` first.
4. **Shutdown is orderly.** `TaskRunner.close()` forgets the callbacks of tasks still running and waits for the pool; the window
   closes its runners before it goes away, and a runner that is destroyed gives back what its tasks had taken.
5. **A second layer, in case something slips through.** While any task runs, the cyclic collector is switched off (counted across
   runners, `PAUSE_GC` in `ui/tasks.py`) and the interpreter's switch interval is shortened (a Python-subclassed widget calls
   back into Python for every paint, so CPU-bound workers can otherwise starve the GUI thread of the GIL for seconds).

## How it is checked

* `tests/ui/test_ownership.py` builds the real window, opens its pages and dialogs, and asserts that no widget it created is
  without a parent.
* `tools/qt_gc_stress.py` drives the real window (scans, page changes, analyses, theme changes, and every dialog including the
  profile manager and the sample wizard) for many rounds while a thread calls `gc.collect()` continuously and the collector pause
  of rule 5 is **off**, so rule 1 has to hold on its own. The test runs it in a process of its own, because a violation ends the
  process; a second run adds a widget without a parent on purpose and must crash, which shows the stress would notice one.
* The test fixtures (`tests/ui/conftest.py`) keep the collector off while a test runs and collect on the GUI thread afterwards:
  the widgets a test builds by hand may have no parent. A green run is not evidence that the application follows the rules; the
  two tests above are.

## When you add a widget

Give it a parent in its constructor (or add it to a layout of a parent straight away), and never show a widget that has no
parent yet: a parentless `QLabel` shown before it is added becomes a top-level window for a moment, which also costs about
40 ms each (this was found in the first Qt build and is why `Card` creates its title with a parent).
