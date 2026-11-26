"""Re-derive every figure in the item 8 digital characterization report
(flow/records/20261123-item8-digital/REPORT.md) from the committed record
files it cites (issue #177). Check the source and field on each area or
delay row, and the timing and power values on each corner row. Stdlib only."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "flow/records/20261123-item8-digital/REPORT.md"
SYN = "flow/records/20261104-df96543/synthesize.json"
PAR = "flow/records/20261121-be3a384/place-and-route.json"
STA = "flow/records/20261121-be3a384/sta.json"


def table_rows(text, heading):
    """Read the rows of a Markdown table with the given column headings."""
    lines = iter(text.splitlines())
    for line in lines:
        if line == heading:
            break
    next(lines, None)  # column separators
    rows = []
    for line in lines:
        if not line.startswith("|"):
            break
        rows.append(tuple(cell.strip() for cell in line.strip("|").split("|")))
    return rows


def main():
    text = REPORT.read_text()
    syn = json.loads((ROOT / SYN).read_text())
    par = json.loads((ROOT / PAR).read_text())
    sta = json.loads((ROOT / STA).read_text())
    quantities = [
        (f"{syn['area_um2']} um2", f"`{SYN}`", "`area_um2`"),
        (f"{syn['leakage_power_nw']} nW", f"`{SYN}`", "`leakage_power_nw`"),
        (
            f"{syn['timing']['critical_path_ps']} ps",
            f"`{SYN}`",
            "`timing.critical_path_ps`",
        ),
        (f"{par['die_area_um2']} um2", f"`{PAR}`", "`die_area_um2`"),
        (f"{par['core_area_um2']} um2", f"`{PAR}`", "`core_area_um2`"),
    ]
    rows = table_rows(
        text, "| Quantity (Benchmark basis item) | Value | Source file | JSON field |"
    )
    if sorted(row[1:] for row in rows) != sorted(quantities):
        print(
            "Baseline quantities differ from the cited synthesis or place-and-route fields."
        )
        return 1
    corners = [
        (
            f"`{c['corner']}`",
            str(c["fmax_mhz"]),
            str(c["worst_slack_ns"]),
            str(c["estimated_power_mw"]),
        )
        for c in sta["corners"]
    ]
    rows = table_rows(
        text,
        "| Corner (`corners[].corner`) | `fmax_mhz` | `worst_slack_ns` | `estimated_power_mw` |",
    )
    if sorted(rows) != sorted(corners):
        print(f"Per-corner timing or power differs from {STA}.")
        return 1
    if "rows 10-12: owned, unmeasured" not in text.lower():
        print("Missing unmeasured status for rows 10-12.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
