"""Nothing of Tk is left: not in the source, the requirements or the packaging, and not loaded when the program's modules are imported."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TK_IMPORT = re.compile(r"^\s*(?:import|from)\s+(?:tkinter|_tkinter|turtle|sv_ttk|ttkthemes)\b", re.MULTILINE)


def python_files() -> list[Path]:
    return [*(ROOT / "datamapperx").rglob("*.py"), *(ROOT / "tools").glob("*.py"), ROOT / "main.py"]


def test_no_python_file_of_the_program_or_its_tools_imports_tk():
    offenders = [str(path.relative_to(ROOT)) for path in python_files() if TK_IMPORT.search(path.read_text(encoding="utf-8"))]
    assert offenders == []


def test_the_requirements_name_no_package_that_needs_tk():
    for name in ("requirements.txt", "requirements-dev.txt", "pyproject.toml"):
        text = (ROOT / name).read_text(encoding="utf-8").lower()
        assert "sv-ttk" not in text and "sv_ttk" not in text and "ttkthemes" not in text and "tkinter" not in text, name


def test_the_exe_is_built_without_tk_and_says_so_in_its_spec():
    spec = (ROOT / "DataMapperX.spec").read_text(encoding="utf-8")
    excludes = re.search(r"excludes=\[(.*?)\]", spec, re.DOTALL)
    assert excludes and "'tkinter'" in excludes.group(1) and "'_tkinter'" in excludes.group(1)
    assert "sv_ttk" not in spec and "tcl" not in spec.lower().replace("tcl/tk", "")  # no Tcl data files are collected either


def test_importing_every_module_of_the_program_loads_no_tk():
    code = (
        "import importlib, pkgutil, sys, datamapperx\n"
        "for module in pkgutil.walk_packages(datamapperx.__path__, 'datamapperx.'):\n"
        "    importlib.import_module(module.name)\n"
        "tk = sorted(name for name in sys.modules if name.split('.')[0] in ('tkinter', '_tkinter', 'sv_ttk', 'turtle'))\n"
        "print('TK:', tk)\n"
        "sys.exit(1 if tk else 0)\n"
    )
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": os.pathsep.join([str(ROOT), os.environ.get("PYTHONPATH", "")])}
    done = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120, cwd=str(ROOT))
    assert done.returncode == 0 and "TK: []" in done.stdout, done.stdout + done.stderr[-1500:]
