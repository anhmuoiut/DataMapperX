from __future__ import annotations

import json
from pathlib import Path

import pytest

from datamapperx.profiles import (
    BUILT_IN_PROFILE_NAMES,
    DEFAULT_PROFILES,
    get_profile_extensions,
    load_profiles,
    save_profiles,
    validate_profile,
)
from datamapperx.settings import Settings, load_settings, save_settings


def test_first_run_writes_defaults(tmp_path):
    path = tmp_path / "profiles.json"
    profiles = load_profiles(path)
    assert list(profiles) == list(BUILT_IN_PROFILE_NAMES)
    assert json.loads(path.read_text("utf-8")) == profiles


def test_custom_profile_survives_reload_and_builtins_are_restored(tmp_path):
    path = tmp_path / "profiles.json"
    tampered = json.loads(json.dumps(DEFAULT_PROFILES))
    tampered["ICT_I3070 Test Log"]["measure_regex"] = "broken"
    tampered["My Profile"] = {"type": "excel", "component_col": "A", "measure_col": "B"}
    path.write_text(json.dumps(tampered), "utf-8")

    profiles = load_profiles(path)

    assert profiles["ICT_I3070 Test Log"] == DEFAULT_PROFILES["ICT_I3070 Test Log"]
    assert profiles["My Profile"]["measure_col"] == "B"
    assert list(profiles)[: len(BUILT_IN_PROFILE_NAMES)] == list(BUILT_IN_PROFILE_NAMES)


def test_legacy_profile_names_are_migrated(tmp_path):
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps({"FT build": {"type": "excel"}, "HP3070 (Built-in)": {"type": "text"}}), "utf-8")
    profiles = load_profiles(path)
    assert "FT build" not in profiles and "HP3070 (Built-in)" not in profiles
    assert set(BUILT_IN_PROFILE_NAMES) <= set(profiles)


def test_corrupt_file_is_backed_up_not_silently_overwritten(tmp_path):
    path = tmp_path / "profiles.json"
    path.write_text("{ this is not json", "utf-8")

    profiles = load_profiles(path)

    assert list(profiles) == list(BUILT_IN_PROFILE_NAMES)
    backups = list(tmp_path.glob("profiles.json.corrupt-*"))
    assert len(backups) == 1 and backups[0].read_text("utf-8") == "{ this is not json"


def test_malformed_profile_entry_is_dropped(tmp_path):
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps({"Bad": "not a dict", "Good": {"type": "text"}}), "utf-8")
    profiles = load_profiles(path)
    assert "Bad" not in profiles and "Good" in profiles


def test_save_is_atomic_and_leaves_no_temp_file(tmp_path):
    path = tmp_path / "profiles.json"
    save_profiles({"X": {"type": "text"}}, path)
    assert json.loads(path.read_text("utf-8")) == {"X": {"type": "text"}}
    assert not list(tmp_path.glob("*.tmp"))


# ----------------------------------------------------------------------------- validation
def test_validate_accepts_builtins():
    for profile in DEFAULT_PROFILES.values():
        validate_profile(profile)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"type": "pdf"}, "either 'text' or 'excel'"),
        ({"block_regex": ""}, "missing Name_Regex"),
        ({"measure_regex": "("}, "Invalid Regex in Measure_Regex"),
    ],
)
def test_validate_rejects_bad_text_profile(change, message):
    profile = {**DEFAULT_PROFILES["ICT_I3070 Test Log"], **change}
    with pytest.raises(ValueError, match=message):
        validate_profile(profile)


@pytest.mark.parametrize(
    ("change", "message"),
    [({"row_start": "0"}, "at least 1"), ({"component_col": "1"}, "column letter"), ({"sn_regex": "("}, "SN_Regex")],
)
def test_validate_rejects_bad_excel_profile(change, message):
    profile = {**DEFAULT_PROFILES["Function Test Log"], **change}
    with pytest.raises(ValueError, match=message):
        validate_profile(profile)


def test_extensions_are_normalised():
    assert get_profile_extensions({"file_extensions": "LOG; txt  .csv,.LOG"}) == (".log", ".txt", ".csv")
    assert get_profile_extensions({"type": "excel"}) == (".xlsx", ".xlsm")
    assert get_profile_extensions({"file_extensions": ["log", ".TXT"]}) == (".log", ".txt")


# ----------------------------------------------------------------------------- settings
def test_settings_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    save_settings(Settings(theme="dark", last_folder="C:/x", component_sets={"P": ["R1", "R2"]}), path)
    loaded = load_settings(path)
    assert loaded.theme == "dark" and loaded.component_sets == {"P": ["R1", "R2"]}


def test_settings_ignore_wrong_types_and_unknown_keys(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"theme": 5, "check_updates": "yes", "bogus": 1, "repeats": "4"}), "utf-8")
    loaded = load_settings(path)
    assert loaded.theme == "system" and loaded.check_updates is True and loaded.repeats == "4"


@pytest.mark.parametrize("content", ["", "[]", "{broken"])
def test_settings_survive_garbage_file(tmp_path, content):
    path = tmp_path / "settings.json"
    path.write_text(content, "utf-8")
    assert load_settings(path) == Settings()


