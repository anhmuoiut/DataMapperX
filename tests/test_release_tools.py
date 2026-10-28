"""Guards for the release pipeline: catch a forgotten changelog or a malformed version before tagging."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

from datamapperx._version import __version__
from datamapperx.updater import parse_manifest

ROOT = Path(__file__).resolve().parent.parent


def load_tool(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_version_is_plain_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__), "release tags are vMAJOR.MINOR.PATCH"


def test_current_version_has_release_notes():
    """The release workflow refuses to publish without these; fail here first, not at tag time."""
    notes = load_tool("make_manifest").changelog_section(__version__)
    assert notes, f"CHANGELOG.md needs a '## [{__version__}] - date' section"


def test_unknown_version_has_no_notes():
    assert load_tool("make_manifest").changelog_section("0.0.1") == ""


def test_manifest_round_trips_through_the_app_parser(tmp_path, monkeypatch):
    fake_exe = tmp_path / "DataMapperX.exe"
    fake_exe.write_bytes(b"MZ" + b"\x00" * 100)
    output = tmp_path / "latest.json"

    tool = load_tool("make_manifest")
    monkeypatch.setattr("sys.argv", ["make_manifest", str(fake_exe), str(output)])
    tool.main()

    info = parse_manifest(json.loads(output.read_text("utf-8")))
    assert info.version == __version__ and info.size == fake_exe.stat().st_size
    assert info.asset_url.endswith(f"/v{__version__}/DataMapperX.exe")
    assert info.notes


def test_manifest_tool_refuses_missing_notes(tmp_path, monkeypatch):
    fake_exe = tmp_path / "DataMapperX.exe"
    fake_exe.write_bytes(b"MZ")
    tool = load_tool("make_manifest")
    monkeypatch.setattr(tool, "__version__", "0.0.1")
    monkeypatch.setattr("sys.argv", ["make_manifest", str(fake_exe), str(tmp_path / "x.json")])
    with pytest.raises(SystemExit, match="no '## \\[0.0.1\\]' section"):
        tool.main()


def test_min_supported_file_is_valid():
    value = load_tool("make_manifest").min_supported()
    if value:
        from datamapperx.updater import parse_version

        parse_version(value)
