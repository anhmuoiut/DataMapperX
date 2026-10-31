"""Phase 0: the immutable dataset snapshot and its statistical fingerprint (apart from provenance)."""
from __future__ import annotations

import dataclasses
import subprocess
import sys
from pathlib import Path

import pytest

from datamapperx.exporter import iter_export_rows
from datamapperx.models import LogRecord, Measurement
from datamapperx.statistics import (
    AnalysisConfig,
    Dataset,
    Observation,
    compute,
    normalize_records,
    snapshot_from_records,
)

from .baseline_support import encode

REPO = Path(__file__).resolve().parent.parent


def rows(values=((1, 2, 3), (4, 5, 6), (7, 8, 9)), item="X", source=lambda i, j: f"C:/logs/S{i}_{j}.log", **extra):
    return [Observation(item, f"S{i}", value, 0, 20, trial=str(j), source=source(i, j), **extra)
            for i, group in enumerate(values) for j, value in enumerate(group)]


def record(path, sn, **entries):
    return LogRecord(Path(path), sn, {name: Measurement(name, *fields) for name, fields in entries.items()})


# ----------------------------------------------------------------------------- the fingerprint says what the numbers depend on
def test_equal_data_has_one_fingerprint_whatever_its_provenance():
    a = Dataset.from_observations(rows(), description="Data Mapping scan of C:/logs")
    b = Dataset.from_observations(
        [dataclasses.replace(o, source=f"Raw Data!R{n}", timestamp=f"2026-10-30T10:00:{n:02d}") for n, o in enumerate(rows(), 2)],
        order_basis="custom", description="imported from RawData.xlsx")
    assert a.fingerprint == b.fingerprint and a.item_fingerprints == b.item_fingerprints
    assert a.provenance_fingerprint != b.provenance_fingerprint


def test_numbers_are_compared_by_value_not_by_text():
    text = Dataset.from_observations([dataclasses.replace(o, value=f"{o.value}.250", lsl="0", usl="+2.0E+01") for o in rows()])
    number = Dataset.from_observations([dataclasses.replace(o, value=o.value + 0.25, lsl=0.0, usl=20) for o in rows()])
    assert text.fingerprint == number.fingerprint


def test_fingerprint_does_not_depend_on_object_identity():
    original = Dataset.from_observations(rows())
    twin = Dataset.from_observations(rows())
    assert original is not twin and original.observations[0] is not twin.observations[0]
    assert original.fingerprint == twin.fingerprint and original.fingerprint.startswith("v1:")


def changed(index, **fields):
    data = rows()
    data[index] = dataclasses.replace(data[index], **fields)
    return data


@pytest.mark.parametrize("variant", [
    changed(0, value=1.5), changed(0, lsl=1), changed(0, usl=21), changed(0, sample_id="S9"), changed(0, trial="9"),
    changed(0, operator="A"), changed(0, tester="T"), changed(0, slot="2"), changed(0, unit="V"), changed(0, subgroup="G"),
    changed(0, test_item="Y"), changed(0, value="bad"),
    rows()[1:], rows()[::-1], [rows()[1], rows()[0], *rows()[2:]],
    changed(1, source=rows()[0].source),  # two observations now share one source: the engine treats that as an error
], ids=lambda variant: "")
def test_the_fingerprint_changes_when_the_statistics_could(variant):
    assert Dataset.from_observations(variant).fingerprint != Dataset.from_observations(rows()).fingerprint


def test_order_within_an_item_matters_but_order_between_items_does_not():
    x, y = rows(item="X"), rows(((2, 4), (6, 9)), item="Y")
    one = Dataset.from_observations(x + y)
    other = Dataset.from_observations(y[:2] + x + y[2:])  # items interleaved differently, each item's own order kept
    assert one.fingerprint == other.fingerprint
    assert Dataset.from_observations(x[::-1] + y).fingerprint != one.fingerprint
    assert one.items == ("X", "Y") and len(one) == 13


def test_an_item_fingerprint_does_not_depend_on_other_items():
    alone = Dataset.from_observations(rows(item="X"))
    with_other = Dataset.from_observations(rows(item="W", source=lambda i, j: f"other{i}{j}") + rows(item="X"))
    assert dict(alone.item_fingerprints)["X"] == dict(with_other.item_fingerprints)["X"]
    assert alone.fingerprint != with_other.fingerprint


def test_fingerprint_is_stable_across_processes_and_hash_seeds():
    script = (
        "import sys; sys.path.insert(0, '.')\n"
        "from datamapperx.statistics import Dataset, Observation\n"
        "rows = [Observation('X', f'S{i}', v, 0, 20, trial=str(j), source=f's{i}{j}') "
        "for i, g in enumerate(((1, 2, 3), (4, 5, 6))) for j, v in enumerate(g)]\n"
        "d = Dataset.from_observations(rows, description='d')\nprint(d.fingerprint, d.provenance_fingerprint)")
    seen = set()
    for seed in ("0", "1", "4242"):
        import os

        env = {**os.environ, "PYTHONHASHSEED": seed}
        seen.add(subprocess.run([sys.executable, "-c", script], cwd=REPO, env=env, capture_output=True, text=True, check=True).stdout.strip())
    assert len(seen) == 1
    local = Dataset.from_observations(
        [Observation("X", f"S{i}", v, 0, 20, trial=str(j), source=f"s{i}{j}")
         for i, g in enumerate(((1, 2, 3), (4, 5, 6))) for j, v in enumerate(g)], description="d")
    assert seen == {f"{local.fingerprint} {local.provenance_fingerprint}"}


