# Qt widget ownership, and the crash of the test suite

`tests/test_qt_prototype.py` builds Qt widgets and windows of the proof of concept (`datamapperx/ui_qt/`) on Qt's `offscreen` platform: no window opens. When that module ran inside a full test run it could end the whole process with a segmentation fault. This note records what was found, what was changed, and what is still a risk.

## Symptom

`python -m pytest tests --ignore=tests/test_ui.py` ended with `Fatal Python error: Segmentation fault` (exit code 139) during `test_the_analysis_page_shows_the_numbers_the_engine_computes`, in `QCoreApplication.processEvents`. It happened in 5 of 6 runs once enough other tests had run before it, and never when `tests/test_qt_prototype.py` was run alone, so it looked like a matter of test order.

## Cause

It is not a matter of order. It is a Qt rule broken by the way Python frees the objects of the tests.

* **Where it crashes.** The macOS crash report of the crashing process puts the fault in the main thread, in `QTimerInfoList::activateTimers()` called from `QEventDispatcherUNIX::processEvents`: a Qt timer fired for an object that no longer exists.
* **Who owns the widgets.** The tests create widgets without a parent (`ActionTable(...)`, `MainWindow(...)`); a widget without a parent belongs to Python. The widget, its model, its delegate and the connections of its signals refer to each other, so reference counting never frees them: only Python's cyclic garbage collector does.
* **On which thread the collector runs.** On the thread that happens to allocate when a collection is due. While a scan runs, that is often a pool thread. Logging the finalisation of these objects in the crashing configuration showed `ActionTable`, `TableModel` and `_ButtonDelegate` finalised by Python on `Dummy-4`, a `QThreadPool` thread, after a generation-0/1 collection that started on that thread (and a collection started on `scan_1`, the scanner's thread).
* **Why that crashes.** Qt requires a QObject to be destroyed on the thread it lives in. A widget destroyed on another thread cannot unregister its timers from the GUI thread's timer list, which keeps a pointer to freed memory; the next `processEvents` fires that timer.
* **Proof by a minimal program** (offscreen, no GUI): a parentless `ActionTable` kept alive only by a reference cycle, then destroyed by `gc.collect()` called on a worker thread while the main thread keeps running its event loop, ended in the same native crash (`QTimerInfoList::activateTimers`) in 6 runs of 6. The same table destroyed by `gc.collect()` on the main thread survived in every run. The program is `tools/qt_ownership_repro.py` (`QT_QPA_PLATFORM=offscreen python tools/qt_ownership_repro.py`); it still reproduces: on 2026-11-01 the worker-thread case ended with exit code -11 in 3 runs of 3 and the main-thread case with 0 in 3 of 3.

## What was changed

Only the tests, and only the Qt module: an autouse fixture in `tests/test_qt_prototype.py` collects garbage before each test, keeps the collector off while the test runs, and collects again, on the GUI thread, when the test is over. Nothing in `datamapperx/` changed, and no test was skipped or weakened.

| Run | Before | After |
|---|---|---|
| everything except the Tk GUI tests, separate processes | exit codes 0 139 139 139 139 139 | 20 of 20 exit 0 |
| `tests/test_qt_prototype.py` alone, separate processes | 6 of 6 exit 0 | 20 of 20 exit 0 |
| the same two, with the collector made to run very often | | 10 of 10 and 5 of 5 exit 0 |

A garbage collection after each test, without keeping it off during the test, also gave 3 of 3 passing runs. The fixture keeps it off because a collection on a pool thread in the middle of a test is exactly what was shown to crash.

## What is still a risk

* **The suite no longer shows the crash; the hazard is as real as before.** Measured again on 2026-11-01, with the tests added since: the whole non-GUI suite exits 0 in 8 runs of 8 with the fixture and also in 8 of 8 with it removed (a temporary copy of the Qt tests without it; the file in the repository is unchanged), and the Qt module alone exits 0 in 8 of 8. The crash depends on when a collection falls due and on which thread allocates then, so a different mix of tests changes whether it happens (it was 5 of 6 runs when it was found); the minimal program (`tools/qt_ownership_repro.py`) shows the mechanism every time. The fixture is kept because it makes the widgets of the tests die on the GUI thread at known points instead of whenever a collection comes due, not because the suite needs it today. It is a guard for the tests and no remedy for the code: a green run is no evidence that the code follows the ownership rule.

* **The migration plan assumed this away, and should not have.** `PYSide6_MIGRATION_PLAN.md` said that with `QThreadPool` "the GC workaround disappears" and listed deleting `ui/tasks.py`'s GC rule at cutover. It does not disappear: the rule that makes the Tk application safe has to be replaced by an ownership rule that the Qt code actually follows. The plan has been corrected (§2.1, §5.1, §5.2).
* **The prototype itself has the same exposure.** `datamapperx/ui_qt/tasks.py` states that Qt objects are never finalised by the collector on another thread. That holds only while every Qt object has a parent, or is deleted explicitly on the GUI thread. A widget without a parent that sits in a reference cycle can be destroyed by a collection started on a `TaskRunner` thread. Nothing in the prototype's own code was seen to do that, but nothing prevents it. Before the Qt port goes on (Phases 2 to 4), widgets should be given parents or deleted with `deleteLater()` on the GUI thread, and cycles through the widget should be avoided.
* **The fixture covers the garbage of a test, not what a test creates and drops in the middle of its run.** With the collector off during a test that is harmless (memory is released at the end of the test), but a future test that needs the collector would have to collect on the GUI thread itself.
* **Other platforms were not tried.** The investigation ran on macOS with PySide6 6.12. The failure mode (wrong-thread destruction) is general; whether it shows depends on the platform's event dispatcher.
* **The Tk application is not concerned**: it has no Qt object. It also already follows the rule that the Qt port should adopt: `datamapperx/ui/tasks.py` collects garbage on the main thread before the first background task starts, keeps the collector off while any task runs, and turns it on when the last one has been delivered. `datamapperx/ui_qt/tasks.py` does not do this.
