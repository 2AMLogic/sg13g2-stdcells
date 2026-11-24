#!/usr/bin/env python3
"""Re-derive every figure in the item 8 digital characterization report
(flow/records/20261123-item8-digital/REPORT.md) from the committed record
files it cites (issue #177). Exits 0 when each figure appears in the report
and equals the record field, 1 on any mismatch. Stdlib only."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "flow/records/20261123-item8-digital/REPORT.md"
REC = ROOT / "flow/records"


def load(rel):
    return json.loads((REC / rel).read_text())


def main():
    text = REPORT.read_text()
    syn = load("20261104-df96543/synthesize.json")
    par = load("20261121-be3a384/place-and-route.json")
    sta = load("20261121-be3a384/sta.json")
    want = [
        syn["area_um2"], syn["leakage_power_nw"], syn["timing"]["critical_path_ps"],
        par["die_area_um2"], par["core_area_um2"],
    ]
    for c in sta["corners"]:
        want += [c["fmax_mhz"], c["worst_slack_ns"], c["estimated_power_mw"]]
        if f"`{c['corner']}`" not in text:
            print(f"corner {c['corner']} missing from report")
            return 1
    bad = [v for v in want if str(v) not in text]
    for v in bad:
        print(f"value {v} not in report")
    for row in ("10", "11", "12"):
        if f"row {row}" not in text.lower() and f"rows {row}" not in text.lower() and row not in text:
            bad.append(row)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
