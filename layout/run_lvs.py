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
netlists that differ from a fresh regeneration.

Exit codes: 0 every cell `match`; 1 tooling error (klt missing a command in
layout/toolchain.json, klt failed) or `--check` drift; 2 invalid config;
4 reports written but at least one cell is not `match` (the reports are the
evidence; nothing is hidden or retried).
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import toolchain_pin  # noqa: E402

GEN_NETLISTS = HERE.parent / "design" / "gen_netlists.py"
DECK = "sg13g2"


def relpath(p):
    return os.path.relpath(p)


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


def cell_names(config_path):
    return [c["name"] for c in json.loads(pathlib.Path(config_path).read_text())["cells"]]


def gen_netlists(config, outdir):
    return subprocess.run([sys.executable, str(GEN_NETLISTS), "--config", str(config),
                           "--out", str(outdir)], capture_output=True, text=True)


def run_klt_lvs(request, report_path):
    return subprocess.run(["klt", "lvs", "-", "--format", "json", "-o", str(report_path)],
                          input=json.dumps(request), capture_output=True, text=True)


def do_check(cells, out, netlists, config):
    bad = []
    with tempfile.TemporaryDirectory() as tmp:
        r = gen_netlists(config, tmp)
        if r.returncode != 0:
            print(r.stderr, file=sys.stderr)
            return 1
        for cell in cells:
            fresh = pathlib.Path(tmp) / f"{cell}.spice"
            have = pathlib.Path(netlists) / f"{cell}.spice"
            if not have.exists() or have.read_bytes() != fresh.read_bytes():
                bad.append(f"{cell}: reference netlist missing or differs from generator output")
            rep = pathlib.Path(out) / f"{cell}.json"
            if not rep.exists():
                bad.append(f"{cell}: report {rep} missing")
                continue
            c = subprocess.run(["klt", "lvs", "--check", str(rep)], capture_output=True, text=True)
            if c.returncode != 0:
                bad.append(f"{cell}: klt lvs --check exit {c.returncode}: {c.stdout.strip()[:200]}")
    stray = sorted(p.name for p in pathlib.Path(out).glob("*.json") if p.stem not in cells)
    bad += [f"stray report {s}" for s in stray]
    for b in bad:
        print(b, file=sys.stderr)
    return 1 if bad else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", required=True)
    ap.add_argument("--gds")
    ap.add_argument("--out")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    cfgdir = pathlib.Path(a.config).resolve().parent
    gds = pathlib.Path(a.gds) if a.gds else cfgdir / "gds"
    out = pathlib.Path(a.out) if a.out else cfgdir / "lvs"
    netlists = out / "netlists"
    try:
        cells = cell_names(a.config)
    except (OSError, ValueError, KeyError) as e:
        print(f"run_lvs: invalid config: {e}", file=sys.stderr)
        return 2
    try:
        missing = toolchain_pin.check_commands()
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"run_lvs: cannot run klt: {e}", file=sys.stderr)
        return 1
    if missing:
        print(f"run_lvs: klt lacks {missing}; install: {toolchain_pin.install_hint()}",
              file=sys.stderr)
        return 1
    if a.check:
        return do_check(cells, out, netlists, a.config)
    r = gen_netlists(a.config, netlists)
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        return 2 if r.returncode == 2 else 1
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