def test_settings_missing_file_gives_defaults(tmp_path):
    assert load_settings(tmp_path / "nope.json") == Settings()


# ----------------------------------------------------------------------------- EOL built-in profile and suggestions
def test_eol_logs_are_read_by_a_built_in_profile(tmp_path):
    from datamapperx.parsing import parse_log_file

    from .test_sampling import EOL_ROWS, write_results_workbook

    path = write_results_workbook(tmp_path / "SV3826-06310A8C6-E1 1.xlsx", "SV3826-06310A8C6-E1", EOL_ROWS)
    parsed = parse_log_file(path, DEFAULT_PROFILES["EOL Test Log"])
    assert parsed.sn == "SV3826-06310A8C6-E1"
    assert list(parsed.entries) == ["Init, Test SIM SN", "Config, Get Portia SW Version", "DC bus voltage"]
    assert DEFAULT_PROFILES["EOL Test Log"] == DEFAULT_PROFILES["Function Test Log"] | {"sn_regex": "B1"}


def test_a_profile_the_user_called_eol_test_log_is_kept_when_the_built_in_arrives(tmp_path):
    path = tmp_path / "profiles.json"
    mine = {"type": "excel", "sn_regex": "C3", "component_col": "A", "measure_col": "B", "data_sheet": "Mine"}
    path.write_text(json.dumps({"EOL Test Log": mine}), "utf-8")

    profiles = load_profiles(path)

    assert profiles["EOL Test Log"] == DEFAULT_PROFILES["EOL Test Log"]
    assert profiles["EOL Test Log (yours)"] == mine
    assert load_profiles(path) == profiles  # stable: nothing is renamed twice
    assert json.loads(path.read_text("utf-8"))["EOL Test Log (yours)"] == mine


# ----------------------------------------------------------------------------- profiles of an older version
def _old_install(tmp_path, monkeypatch, profiles: dict) -> Path:
    """A folder with the profiles.json that v1.1.0 kept next to the program."""
    app_folder = tmp_path / "old_app"
    app_folder.mkdir()
    (app_folder / "profiles.json").write_text(json.dumps(profiles), "utf-8")
    monkeypatch.setattr("datamapperx.profiles.app_dir", lambda: app_folder)
    return app_folder


def test_profiles_of_the_old_version_are_imported_once(tmp_path, monkeypatch):
    custom = {"type": "text", "sn_regex": "(TSE[A-Z0-9]+)", "block_regex": "b", "measure_regex": "m"}
    _old_install(tmp_path, monkeypatch, {
        "ICT_I3070 Test Log": {"type": "text", "measure_regex": "edited by hand"},  # built-ins are never imported
        "FT build": {"type": "excel"},  # nor legacy names of built-ins
        "ICT Test Log (SN: TSE....)": custom,
        "Not a profile": "text",
    })
    data_file = tmp_path / "data" / "profiles.json"
    data_file.parent.mkdir()

    profiles = load_profiles(data_file)

    assert profiles["ICT Test Log (SN: TSE....)"] == custom
    assert profiles["ICT_I3070 Test Log"] == DEFAULT_PROFILES["ICT_I3070 Test Log"]
    assert "Not a profile" not in profiles and "FT build" not in profiles
    assert (data_file.parent / "legacy_profiles_imported").exists()
    assert "ICT Test Log (SN: TSE....)" in json.loads(data_file.read_text("utf-8"))

    # Deleting the imported profile later must not bring it back on the next start.
    del profiles["ICT Test Log (SN: TSE....)"]
    save_profiles(profiles, data_file)
    assert "ICT Test Log (SN: TSE....)" not in load_profiles(data_file)


def test_importing_old_profiles_never_overwrites_a_profile_the_user_already_has(tmp_path, monkeypatch):
    _old_install(tmp_path, monkeypatch, {"Mine": {"type": "text", "measure_regex": "OLD"}, "Other": {"type": "excel"}})
    data_file = tmp_path / "profiles.json"
    data_file.write_text(json.dumps({"Mine": {"type": "text", "measure_regex": "NEW"}}), "utf-8")

    profiles = load_profiles(data_file)

    assert profiles["Mine"]["measure_regex"] == "NEW" and profiles["Other"] == {"type": "excel"}


def test_an_unreadable_old_profiles_file_does_not_stop_the_app_starting(tmp_path, monkeypatch):
    app_folder = _old_install(tmp_path, monkeypatch, {})
    (app_folder / "profiles.json").write_text("{ not json", "utf-8")
    profiles = load_profiles(tmp_path / "profiles.json")
    assert list(profiles) == list(BUILT_IN_PROFILE_NAMES)
    assert not (tmp_path / "legacy_profiles_imported").exists()  # tried again next start


def test_no_old_profiles_file_means_nothing_is_imported_or_marked(tmp_path, monkeypatch):
    empty = tmp_path / "empty_app"
    empty.mkdir()
    monkeypatch.setattr("datamapperx.profiles.app_dir", lambda: empty)
    load_profiles(tmp_path / "profiles.json")
    assert not (tmp_path / "legacy_profiles_imported").exists()
