"""Run ``klt characterize`` and append the raw measurements as an evidence record.

Single corner per invocation. Multi-corner (FF/SS) is one invocation per corner
with ``--backend batch`` -- never a local loop (host rule). Records are
append-only: a new run mints a new record id; nothing is overwritten.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

from ..harness.evidence import CharacterizationExtensions
from ..harness.report import allocate_record_id, git_provenance
from .request import (LIBRARY_NAME, CellSpec, build_library_request, build_request,
                      cells_from_config)

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
RECORDS_DIR = HERE / "records"

TABLES = ("cell_rise", "cell_fall", "rise_transition", "fall_transition", "rise_power", "fall_power")


class CharacterizeFailed(RuntimeError):
    pass


def klt_version() -> str:
    try:
        out = subprocess.run(["klt", "--version"], capture_output=True, text=True, check=False)
    except FileNotFoundError:  # tool-free environments (CI) have no klt
        return "unavailable"
    return (out.stdout or out.stderr).strip() or "unknown"


def run_klt(request: dict, backend: str = "local", workdir: Path | None = None,
            lib_path: Path | None = None) -> dict:
    """Write ``request`` to a scratch dir, run klt, return the parsed JSON response.

    Raises :class:`CharacterizeFailed` loudly on a non-zero exit or unparsable output
    (e.g. a missing cell/arc) -- nothing is recorded in that case.
    """
    scratch = Path(workdir or tempfile.mkdtemp(prefix="klt-characterize-"))
    scratch.mkdir(parents=True, exist_ok=True)
    req_path = scratch / "request.json"
    req_path.write_text(json.dumps(request, indent=2) + "\n")
    cmd = ["klt", "characterize", "--format", "json", "--backend", backend,
           "-o", str(scratch / "out"), str(req_path)]
    if lib_path is not None:
        cmd[-1:-1] = ["--lib", str(lib_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise CharacterizeFailed(
            f"klt characterize exited {proc.returncode}: {(proc.stdout + proc.stderr).strip()[:2000]}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise CharacterizeFailed(f"klt characterize emitted unparsable JSON: {exc}") from exc


def extract_arcs(response: dict, cell: CellSpec) -> list[dict]:
    """Per-arc raw values from the response; fails loudly if the cell/arcs are absent."""
    entries = [e for e in response.get("cells") or [] if e["cell"]["name"] == cell.name]
    if not entries:
        raise CharacterizeFailed(f"cell {cell.name!r} missing from klt response")
    arcs = []
    for arc in entries[0].get("arcs") or []:
        arcs.append({
            "related_pin": arc["related_pin"],
            "output_pin": arc["output_pin"],
            "timing_sense": arc["timing_sense"],
            "side_inputs": arc.get("side_inputs", {}),
            **{t: arc[t]["values"] for t in TABLES if t in arc},
        })
    if not arcs:
        raise CharacterizeFailed(f"cell {cell.name!r} has no timing arcs in klt response")
    missing = [t for a in arcs for t in TABLES[:4] if t not in a]
    if missing:
        raise CharacterizeFailed(f"klt response lacks required tables: {sorted(set(missing))}")
    return arcs


def build_record_data(response: dict, cell: CellSpec, backend: str) -> dict:
    prov = response.get("provenance") or {}
    return {
        "cell": cell.name,
        "netlist_provenance": f"netlist supplied to klt characterize: {cell.netlist}",
        "corner": response["corner"],
        "backend": backend,
        "klt": {"version": klt_version(), "provenance_version": prov.get("klt_version"),
                "provenance": prov},
        "axes": {
            "input_transition_ns": response["grid"]["input_transition_ns"],
            "output_load_pf": response["grid"]["output_load_pf"],
        },
        "units": response.get("units", {}),
        "arcs": extract_arcs(response, cell),
        "leakage": next((e.get("leakage") for e in response.get("cells") or []
                         if e["cell"]["name"] == cell.name), None),
    }


def _when(side_inputs: dict) -> str:
    return " & ".join(f"{k}={v}" for k, v in sorted(side_inputs.items()))


def evidence_for(data: dict) -> list[CharacterizationExtensions]:
    """One validated extension per arc and per (slew, load) grid point.

    The scalar fields summarise the rise/fall tables: delay and transition are
    the worse (larger) of the two edges, energy is the Liberty internal energy
    of one full cycle (rise_power + fall_power). The full tables stay in the
    record's Data block.
    """
    corner = data["corner"]["name"]
    slews = data["axes"]["input_transition_ns"]
    loads = data["axes"]["output_load_pf"]
    exts = []
    for arc in data["arcs"]:
        missing = [t for t in ("rise_power", "fall_power") if t not in arc]
        if missing:
            raise CharacterizeFailed(
                f"arc {arc['related_pin']}->{arc['output_pin']} lacks energy tables: {missing}"
            )
        for i, slew in enumerate(slews):
            for j, load in enumerate(loads):
                ext = CharacterizationExtensions(
                    record_kind="characterization",
                    data_provenance="simulated",
                    cell=data["cell"],
                    arc_related_pin=arc["related_pin"],
                    arc_when=_when(arc["side_inputs"]),
                    arc_sense=arc["timing_sense"],
                    input_slew_ns=slew,
                    output_load_pf=load,
                    delay_ns=max(arc["cell_rise"][i][j], arc["cell_fall"][i][j]),
                    transition_ns=max(arc["rise_transition"][i][j], arc["fall_transition"][i][j]),
                    energy_pj=arc["rise_power"][i][j] + arc["fall_power"][i][j],
                    corner=corner,
                    netlist_provenance=data["netlist_provenance"],
                )
                ext.validate()
                exts.append(ext)
    return exts


def render(record_id: str, git: dict, data: dict, exts: list[CharacterizationExtensions]) -> str:
    """``data`` is one cell's data, or ``{"cells": [per-cell data...], ...}`` for a library."""
    if "cells" in data:
        data = {**data, **{k: v for k, v in data["cells"][0].items() if k not in data}}
    lines = [f"# {record_id}", "", "**Kind**: characterization (raw klt characterize measurements)",
             f"**Repo commit**: {git['commit']}{' (dirty)' if git['dirty'] else ''}", ""]
    lines += [f"**Notes**: klt {data['klt']['version']}, backend {data['backend']}; "
              "delay/transition = worse of rise/fall, energy = rise + fall internal energy.", ""]
    for ext in exts:
        lines += [f"### {ext.cell} {ext.arc_related_pin} slew {ext.input_slew_ns} ns, load {ext.output_load_pf} pF",
                  *ext.render_lines(), ""]
    lines += ["", "## Data", "", "```json", json.dumps(data, indent=2, sort_keys=True), "```", ""]
    return "\n".join(lines)


