from __future__ import annotations

import hashlib
import io
import json
import threading

import pytest

from datamapperx import updater
from datamapperx.updater import (
    UpdateCancelled,
    UpdateError,
    UpdateInfo,
    check_for_update,
    cleanup_update_leftovers,
    download_update,
    install_update,
    is_newer,
    parse_manifest,
    parse_version,
)

EXE_BYTES = b"MZ" + b"\x90" * 5000
GOOD = {
    "version": "1.3.0",
    "min_supported": "1.0.0",
    "sha256": hashlib.sha256(EXE_BYTES).hexdigest(),
    "size": len(EXE_BYTES),
    "notes": "- faster scan",
    "published_at": "2026-10-28T00:00:00Z",
}


# ----------------------------------------------------------------------------- versions
@pytest.mark.parametrize(
    ("text", "expected"),
    [("1.2.3", (1, 2, 3)), ("v2.0", (2, 0, 0)), ("V10", (10, 0, 0)), (" 1.2.3-beta1", (1, 2, 3))],
)
def test_parse_version(text, expected):
    assert parse_version(text) == expected


def test_parse_version_rejects_garbage():
    with pytest.raises(ValueError):
        parse_version("latest")


@pytest.mark.parametrize(
    ("candidate", "current", "newer"),
    [("1.10.0", "1.9.9", True), ("1.2.0", "1.2.0", False), ("1.1.9", "1.2.0", False), ("2.0.0", "1.99.99", True)],
)
def test_is_newer_compares_numerically_not_as_text(candidate, current, newer):
    assert is_newer(candidate, current) is newer


# ----------------------------------------------------------------------------- manifest
def test_manifest_builds_download_url_itself():
    info = parse_manifest({**GOOD, "asset_url": "https://evil.example/x.exe"})
    assert info.asset_url == "https://github.com/anhmuoiut/DataMapperX/releases/download/v1.3.0/DataMapperX.exe"
    assert info.version == "1.3.0" and info.sha256 == GOOD["sha256"]


def test_manifest_accepts_v_prefix_and_uppercase_hash():
    info = parse_manifest({**GOOD, "version": "v1.3.0", "sha256": GOOD["sha256"].upper()})
    assert info.version == "1.3.0" and info.sha256 == GOOD["sha256"]


@pytest.mark.parametrize(
    "broken",
    [
        {"version": "1.3.0"},
        {**GOOD, "sha256": "abc"},
        {**GOOD, "version": "soon"},
        {**GOOD, "asset": "../../evil.exe"},
        {**GOOD, "min_supported": "x"},
        [],
    ],
)
def test_manifest_rejects_invalid(broken):
    with pytest.raises(UpdateError):
        parse_manifest(broken)


def test_mandatory_when_below_min_supported():
    info = parse_manifest({**GOOD, "min_supported": "1.2.0"})
    assert info.is_mandatory_for("1.1.0") and not info.is_mandatory_for("1.2.0")
    assert not parse_manifest({**GOOD, "min_supported": ""}).is_mandatory_for("0.0.1")


# ----------------------------------------------------------------------------- network (faked)
class FakeResponse(io.BytesIO):
    def __init__(self, payload: bytes, url: str, length: int | None = None):
        super().__init__(payload)
        self._url = url
        self.headers = {"Content-Length": str(len(payload) if length is None else length)}

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def serve(monkeypatch, payload: bytes, final_url: str | None = None, length: int | None = None):
    def fake_urlopen(request, timeout=None):
        return FakeResponse(payload, final_url or request.full_url, length)

    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)


def test_check_returns_update_only_when_newer(monkeypatch):
    serve(monkeypatch, json.dumps(GOOD).encode())
    assert check_for_update("1.2.0").version == "1.3.0"
    assert check_for_update("1.3.0") is None
    assert check_for_update("2.0.0") is None


def test_check_reports_garbage_manifest(monkeypatch):
    serve(monkeypatch, b"<html>captive portal</html>")
    with pytest.raises(UpdateError, match="not valid JSON"):
        check_for_update("1.0.0")


def test_check_refuses_redirect_to_other_host(monkeypatch):
    serve(monkeypatch, json.dumps(GOOD).encode(), final_url="https://evil.example/latest.json")
    with pytest.raises(UpdateError, match="non-GitHub"):
        check_for_update("1.0.0")


def test_check_wraps_network_failure(monkeypatch):
    def boom(*_a, **_k):
        raise updater.urllib.error.URLError("no route")

    monkeypatch.setattr(updater.urllib.request, "urlopen", boom)
    with pytest.raises(UpdateError, match="Could not reach GitHub"):
        check_for_update("1.0.0")


