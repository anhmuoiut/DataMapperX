"""The built exe's self-test (``DataMapperX.exe --smoke-test``) run from source: every component once, through the real window."""
from __future__ import annotations

from datamapperx import selftest


def test_the_smoke_test_checks_the_app_end_to_end(app, tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("DATAMAPPERX_HOME", str(tmp_path / "home"))
    with caplog.at_level("INFO"):
        assert selftest.run() == 0
    assert "Smoke test passed" in caplog.text and "Statistical report self-test passed" in caplog.text


def test_the_smoke_test_can_run_again_with_a_remembered_choice_in_the_data_folder(app, tmp_path, monkeypatch):
    monkeypatch.setenv("DATAMAPPERX_HOME", str(tmp_path / "home"))
    sample = selftest._check_logic(tmp_path)
    selftest._check_window(sample)
    selftest._check_window(sample)  # the first run left its choice behind and the second must still pass


def test_the_smoke_test_reports_a_broken_window_through_its_exit_code(app, tmp_path, monkeypatch):
    monkeypatch.setenv("DATAMAPPERX_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(selftest, "_check_window", lambda sample: (_ for _ in ()).throw(selftest.SmokeTestError("no window")))
    assert selftest.run() == 1
