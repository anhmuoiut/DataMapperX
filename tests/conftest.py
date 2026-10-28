"""Shared fixtures: synthetic ICT text logs and Function-Test Excel workbooks."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from openpyxl import Workbook

from datamapperx.config import DATA_DIR_ENV
from datamapperx.profiles import DEFAULT_PROFILES


@pytest.fixture(autouse=True)
def isolated_user_data(tmp_path_factory, monkeypatch):
    """Never let a test read or write the real user profile / settings."""
    home = tmp_path_factory.mktemp("userdata")
    monkeypatch.setenv(DATA_DIR_ENV, str(home))
    return home


@pytest.fixture
def ict_profile() -> dict:
    return copy.deepcopy(DEFAULT_PROFILES["ICT_I3070 Test Log"])


@pytest.fixture
def ft_profile() -> dict:
    return copy.deepcopy(DEFAULT_PROFILES["Function Test Log"])


def ict_block(component: str, measured: str, lim_max: str | None = None, lim_min: str | None = None,
              kind: str = "RES", blank_lines: int = 0) -> str:
    """One i3070 block: a {@BLOCK} header followed by its {@A-xxx} measurement line."""
    tail = f"{{@LIM2|{lim_max}|{lim_min}}}}}" if lim_max is not None else ""
    return f"{{@BLOCK|{component}|00|1\n" + "\n" * blank_lines + f"{{@A-{kind}|0|{measured}{tail}\n"


def write_ict_log(path: Path, sn: str, blocks: list[str]) -> Path:
    body = f"{{@BATCH|{sn}|board\n" + "".join(blocks)
    path.write_text(body, encoding="utf-8")
    return path


def write_ft_workbook(path: Path, sn: str | None, rows: list[tuple], sn_cell: str = "B2") -> Path:
    """Session sheet holds the SN; Results sheet columns: C=component, E=min, F=measured, G=max, H=unit."""
    wb = Workbook()
    session = wb.active
    session.title = "Session"
    session["A1"] = "Serial"
    if sn is not None:
        session[sn_cell] = sn
    results = wb.create_sheet("Results")
    results.append(["#", "x", "Component", "y", "Min", "Measured", "Max", "Unit"])
    for component, measured, lo, hi, unit in rows:
        results.append([None, None, component, None, lo, measured, hi, unit])
    wb.save(path)
    return path
