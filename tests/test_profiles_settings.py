from __future__ import annotations

import json

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
    assert list(profiles)[:2] == list(BUILT_IN_PROFILE_NAMES)


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
