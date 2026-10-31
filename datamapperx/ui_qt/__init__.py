"""Phase 1 proof of concept: the DataMapperX window rebuilt on PySide6 (Qt Widgets).

Run it with ``python -m datamapperx.ui_qt``. It is a vertical slice, not a replacement: it covers the Select and Review &
Export steps and a Validation & Reports preview (analysis, results table, charts), and reuses the scanner, exporter,
statistics, reports and settings unchanged. The tkinter application in ``datamapperx.ui`` is untouched and remains the
one that ships.
"""
