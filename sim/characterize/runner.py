"""Run ``klt characterize`` and append the raw measurements as an evidence record.

Single corner per invocation. Multi-corner (FF/SS) is one invocation per corner
with ``--backend batch`` -- never a local loop (host rule). Records are
append-only: a new run mints a new record id; nothing is overwritten.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from ..harness.evidence import CharacterizationExtensions
from ..harness.report import allocate_record_id, git_provenance
from .request import CellSpec, build_request

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


def run_klt(request: dict, backend: str = "local", workdir: Path | None = None) -> dict:
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
        "leakage": (response.get("cells") or [{}])[0].get("leakage"),
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
    lines = [f"# {record_id}", "", "**Kind**: characterization (raw klt characterize measurements)",
             f"**Repo commit**: {git['commit']}{' (dirty)' if git['dirty'] else ''}", ""]
    lines += [f"**Notes**: klt {data['klt']['version']}, backend {data['backend']}; "
              "delay/transition = worse of rise/fall, energy = rise + fall internal energy.", ""]
    for ext in exts:
        lines += [f"### {ext.arc_related_pin} slew {ext.input_slew_ns} ns, load {ext.output_load_pf} pF",
                  *ext.render_lines(), ""]
    lines += ["", "## Data", "", "```json", json.dumps(data, indent=2, sort_keys=True), "```", ""]
    return "\n".join(lines)


def record(data: dict, records_dir: Path = RECORDS_DIR, repo_root: Path = REPO_ROOT) -> Path:
    """Append one record. Never overwrites: exclusive-create, new id on collision."""
    records_dir.mkdir(parents=True, exist_ok=True)
    git = git_provenance(repo_root)
    exts = evidence_for(data)
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


def main(argv=None) -> int:
    import argparse
    from .request import DEFAULT_CORNER, SG13G2_INV_1
    ap = argparse.ArgumentParser(prog="python3 -m sim.characterize")
    ap.add_argument("--pdk-dir", default=os.environ.get("SG13G2_PDK_PATH") or
                    os.path.join(os.environ.get("PDK_ROOT", ""), "ihp-sg13g2"))
    ap.add_argument("--backend", default="local")
    args = ap.parse_args(argv)
    print(characterize_and_record(SG13G2_INV_1, DEFAULT_CORNER, args.pdk_dir, backend=args.backend))
    return 0