# ----------------------------------------------------------------------------- immutable
def test_a_dataset_cannot_be_changed_after_it_is_made():
    dataset = Dataset.from_observations(rows())
    with pytest.raises(dataclasses.FrozenInstanceError):
        dataset.observations = ()
    with pytest.raises(dataclasses.FrozenInstanceError):
        dataset.fingerprint = "x"
    with pytest.raises(dataclasses.FrozenInstanceError):
        dataset.observations[0].value = 99
    assert isinstance(dataset.observations, tuple)
    source = rows()
    kept = Dataset.from_observations(source)
    source.clear()
    assert len(kept) == 9
    with pytest.raises(ValueError, match="order_basis"):
        Dataset.from_observations(rows(), order_basis="sorted")


# ----------------------------------------------------------------------------- snapshot from scanned records
def scanned():
    # Serial numbers meet in the order B, A (as a scan sorted by path would meet them); files sorted by name within each.
    return {"B": [record("z/B_1.log", "B", X=("1.5", "0", "20", "V"), Y=("7", "", "", "")), record("z/B_2.log", "B", X=("1.6", "0", "20", "V"))],
            "A": [record("a/A_1.log", "A", X=("2.5", "0", "20", "V")), record("a/A_2.log", "A", X=("2.6", "0", "20", "V"), Y=("8", "", "", ""))]}


def test_the_snapshot_is_isolated_from_later_changes_to_the_records():
    grouped = scanned()
    dataset = snapshot_from_records(grouped, ["X", "Y"])
    before, fingerprint = encode(dataset.observations), dataset.fingerprint
    grouped["A"][0].entries["X"] = Measurement("X", "999", "0", "20", "V")  # a duplicate dialog replaces an entry
    del grouped["B"][0]
    grouped["C"] = []
    assert encode(dataset.observations) == before and dataset.fingerprint == fingerprint
    assert snapshot_from_records(grouped, ["X", "Y"]).fingerprint != fingerprint


def test_taking_a_snapshot_does_not_modify_the_records():
    grouped = scanned()
    before = {sn: [(r.path, r.sn, dict(r.entries)) for r in records] for sn, records in grouped.items()}
    snapshot_from_records(grouped, ["X", "Y"], {"trial": "@trial"}, assign_trials=False)
    after = {sn: [(r.path, r.sn, dict(r.entries)) for r in records] for sn, records in grouped.items()}
    assert before == after and list(grouped) == ["B", "A"]


def test_snapshot_order_is_the_order_of_the_rawdata_rows_not_the_scan_order():
    grouped = scanned()
    dataset = snapshot_from_records(grouped, ["X"])
    assert dataset.order_basis == "worksheet"
    export = [(row.sn, row.filename, row.values[0]) for row in iter_export_rows(grouped, ["X"])]
    assert [(o.sample_id, Path(o.source).name, o.value) for o in dataset.observations] == export
    assert [o.sample_id for o in dataset.observations] == ["A", "A", "B", "B"]
    # The panel's existing adapter keeps the scan order; the two orders differ, which Phase 1 must resolve.
    assert [o.sample_id for o in normalize_records(grouped, ["X"])] == ["B", "B", "A", "A"]


def test_field_mapping_and_file_assignments_are_applied():
    grouped = scanned()
    sources = {str(r.path): r for records in grouped.values() for r in records}
    first = str(grouped["A"][0].path)
    dataset = snapshot_from_records(grouped, ["X"], {"trial": "@trial", "tester": "=T1"},
                                    assignments={first: {"operator": "Op1"}}, description="scan")
    by_source = {o.source: o for o in dataset.observations}
    assert set(by_source) == set(sources) and by_source[first].operator == "Op1" and by_source[first].trial == "1"
    assert {o.tester for o in dataset.observations} == {"T1"} and dataset.description == "scan"


def test_two_sources_with_the_same_data_give_the_same_metrics():
    grouped = {"S0": [record(f"S0_{j}.log", "S0", X=(str(v), "0", "20", "V")) for j, v in enumerate((1, 2, 3))],
               "S1": [record(f"S1_{j}.log", "S1", X=(str(v), "0", "20", "V")) for j, v in enumerate((4, 5, 6))],
               "S2": [record(f"S2_{j}.log", "S2", X=(str(v), "0", "20", "V")) for j, v in enumerate((7, 8, 9))]}
    from_scan = snapshot_from_records(grouped, ["X"], {"trial": "@trial", "unit": "=V"}, description="Data Mapping")
    from_workbook = Dataset.from_observations(
        [Observation("X", f"S{i}", float(v), 0.0, 20.0, trial=str(j + 1), unit="V", source=f"Raw Data!R{r}")
         for r, (i, j, v) in enumerate(((i, j, 1 + 3 * i + j) for i in range(3) for j in range(3)), 2)], description="RawData.xlsx")
    assert from_scan.fingerprint == from_workbook.fingerprint
    assert from_scan.provenance_fingerprint != from_workbook.provenance_fingerprint
    config = AnalysisConfig(method="grr")
    metrics = [compute(d.observations, config)[0].metrics for d in (from_scan, from_workbook)]
    assert encode(metrics[0]) == encode(metrics[1]) and metrics[0]["ndc"] == 4