def record(data: dict, records_dir: Path = RECORDS_DIR, repo_root: Path = REPO_ROOT) -> Path:
    """Append one record. Never overwrites: exclusive-create, new id on collision.

    ``data`` is one cell's data, or a library ``{"cells": [...]}`` (one record per run).
    """
    records_dir.mkdir(parents=True, exist_ok=True)
    git = git_provenance(repo_root)
    exts = [e for d in data.get("cells", [data]) for e in evidence_for(d)]
    while True:
        record_id = allocate_record_id(repo_root, records_dir, git=git)
        path = records_dir / f"{record_id}.md"
        try:
            with open(path, "x") as fh:
                fh.write(render(record_id, git, {**data, "record_id": record_id}, exts))
            return path
        except FileExistsError:  # raced: mint another
            continue


def characterize_and_record(cell: CellSpec, corner: str, pdk_dir, backend: str = "local",
                            records_dir: Path = RECORDS_DIR, **axes) -> Path:
    response = run_klt(build_request(cell, corner, pdk_dir, **axes), backend=backend)
    return record(build_record_data(response, cell, backend), records_dir=records_dir)


DEFAULT_CONFIG = REPO_ROOT / "layout" / "example_config.json"
DEFAULT_LIB = REPO_ROOT / "views" / f"{LIBRARY_NAME}.lib"


def generate_netlists(config: Path, out: Path) -> None:
    """Emit the config's SPICE with the repo generator (not the committed ``demo_*``)."""
    proc = subprocess.run(
        ["python3", str(REPO_ROOT / "design" / "gen_netlists.py"), "--config", str(config),
         "--out", str(out)], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise CharacterizeFailed(f"gen_netlists failed: {(proc.stdout + proc.stderr).strip()[:2000]}")


def provenance_for(config: Path, corner: dict, data: dict) -> dict:
    git = git_provenance(REPO_ROOT)
    rel = os.path.relpath(config, REPO_ROOT)
    return {
        "library": LIBRARY_NAME,
        "klt_version": data["klt"]["version"],
        "repo_commit": git["commit"] + (" (dirty)" if git["dirty"] else ""),
        "corner": corner,
        "config": rel,
        "config_sha256": hashlib.sha256(Path(config).read_bytes()).hexdigest(),
        "cells": [c["cell"] for c in data["cells"]],
        "evidence_record": data.get("record_id"),
    }


def characterize_library(config: Path, corner: str, pdk_dir, lib_path: Path = DEFAULT_LIB,
                         backend: str = "local", records_dir: Path = RECORDS_DIR) -> Path:
    """Characterize every cell of ``config`` into one committed ``.lib`` + sidecar + record."""
    with tempfile.TemporaryDirectory(prefix="sg13g2-lib-") as tmp:
        tmp = Path(tmp)
        generate_netlists(config, tmp / "netlists")
        cells = cells_from_config(config, tmp / "netlists")
        request = build_library_request(cells, corner, pdk_dir)
        response = run_klt(request, backend=backend, workdir=tmp / "work", lib_path=lib_path)
    per_cell = [build_record_data(response, c, backend) for c in cells]
    data = {**per_cell[0], "cells": per_cell,
            "netlist_provenance": f"design/gen_netlists.py --config {os.path.relpath(config, REPO_ROOT)}"}
    path = record(data, records_dir=records_dir)
    data["record_id"] = path.stem
    prov = provenance_for(config, response["corner"], data)
    Path(str(lib_path) + ".provenance").write_text(json.dumps(prov, indent=2, sort_keys=True) + "\n")
    return path


def main(argv=None) -> int:
    import argparse
    from .request import DEFAULT_CORNER, SG13G2_INV_1
    ap = argparse.ArgumentParser(prog="python3 -m sim.characterize")
    ap.add_argument("--pdk-dir", default=os.environ.get("SG13G2_PDK_PATH") or
                    os.path.join(os.environ.get("PDK_ROOT", ""), "ihp-sg13g2"))
    ap.add_argument("--backend", default="local")
    ap.add_argument("--library", action="store_true",
                    help=f"characterize every cell of --config into {DEFAULT_LIB.relative_to(REPO_ROOT)}")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--lib", type=Path, default=DEFAULT_LIB)
    args = ap.parse_args(argv)
    if args.library:
        print(characterize_library(args.config.resolve(), DEFAULT_CORNER, args.pdk_dir,
                                   lib_path=args.lib.resolve(), backend=args.backend))
        return 0
    print(characterize_and_record(SG13G2_INV_1, DEFAULT_CORNER, args.pdk_dir, backend=args.backend))
    return 0
