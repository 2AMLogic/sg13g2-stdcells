#!/usr/bin/env python3
"""Run `klt lvs` on every generated cell against its generator netlist.

Usage: run_lvs.py --config CONFIG.json [--gds DIR] [--out DIR] [--check]

For each cell in CONFIG the runner
  1. regenerates the reference netlist with design/gen_netlists.py from the
     SAME config (written to <out>/netlists/<cell>.spice, committed so the
     reports stay re-checkable),
  2. runs `klt lvs` (inline extraction with the sg13g2 deck, reference form
     `subckt-call`, `options.combine_devices` on because the generator folds a
     device into F parallel fingers) on <gds>/<cell>.gds, writing
     <out>/<cell>.json.

Defaults: --gds <config dir>/gds, --out <config dir>/lvs. Paths are given to
klt relative to the current directory, so run from the repo root.

`--check` runs `klt lvs --check` (cheap mode: re-hash the layout and reference
netlist recorded in each report) and fails on stale/missing/stray reports or
netlists that are not fresh: the reference netlists are checked with the
generator's own `--check` (design/gen_netlists.py) — the same freshness gate
CI runs — so a missing, edited, stray or line-ending-rewritten netlist fails
here exactly as it fails there, and both drifts are reported in one run.

Exit codes: 0 every cell `match`; 1 tooling error (klt missing a command in
layout/toolchain.json, klt failed) or `--check` drift; 2 invalid config;
4 reports written but at least one cell is not `match` (the reports are the
evidence; nothing is hidden or retried).
"""
import contextlib
import io
import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import toolchain_pin  # noqa: E402

sys.path.insert(0, str(HERE.parent / "design"))
import gen_netlists as gn  # noqa: E402

DECK = toolchain_pin.DECK
relpath = toolchain_pin.relpath
cell_names = toolchain_pin.cell_names


def build_request(cell, gds_dir, netlist_dir):
    """The `klt lvs` request for one cell (pure; paths relative to cwd)."""
    return {
        "schema": "klt.lvs.request/1",
        "engine": "klayout",
        "layout": {
            "file": relpath(pathlib.Path(gds_dir) / f"{cell}.gds"),
            "deck": DECK,
            "top": cell,
        },
        "reference": {
            "netlist": relpath(pathlib.Path(netlist_dir) / f"{cell}.spice"),
            "top": cell,
            "form": "subckt-call",
            "deck": DECK,
        },
        # layout/gen_layouts.py folds a device into F parallel fingers, so
        # extraction sees F transistors on one gate net where the reference
        # netlist carries a single device with ng=F. Combining parallel devices
        # makes the comparison see the same device the netlist declares; it does
        # not loosen what is compared (the nets are already 1:1 without it).
        "options": {"combine_devices": True},
    }


def power_ok(report):
    return report.get("power_connectivity", {}).get("status") != "mismatch"


def summarize(cell, report):
    """One line per cell from a klt lvs JSON report (pure)."""
    return "{}: {} (power_connectivity={}, errors={})".format(
        cell, report.get("status"),
        report.get("power_connectivity", {}).get("status"), report.get("error_count"))


def gen_netlists(config, outdir, *, check=False):
    """design/gen_netlists.py in-process on `config` into `outdir` (`--check`
    with `check`): its stdout is swallowed, its diagnostics go straight to
    stderr, and its exit code (0 ok, 1 drift, 2 invalid config) is returned."""
    argv = ["--config", str(config), "--out", str(outdir)] + (["--check"] if check else [])
    with contextlib.redirect_stdout(io.StringIO()):
        return gn.main(argv)


def check_report(report_path):
    return subprocess.run(["klt", "lvs", "--check", str(report_path)], capture_output=True, text=True)


def run_klt_lvs(request, report_path):
    return subprocess.run(["klt", "lvs", "-", "--format", "json", "-o", str(report_path)],
                          input=json.dumps(request), capture_output=True, text=True)


def do_check(cells, out, netlists, config):
    bad = []
    if gen_netlists(config, netlists, check=True) != 0:
        bad.append("netlists: reference netlists not fresh (generator diagnostics above)")
    for cell in cells:
        rep = pathlib.Path(out) / f"{cell}.json"
        bad += toolchain_pin.check_report_fresh(cell, rep, "lvs", check_report)
    bad += toolchain_pin.stray_reports(out, cells)
    return toolchain_pin.emit_check_errors(bad)


def main(argv=None):
    a, _, gds, out = toolchain_pin.parse_runner_args(__doc__, "lvs", argv)
    netlists = out / "netlists"
    try:
        cells = cell_names(a.config)
    except (OSError, ValueError, KeyError) as e:
        print(f"run_lvs: invalid config: {e}", file=sys.stderr)
        return 2
    preflight = toolchain_pin.ensure_commands("run_lvs")
    if preflight:
        return preflight
    if a.check:
        return do_check(cells, out, netlists, a.config)
    rc = gen_netlists(a.config, netlists)
    if rc != 0:
        return 2 if rc == 2 else 1
    out.mkdir(parents=True, exist_ok=True)
    worst = 0
    for cell in cells:
        rep = out / f"{cell}.json"
        r = run_klt_lvs(build_request(cell, gds, netlists), rep)
        if r.returncode not in (0, 3) or not rep.exists():
            print(f"run_lvs: klt lvs failed for {cell} (exit {r.returncode}):\n"
                  f"{r.stdout}{r.stderr}", file=sys.stderr)
            return 1
        report = json.loads(rep.read_text())
        print(summarize(cell, report))
        if report.get("status") != "match" or not power_ok(report):
            worst = 4
    return worst


if __name__ == "__main__":
    sys.exit(main())
