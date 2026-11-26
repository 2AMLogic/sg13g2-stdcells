"""Run the item-5 ``klt sim`` testbenches and commit them as append-only evidence.

One record per invocation: ``sim/item5/records/<id>/`` carries every generated
testbench, its request document and the ``klt sim`` envelope exactly as klt
emitted it, and ``sim/item5/records/<id>.md`` summarises the run (the same
append-only convention ``sim/characterize`` keeps: nothing is ever
overwritten; a re-run mints a new id).

A run that does not grade ``pass`` on every measurement commits nothing and
raises -- the envelopes this record exists to produce are limit-checked
evidence, and a failing one is a finding to investigate, not a record to
append (an append-only record of a known-broken testbench would be
indistinguishable from evidence once fixed).
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from ..harness.report import allocate_record_id, commit_stamp, git_provenance
from .request import (
    SPEC_ROW,
    arcs_for,
    build_function_netlist,
    build_function_request_with_targets,
    build_timing_netlist,
    build_timing_request_with_targets,
    parse_liberty,
)

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
RECORDS_DIR = HERE / "records"
DEFAULT_CONFIG = REPO_ROOT / "layout" / "example_config.json"
DEFAULT_VIEW = REPO_ROOT / "views" / "sg13g2_stdcells_tt_1p20v_25c.lib"
NETLISTS_DIR = REPO_ROOT / "layout" / "lvs" / "netlists"

#: Both testbench kinds per cell, in the order the record lists them.
KINDS = ("function", "timing")

#: Host rule: a batch ``klt sim`` submit must wait out fleet capacity instead
#: of failing on ``batch_no_capacity``; ``klt`` rejects the flag on
#: ``--backend local``, so it is added for batch submits only.
BATCH_CAPACITY_WAIT_S = 600


class Item5Failed(RuntimeError):
    pass


def klt_version() -> str:
    try:
        out = subprocess.run(["klt", "--version"], capture_output=True, text=True, check=False)
    except FileNotFoundError:  # tool-free environments (CI) have no klt
        return "unavailable"
    return (out.stdout or out.stderr).strip() or "unknown"


def run_klt_sim(request_path: Path, backend: str, outdir: Path) -> str:
    """Run one request; return klt's JSON report text (byte-preserved)."""
    cmd = ["klt", "sim", "--format", "json", "--backend", backend,
           "-o", str(outdir), str(request_path)]
    if backend == "batch":
        cmd[2:2] = ["--wait-for-capacity", str(BATCH_CAPACITY_WAIT_S)]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise Item5Failed(
            f"klt sim exited {proc.returncode} on {request_path.name}: "
            f"{(proc.stdout + proc.stderr).strip()[:2000]}"
        )
    return proc.stdout


def _grade(report: dict, exp: dict[str, float], what: str) -> dict:
    """Assert the envelope passed on every measurement; return the worst
    observed disagreement with the committed values."""
    if report.get("status") != "pass":
        raise Item5Failed(f"{what}: envelope status {report.get('status')!r}, expected pass")
    failed, errored, worst = [], [], 0.0
    for corner in report.get("corners", []):
        for m in corner.get("measurements", []):
            if m.get("status") == "fail":
                failed.append(f"{corner['corner_id']}/{m['name']}")
            elif m.get("status") != "pass":
                errored.append(f"{corner['corner_id']}/{m['name']}")
    if failed or errored:
        raise Item5Failed(f"{what}: failing measurements {failed[:5]}, "
                          f"non-passing {errored[:5]}")
    for m in report.get("measurements", []):
        value, want = (m.get("worst_case") or {}).get("value"), exp.get(m["name"])
        if value is None or want is None:
            continue
        if want:
            worst = max(worst, abs(value - want) / abs(want))
    return {"measurements": len(report.get("measurements", [])),
            "corners": report.get("corner_count"),
            "worst_relative_deviation": worst}