def test_download_verifies_and_reports_progress(monkeypatch, tmp_path):
    serve(monkeypatch, EXE_BYTES)
    info = parse_manifest(GOOD)
    seen = []
    dest = tmp_path / "DataMapperX.exe.new"
    download_update(info, dest, progress=lambda done, total: seen.append((done, total)))
    assert dest.read_bytes() == EXE_BYTES
    assert seen[-1] == (len(EXE_BYTES), len(EXE_BYTES))


def test_download_rejects_tampered_file_and_deletes_it(monkeypatch, tmp_path):
    serve(monkeypatch, b"MZ" + b"\x00" * 5000)  # right size, wrong content
    dest = tmp_path / "x.new"
    with pytest.raises(UpdateError, match="SHA-256"):
        download_update(parse_manifest(GOOD), dest)
    assert not dest.exists()


def test_download_rejects_truncated_file(monkeypatch, tmp_path):
    serve(monkeypatch, EXE_BYTES[:100])
    dest = tmp_path / "x.new"
    with pytest.raises(UpdateError, match="incomplete"):
        download_update(parse_manifest(GOOD), dest)
    assert not dest.exists()


def test_download_rejects_non_executable(monkeypatch, tmp_path):
    html = b"<html>sign in to the corporate proxy</html>"
    serve(monkeypatch, html)
    info = parse_manifest({**GOOD, "sha256": hashlib.sha256(html).hexdigest(), "size": len(html)})
    with pytest.raises(UpdateError, match="not a Windows program"):
        download_update(info, tmp_path / "x.new")


def test_download_can_be_cancelled(monkeypatch, tmp_path):
    serve(monkeypatch, EXE_BYTES)
    cancel = threading.Event()
    cancel.set()
    dest = tmp_path / "x.new"
    with pytest.raises(UpdateCancelled):
        download_update(parse_manifest(GOOD), dest, cancel_event=cancel)
    assert not dest.exists()


# ----------------------------------------------------------------------------- install
def test_install_swaps_files_and_relaunches(tmp_path):
    target = tmp_path / "DataMapperX.exe"
    target.write_bytes(b"old version")
    new = tmp_path / "DataMapperX.exe.new"
    new.write_bytes(b"new version")
    launched = []

    install_update(new, target=target, relaunch=launched.append)

    assert target.read_bytes() == b"new version"
    assert (tmp_path / "DataMapperX.exe.old").read_bytes() == b"old version"
    assert not new.exists()
    assert launched == [target]


def test_install_replaces_stale_backup(tmp_path):
    target = tmp_path / "app.exe"
    target.write_bytes(b"v2")
    (tmp_path / "app.exe.old").write_bytes(b"v0 stale")
    new = tmp_path / "app.exe.new"
    new.write_bytes(b"v3")
    install_update(new, target=target, relaunch=None)
    assert target.read_bytes() == b"v3" and (tmp_path / "app.exe.old").read_bytes() == b"v2"


def test_install_rolls_back_when_new_file_cannot_be_moved(tmp_path, monkeypatch):
    target = tmp_path / "app.exe"
    target.write_bytes(b"working version")
    new = tmp_path / "app.exe.new"
    new.write_bytes(b"new")
    real_replace = updater.os.replace

    def flaky(src, dst):
        if str(src).endswith(".new"):
            raise PermissionError("antivirus has the file")
        return real_replace(src, dst)

    monkeypatch.setattr(updater.os, "replace", flaky)
    with pytest.raises(UpdateError, match="new version in place"):
        install_update(new, target=target, relaunch=None)
    assert target.read_bytes() == b"working version"


def test_install_requires_downloaded_file(tmp_path):
    target = tmp_path / "app.exe"
    target.write_bytes(b"x")
    with pytest.raises(UpdateError, match="missing"):
        install_update(tmp_path / "nope.new", target=target, relaunch=None)


def test_cleanup_removes_leftovers(tmp_path):
    exe = tmp_path / "app.exe"
    exe.write_bytes(b"x")
    (tmp_path / "app.exe.old").write_bytes(b"x")
    (tmp_path / "app.exe.new").write_bytes(b"x")
    cleanup_update_leftovers(exe)
    assert exe.exists() and not (tmp_path / "app.exe.old").exists() and not (tmp_path / "app.exe.new").exists()


def test_cannot_self_update_from_source_checkout():
    assert updater.can_self_update() is False


def test_update_info_is_immutable():
    info = parse_manifest(GOOD)
    assert isinstance(info, UpdateInfo)
    with pytest.raises(AttributeError):
        info.version = "9.9.9"  # type: ignore[misc]
