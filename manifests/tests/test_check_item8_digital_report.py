"""The attested report and inventory must associate each number with its source."""

import itertools
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_item8_digital_report as checker

BASELINE_LABELS = [
    "Post-synthesis cell area (row 10)",
    "Liberty leakage sum (context)",
    "ABC critical-path delay, typ corner (row 12 basis 3, synthesis estimate)",
    "Routed die area (post-layout, labelled separately)",
    "Routed core area (post-layout, labelled separately)",
]


def test_committed_report_matches():
    assert checker.main() == 0


@pytest.mark.parametrize(
    "first, second",
    [
        ("196.607", "212.095"),  # Fmax at different corners
        ("1674.45 um2", "850.954 um2"),  # die and core area
        *itertools.combinations(BASELINE_LABELS, 2),  # all 10 baseline label swaps
    ],
)
def test_misassigned_values_or_labels_fail(tmp_path, monkeypatch, first, second):
    text = checker.REPORT.read_text()
    assert text.count(first) == text.count(second) == 1
    report = tmp_path / "REPORT.md"
    report.write_text(
        text.replace(first, "SWAP").replace(second, first).replace("SWAP", second)
    )
    monkeypatch.setattr(checker, "REPORT", report)
    assert checker.main() == 1


@pytest.mark.parametrize("i, j", [(0, 1), (0, 2), (1, 2)])
def test_reordered_sta_corners_fail(tmp_path, monkeypatch, i, j):
    sta = json.loads(checker.STA_FILE.read_text())
    sta["corners"][i], sta["corners"][j] = sta["corners"][j], sta["corners"][i]
    sta_file = tmp_path / "sta.json"
    sta_file.write_text(json.dumps(sta))
    monkeypatch.setattr(checker, "STA_FILE", sta_file)
    assert checker.main() == 1


@pytest.mark.parametrize(
    "corner, metric, bad_field",
    [
        ("typ_1p20V_25C", "fmax", "corners.1.fmax_mhz"),
        ("typ_1p20V_25C", "power", "corners.2.estimated_power_mw"),
        ("fast_1p32V_m40C", "fmax", "corners.0.fmax_mhz"),
        ("slow_1p08V_125C", "power", "corners.1.estimated_power_mw"),
        ("typ_1p20V_25C", "fmax", "corners.0.estimated_power_mw"),
        ("typ_1p20V_25C", "power", "corners.0.fmax_mhz"),
    ],
)
def test_misbound_inventory_sta_metric_fails(
    tmp_path, monkeypatch, corner, metric, bad_field
):
    inv = json.loads(checker.INVENTORY.read_text())
    inv["metrics"][corner][metric]["field"] = bad_field
    inv_file = tmp_path / "item8.digital.json"
    inv_file.write_text(json.dumps(inv))
    monkeypatch.setattr(checker, "INVENTORY", inv_file)
    assert checker.main() == 1


def test_equal_values_still_check_corner_and_field_identity(tmp_path, monkeypatch):
    sta = json.loads(checker.STA_FILE.read_text())
    text = checker.REPORT.read_text()
    # Give fast corner the same fmax_mhz as typ, and set worst_slack_ns equal too,
    # so value comparison alone could not catch a wrong corner or wrong field.
    old_fast_fmax = str(sta["corners"][1]["fmax_mhz"])
    old_typ_slack = str(sta["corners"][0]["worst_slack_ns"])
    typ_fmax = sta["corners"][0]["fmax_mhz"]
    sta["corners"][1]["fmax_mhz"] = typ_fmax
    sta["corners"][0]["worst_slack_ns"] = typ_fmax
    sta_file = tmp_path / "sta.json"
    sta_file.write_text(json.dumps(sta))
    report = tmp_path / "REPORT.md"
    report.write_text(
        text.replace(old_fast_fmax, str(typ_fmax)).replace(old_typ_slack, str(typ_fmax))
    )
    monkeypatch.setattr(checker, "STA_FILE", sta_file)
    monkeypatch.setattr(checker, "REPORT", report)
    assert checker.main() == 0

    inv = json.loads(checker.INVENTORY.read_text())
    inv["metrics"]["typ_1p20V_25C"]["fmax"]["field"] = "corners.1.fmax_mhz"
    inv_file = tmp_path / "item8.digital.json"
    inv_file.write_text(json.dumps(inv))
    monkeypatch.setattr(checker, "INVENTORY", inv_file)
    assert checker.main() == 1

    inv["metrics"]["typ_1p20V_25C"]["fmax"]["field"] = "corners.0.worst_slack_ns"
    inv_file.write_text(json.dumps(inv))
    assert checker.main() == 1


def test_misbound_inventory_area_fails(tmp_path, monkeypatch):
    inv = json.loads(checker.INVENTORY.read_text())
    inv["metrics"]["typ_1p20V_25C"]["area"] = {
        "envelope": checker.PAR,
        "field": "core_area_um2",
    }
    inv_file = tmp_path / "item8.digital.json"
    inv_file.write_text(json.dumps(inv))
    monkeypatch.setattr(checker, "INVENTORY", inv_file)
    assert checker.main() == 1
