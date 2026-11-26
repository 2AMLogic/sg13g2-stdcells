"""The attested report must associate each number with its source."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_item8_digital_report as checker


def test_committed_report_matches():
    assert checker.main() == 0


@pytest.mark.parametrize(
    "first, second",
    [
        ("196.607", "212.095"),  # Fmax at different corners
        ("1674.45 um2", "850.954 um2"),  # die and core area
    ],
)
def test_misassigned_values_fail(tmp_path, monkeypatch, first, second):
    text = checker.REPORT.read_text()
    assert text.count(first) == text.count(second) == 1
    report = tmp_path / "REPORT.md"
    report.write_text(
        text.replace(first, "SWAP").replace(second, first).replace("SWAP", second)
    )
    monkeypatch.setattr(checker, "REPORT", report)
    assert checker.main() == 1
