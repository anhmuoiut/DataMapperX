"""The owner's off switch: reading status.json and deciding whether a copy may still run."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from datamapperx import access, updater
from datamapperx.settings import Settings, load_settings, save_settings
from datamapperx.updater import Status, UpdateError, fetch_status, parse_status

DAY = 24 * 60 * 60
NOW = 1_800_000_000.0


# ----------------------------------------------------------------------------- reading the file
def test_status_file_in_the_repository_is_valid():
    """Not that it is switched on: the owner will change it. Only that a slip in it would be caught here."""
    data = json.loads(Path(__file__).parent.parent.joinpath("status.json").read_text(encoding="utf-8"))
    assert isinstance(parse_status(data), Status)


def test_status_says_on_or_off():
    assert parse_status({"disabled": False}) == Status(False, "")
    assert parse_status({"disabled": True, "message": "  Use 1.3 instead.  "}) == Status(True, "Use 1.3 instead.")


@pytest.mark.parametrize(
    "broken",
    [
        [],
        "disabled",
        {},  # a typo such as {"disable": true} must not look like "everything is fine"
        {"disable": True},
        {"disabled": "true"},  # text is not a yes/no
        {"disabled": 1},
        {"disabled": None},
        {"disabled": True, "message": 5},
    ],
)
def test_unclear_status_is_an_error_never_a_verdict(broken):
    with pytest.raises(UpdateError):
        parse_status(broken)


def test_message_is_cleaned_and_shortened():
    status = parse_status({"disabled": True, "message": "Line 1\nLine 2\x00\x1b[31m" + "x" * 2000})
    assert status.message.startswith("Line 1\nLine 2")
    assert "\x00" not in status.message and "\x1b" not in status.message
    assert len(status.message) <= 600


class FakeResponse(io.BytesIO):
    def __init__(self, payload: bytes, url: str):
        super().__init__(payload)
        self._url = url

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def serve(monkeypatch, payload: bytes, final_url: str | None = None):
    seen = []

    def fake_urlopen(request, timeout=None):
        seen.append(request.full_url)
        return FakeResponse(payload, final_url or request.full_url)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return seen


def test_fetch_reads_the_file_from_the_repository(monkeypatch):
    seen = serve(monkeypatch, json.dumps({"disabled": True, "message": "Stop"}).encode())
    assert fetch_status() == Status(True, "Stop")
    assert seen == [updater.STATUS_URL]
    assert updater.STATUS_URL.startswith("https://raw.githubusercontent.com/") and updater.STATUS_URL.endswith("/status.json")


def test_fetch_accepts_a_byte_order_mark(monkeypatch):
    serve(monkeypatch, b"\xef\xbb\xbf" + json.dumps({"disabled": False}).encode())
    assert fetch_status() == Status(False, "")


@pytest.mark.parametrize("payload", [b"<html>captive portal</html>", b"", b"\xff\xfe\x00", b'{"disabled": maybe}'])
def test_fetch_reports_garbage_as_an_error(monkeypatch, payload):
    serve(monkeypatch, payload)
    with pytest.raises(UpdateError, match="not valid JSON"):
        fetch_status()


def test_fetch_refuses_a_redirect_to_another_host(monkeypatch):
    serve(monkeypatch, json.dumps({"disabled": False}).encode(), final_url="https://evil.example/status.json")
    with pytest.raises(UpdateError, match="non-GitHub"):
        fetch_status()


def test_fetch_rejects_an_oversized_file(monkeypatch):
    serve(monkeypatch, b" " * (300 * 1024))
    with pytest.raises(UpdateError, match="unexpectedly large"):
        fetch_status()


@pytest.mark.parametrize("error", [urllib.error.URLError("no route"), TimeoutError("slow"), OSError("reset")])
def test_fetch_wraps_network_failures(monkeypatch, error):
    def boom(*_a, **_k):
        raise error

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(UpdateError, match="Could not reach GitHub"):
        fetch_status()


def test_fetch_reports_a_missing_file(monkeypatch):
    def not_found(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", not_found)
    with pytest.raises(UpdateError, match="404"):
        fetch_status()


# ----------------------------------------------------------------------------- the decision
def test_a_new_copy_may_run_and_its_allowance_starts_now():
    settings = Settings()
    access.begin(settings, NOW)
    assert settings.verified_at == NOW
    assert access.current_block(settings, NOW) is None


def test_begin_never_restarts_an_allowance_that_is_running():
    settings = Settings(verified_at=NOW - 5 * DAY)
    access.begin(settings, NOW)
    assert settings.verified_at == NOW - 5 * DAY


def test_a_copy_that_was_checked_recently_runs_with_no_network():
    settings = Settings(verified_at=NOW - 3 * DAY)
    assert access.current_block(settings, NOW) is None


def test_the_offline_allowance_ends_after_the_grace_period():
    limit = access.OFFLINE_GRACE_DAYS * DAY
    assert access.current_block(Settings(verified_at=NOW - limit), NOW) is None  # exactly at the limit: still fine
    block = access.current_block(Settings(verified_at=NOW - limit - 1), NOW)
    assert block is not None and block.kind == "unverified"
    assert str(access.OFFLINE_GRACE_DAYS) in block.message


def test_a_status_that_says_stop_blocks_with_the_owners_words():
    settings = Settings()
    block = access.record_status(settings, Status(True, "Version 1.2 has a bug. Ask Man for 1.3."), NOW)
    assert block is not None and block.kind == "disabled"
    assert "Ask Man for 1.3" in block.message
    assert settings.deactivated and settings.verified_at == NOW


def test_a_stop_with_no_message_still_tells_people_what_to_do():
    block = access.record_status(Settings(), Status(True, ""), NOW)
    assert block is not None and block.message


def test_a_copy_told_to_stop_stays_stopped_offline():
    settings = Settings()
    access.record_status(settings, Status(True, "Stopped"), NOW)
    later = NOW + 2 * DAY  # no check could be made since: the remembered answer still decides
    block = access.current_block(settings, later)
    assert block is not None and block.kind == "disabled" and block.message == "Stopped"


def test_the_owner_can_switch_it_back_on():
    settings = Settings()
    access.record_status(settings, Status(True, "Stopped"), NOW)
    assert access.record_status(settings, Status(False, ""), NOW + DAY) is None
    assert not settings.deactivated and settings.deactivated_message == ""


def test_a_successful_check_restarts_the_allowance():
    settings = Settings(verified_at=NOW - 30 * DAY)
    assert access.current_block(settings, NOW) is not None
    assert access.record_status(settings, Status(False, ""), NOW) is None
    assert settings.verified_at == NOW


def test_the_remembered_state_survives_a_restart(tmp_path):
    path = tmp_path / "settings.json"
    settings = Settings()
    access.record_status(settings, Status(True, "Stopped"), NOW)
    save_settings(settings, path)
    reloaded = load_settings(path)
    assert reloaded.deactivated and reloaded.deactivated_message == "Stopped" and reloaded.verified_at == NOW
    block = access.current_block(reloaded, NOW + DAY)
    assert block is not None and block.kind == "disabled"


def test_hand_edited_settings_cannot_crash_the_check(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"deactivated": "yes", "verified_at": "yesterday", "deactivated_message": 5}), encoding="utf-8")
    settings = load_settings(path)
    assert not settings.deactivated and settings.verified_at == 0
    access.begin(settings, NOW)
    assert access.current_block(settings, NOW) is None
