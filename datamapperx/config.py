"""Application-wide constants. Edit here to rebrand or retarget the app."""

from __future__ import annotations

APP_TITLE = "DataMapperX"
APP_DEVELOPER_LINE = "Developed by MAN_TRAN8118@jabil.com"

# GitHub repository that publishes releases (owner/name). The auto-updater reads
# https://github.com/<repo>/releases/latest/download/latest.json
GITHUB_REPO = "anhmuoiut/DataMapperX"

# Keep blank by default. Change to "N/A" or "-" to make missing values visible
# in the exported Excel file.
MISSING_TEXT = ""

TEXT_FILE_EXTENSIONS = (".log", ".txt", ".csv")
EXCEL_FILE_EXTENSIONS = (".xlsx", ".xlsm")

DEFAULT_OUTPUT_FILE = "RawData.xlsx"
DEFAULT_EXPECTED_SAMPLES = "10"
DEFAULT_REPEATS = "3"

# Rows shown in the on-screen preview (the export always writes every row).
PREVIEW_ROW_LIMIT = 500

# Environment variable that relocates all user data (profiles, settings, log).
# Used by the tests so they never touch the real profile of the person running them.
DATA_DIR_ENV = "DATAMAPPERX_HOME"
