from __future__ import annotations

from datamapperx.reporting import describe_empty_scan, full_report, summarize_scan
from datamapperx.scanner import scan_folder

from .conftest import ict_block, write_ict_log


def folder_with(tmp_path, spec):
    for sn, runs in spec.items():
        for run in range(runs):
            write_ict_log(tmp_path / f"{sn}_{run}.log", sn, [ict_block("R1", "+1.0E+00")])
    return tmp_path


def test_clean_scan_is_ok(tmp_path, ict_profile):
    result = scan_folder(folder_with(tmp_path, {"VSE1": 3, "VSE2": 3}), ict_profile)
    summary = summarize_scan(result, expected_sns=2, repeats=3)
    assert summary.level == "ok" and summary.issues == []
    assert "2 samples × 3 files" in summary.headline


def test_wrong_sample_count_is_a_warning(tmp_path, ict_profile):
    result = scan_folder(folder_with(tmp_path, {"VSE1": 3}), ict_profile)
    summary = summarize_scan(result, expected_sns=10, repeats=3)
    assert summary.level == "warn"
    assert summary.issues == ["Expected 10 samples but found 1."]


def test_wrong_repeat_count_blocks_and_names_the_sample(tmp_path, ict_profile):
    result = scan_folder(folder_with(tmp_path, {"VSE1": 3, "VSE2": 2}), ict_profile)
    summary = summarize_scan(result, expected_sns=2, repeats=3)
    assert summary.level == "bad"
    assert "VSE2" in summary.issues[0] and "exactly 3" in summary.issues[0]
    assert "VSE2: 2 file(s)" in full_report(result, 2, 3)


def test_many_bad_samples_are_clipped(tmp_path, ict_profile):
    result = scan_folder(folder_with(tmp_path, {f"VSE{n:02d}": 1 for n in range(12)}), ict_profile)
    issue = summarize_scan(result, 12, 3).issues[0]
    assert "and 7 more" in issue


def test_empty_folder_explained(tmp_path, ict_profile):
    result = scan_folder(tmp_path, ict_profile)
    assert "does not contain any files" in describe_empty_scan(tmp_path, "P", ict_profile, result)


def test_wrong_file_type_lists_what_was_found(tmp_path, ict_profile):
    (tmp_path / "a.pdf").write_text("x")
    (tmp_path / "b.pdf").write_text("x")
    result = scan_folder(tmp_path, ict_profile)
    text = describe_empty_scan(tmp_path, "P", ict_profile, result)
    assert "No files match" in text and ".pdf (2)" in text


def test_files_without_serial_are_explained(tmp_path, ict_profile):
    (tmp_path / "anon.log").write_text(ict_block("R1", "+1.0E+00"))
    result = scan_folder(tmp_path, ict_profile)
    text = describe_empty_scan(tmp_path, "P", ict_profile, result)
    assert "no serial number matched" in text and "anon.log" in text