def run_all(pdk_dir: str | Path, backend: str = "local",
            config: Path = DEFAULT_CONFIG, view_path: Path = DEFAULT_VIEW,
            records_dir: Path = RECORDS_DIR) -> Path:
    """Run both testbench kinds for every config cell; commit one record."""
    from ..characterize.request import cells_from_config

    git = git_provenance(REPO_ROOT)
    cells = cells_from_config(config, NETLISTS_DIR)
    view = parse_liberty(view_path.read_text())
    unverified = sorted(set(c.name for c in cells) - set(view.tables))
    if unverified:
        raise Item5Failed(f"committed view has no tables for cells {unverified}")

    record_id = allocate_record_id(REPO_ROOT, records_dir, git=git)
    rec_dir = records_dir / record_id
    rec_dir.mkdir(parents=True)

    summary: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="sg13g2-item5-") as tmp:
        for cell in cells:
            arcs = arcs_for(cell)
            for kind in KINDS:
                base = rec_dir / f"{cell.name}.{kind}"
                ref = os.path.relpath(NETLISTS_DIR / f"{cell.name}.spice", rec_dir)
                if kind == "timing":
                    netlist = build_timing_netlist(cell, arcs, view, ref)
                    request, targets = build_timing_request_with_targets(cell, arcs, view, pdk_dir)
                else:
                    supply = _config_supply(config)
                    netlist = build_function_netlist(cell, ref, supply)
                    request, targets = build_function_request_with_targets(cell, pdk_dir, supply)
                (rec_dir / f"{base.name}.spice").write_text(netlist)
                (rec_dir / f"{base.name}.request.json").write_text(
                    json.dumps(request, indent=2) + "\n")
                report_text = run_klt_sim(rec_dir / f"{base.name}.request.json",
                                          backend, Path(tmp) / f"{cell.name}.{kind}")
                (rec_dir / f"{base.name}.report.json").write_text(report_text)
                report = json.loads(report_text)
                grade = _grade(report, targets, f"{cell.name}.{kind}")
                grade.update({"cell": cell.name, "kind": kind,
                              "file": os.path.relpath(
                                  rec_dir / f"{base.name}.report.json", REPO_ROOT),
                              "content_hash": report["provenance"]["input"]["content_hash"],
                              "corner_id": report["corners"][0]["corner_id"],
                              "engine": f"{report['environment']['engine']}-"
                                        f"{report['environment']['engine_version']}"})
                summary.append(grade)

    (records_dir / f"{record_id}.md").write_text(_render(record_id, git, summary))
    return records_dir / f"{record_id}.md"


def _config_supply(config: Path) -> float:
    return float(json.loads(Path(config).read_text())["process"]["supply_v"])


def _render(record_id: str, git: dict, summary: list[dict]) -> str:
    sim = next((s["engine"] for s in summary), "unknown")
    lines = [
        f"# {record_id}", "",
        "**Kind**: corner-matrix (klt sim envelopes, T1 item 5 [analog], spec row 9)",
        f"**Repo commit**: {commit_stamp(git)}", "",
        f"**Notes**: klt {klt_version().removeprefix('klt ')}, simulator {sim}; logical function",
        "at the rails and delay/transition agreement with the committed Liberty view",
        f"`{DEFAULT_VIEW.relative_to(REPO_ROOT)}` at every (input transition, output load)",
        "grid point, TT / 1.20 V / 25 C. Cell netlists are the committed generated files",
        "under `layout/lvs/netlists/` (included, not copied). Envelope list with the",
        "manifest citation shape:", "",
    ]
    for s in summary:
        lines.append(
            f"- `{s['file']}` ({s['cell']} {s['kind']}): {s['measurements']} measurements x"
            f" {s['corners']} corner, pass; worst deviation vs the view"
            f" {s['worst_relative_deviation']:.4%}; corner `{s['corner_id']}`;"
            f" provenance.input.content_hash `{s['content_hash']}`, rows `[\"{SPEC_ROW}\"]`"
        )
    lines += ["", "## Citations (manifest evidence entries)", "",
              "```json", json.dumps(
                  [{"file": s["file"], "content_hash": s["content_hash"], "rows": [SPEC_ROW]}
                   for s in summary], indent=2), "```", ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python3 -m sim.item5")
    ap.add_argument("--pdk-dir", default=os.environ.get("SG13G2_PDK_PATH") or
                    os.path.join(os.environ.get("PDK_ROOT", ""), "ihp-sg13g2"))
    ap.add_argument("--backend", default="local", choices=["local", "batch"])
    args = ap.parse_args(argv)
    print(run_all(args.pdk_dir, backend=args.backend))
    return 0
