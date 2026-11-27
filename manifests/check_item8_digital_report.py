"""Re-derive every figure in the item 8 digital characterization report
(flow/records/20261123-item8-digital/REPORT.md) from the committed record
files it cites, and verify each metric binding in
manifests/inventories/item8.digital.json against its source object and named
report metric (issue #177). Stdlib only."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT_REL = "flow/records/20261123-item8-digital/REPORT.md"
REPORT = ROOT / REPORT_REL
INVENTORY = ROOT / "manifests/inventories/item8.digital.json"
SYN = "flow/records/20261104-df96543/synthesize.json"
PAR = "flow/records/20261121-be3a384/place-and-route.json"
STA = "flow/records/20261121-be3a384/sta.json"
SYN_FILE = ROOT / SYN
PAR_FILE = ROOT / PAR
STA_FILE = ROOT / STA

AREA_QUANTITY = "Post-synthesis cell area (row 10)"
CORNER_METRICS = (
    ("fmax", "fmax_mhz"),
    ("power", "estimated_power_mw"),
)


def _is_index(token):
    return token.isascii() and token.isdigit() and str(int(token)) == token


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


def resolve_field(doc, field):
    """Walk a dotted field path and return (parent, leaf_key, value), or None."""
    if not isinstance(field, str) or not field:
        return None
    parts = field.split(".")
    parent = None
    cur = doc
    for part in parts:
        if isinstance(cur, dict) and part in cur:
            parent = cur
            cur = cur[part]
        elif isinstance(cur, list) and _is_index(part) and int(part) < len(cur):
            parent = cur
            cur = cur[int(part)]
        else:
            return None
    return parent, parts[-1], cur


def check_inventory_bindings(inv, sources, area_row, report_corners):
    """Verify every inventory metric binding against its source object and report row."""
    if not isinstance(inv, dict) or inv.get("report") != REPORT_REL:
        print(f"Inventory report does not match {REPORT_REL}.")
        return False
    inv_corners = inv.get("corners")
    metrics = inv.get("metrics")
    if (
        not isinstance(inv_corners, list)
        or len(inv_corners) != len(set(inv_corners))
        or not isinstance(metrics, dict)
        or set(inv_corners) != set(metrics)
        or set(inv_corners) != set(report_corners)
    ):
        print("Inventory corners or metrics keys do not match the report corners.")
        return False

    for corner in inv_corners:
        corner_metrics = metrics[corner]
        if not isinstance(corner_metrics, dict) or set(corner_metrics) != {
            "area",
            "fmax",
            "power",
        }:
            print(f"Inventory metrics for {corner} must bind area, fmax, and power.")
            return False

        area_binding = corner_metrics["area"]
        if not isinstance(area_binding, dict) or area_binding.get("envelope") != SYN:
            print(f"Inventory {corner}.area must cite {SYN}.")
            return False
        resolved_area = resolve_field(sources[SYN], area_binding.get("field"))
        if resolved_area is None:
            print(
                f"Inventory {corner}.area field {area_binding.get('field')!r} failed to resolve."
            )
            return False
        _, area_leaf, area_val = resolved_area
        if (
            area_binding.get("field") != "area_um2"
            or (f"{area_val} um2", f"`{SYN}`", f"`{area_leaf}`") != area_row[1:]
        ):
            print(
                f"Inventory {corner}.area does not match the report baseline area row."
            )
            return False

        for metric_key, sta_field in CORNER_METRICS:
            binding = corner_metrics[metric_key]
            field_path = binding.get("field") if isinstance(binding, dict) else None
            parts = field_path.split(".") if isinstance(field_path, str) else []
            if (
                not isinstance(binding, dict)
                or binding.get("envelope") != STA
                or len(parts) != 3
                or parts[0] != "corners"
                or not _is_index(parts[1])
            ):
                print(
                    f"Inventory {corner}.{metric_key} must bind corners.<index>.{sta_field} in {STA}."
                )
                return False
            resolved = resolve_field(sources[STA], field_path)
            if resolved is None:
                print(
                    f"Inventory {corner}.{metric_key} field {field_path!r} out of range in {STA}."
                )
                return False
            source_obj, leaf_key, value = resolved
            if (
                not isinstance(source_obj, dict)
                or source_obj.get("corner") != corner
                or leaf_key != sta_field
                or str(value) != report_corners[corner][sta_field]
            ):
                src_corner = (
                    source_obj.get("corner") if isinstance(source_obj, dict) else None
                )
                print(
                    f"Inventory {corner}.{metric_key} ({field_path}) resolved to "
                    f"corner={src_corner!r}, field={leaf_key!r}, value={value!r}; "
                    f"expected {corner!r}.{sta_field}={report_corners[corner][sta_field]!r}."
                )
                return False
    return True


def main():
    text = REPORT.read_text()
    syn = json.loads(SYN_FILE.read_text())
    par = json.loads(PAR_FILE.read_text())
    sta = json.loads(STA_FILE.read_text())
    inv = json.loads(INVENTORY.read_text())
    quantities = [
        (AREA_QUANTITY, f"{syn['area_um2']} um2", f"`{SYN}`", "`area_um2`"),
        (
            "Liberty leakage sum (context)",
            f"{syn['leakage_power_nw']} nW",
            f"`{SYN}`",
            "`leakage_power_nw`",
        ),
        (
            "ABC critical-path delay, typ corner (row 12 basis 3, synthesis estimate)",
            f"{syn['timing']['critical_path_ps']} ps",
            f"`{SYN}`",
            "`timing.critical_path_ps`",
        ),
        (
            "Routed die area (post-layout, labelled separately)",
            f"{par['die_area_um2']} um2",
            f"`{PAR}`",
            "`die_area_um2`",
        ),
        (
            "Routed core area (post-layout, labelled separately)",
            f"{par['core_area_um2']} um2",
            f"`{PAR}`",
            "`core_area_um2`",
        ),
    ]
    baseline_rows = table_rows(
        text, "| Quantity (Benchmark basis item) | Value | Source file | JSON field |"
    )
    if sorted(baseline_rows) != sorted(quantities):
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
    corner_rows = table_rows(
        text,
        "| Corner (`corners[].corner`) | `fmax_mhz` | `worst_slack_ns` | `estimated_power_mw` |",
    )
    if f"`{STA}`" not in text or sorted(corner_rows) != sorted(corners):
        print(f"Per-corner timing or power differs from {STA}.")
        return 1
    report_corners = {
        row[0][1:-1]: {
            "fmax_mhz": row[1],
            "worst_slack_ns": row[2],
            "estimated_power_mw": row[3],
        }
        for row in corner_rows
    }
    if len(report_corners) != len(corner_rows):
        print("Duplicate corner rows in report.")
        return 1
    area_row = next(row for row in baseline_rows if row[0] == AREA_QUANTITY)
    if not check_inventory_bindings(
        inv, {SYN: syn, PAR: par, STA: sta}, area_row, report_corners
    ):
        return 1
    if "rows 10-12: owned, unmeasured" not in text.lower():
        print("Missing unmeasured status for rows 10-12.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
