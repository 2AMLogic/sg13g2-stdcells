"""Run ``klt characterize`` and append the raw measurements as an evidence record.

Single corner per invocation. Multi-corner (FF/SS) is one invocation per corner
with ``--backend batch`` -- never a local loop (host rule). Records are
append-only: a new run mints a new record id; nothing is overwritten.

Every run captures the PDK revision of its ``--pdk-dir`` checkout first
(:func:`pdk_provenance`): the IHP-Open-PDK commit, written into the record
header and the view's provenance sidecar. A PDK directory that is not a
clean IHP-Open-PDK git checkout refuses the run before anything is written.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from ..harness.evidence import CharacterizationExtensions
from ..harness.report import allocate_record_id, commit_stamp, git_provenance
from .request import (DEFAULT_CORNER, CellSpec, build_library_request, cells_from_config,
                      library_view_name)

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
RECORDS_DIR = HERE / "records"

TABLES = ("cell_rise", "cell_fall", "rise_transition", "fall_transition", "rise_power", "fall_power")

#: Host rule: every batch ``klt sim`` submit -- and a batch ``klt characterize``
#: submit is one underneath -- must wait up to this long for fleet capacity
#: instead of failing the step on ``batch_no_capacity``. ``klt`` rejects the
#: flag on ``--backend local``, so it is added for batch submits only.
BATCH_CAPACITY_WAIT_S = 600


class CharacterizeFailed(RuntimeError):
    pass


def klt_version() -> str:
    try:
        out = subprocess.run(["klt", "--version"], capture_output=True, text=True, check=False)
    except FileNotFoundError:  # tool-free environments (CI) have no klt
        return "unavailable"
    return (out.stdout or out.stderr).strip() or "unknown"


#: The PDK this library is characterized against, and the origin-URL marker a
#: ``--pdk-dir`` checkout must carry for :func:`pdk_provenance` to accept it.
#: The remote check is what keeps a PDK copied inside another git tree (this
#: repo's, for instance) from acquiring the enclosing project's SHA: the copy
#: resolves to a repository whose origin is not IHP-Open-PDK, and the capture
#: fails loudly instead of stamping a revision the PDK files never had.
PDK_NAME = "IHP-Open-PDK"
_PDK_ORIGIN_MARKER = "ihp-open-pdk"
_HEX_SHA_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


def pdk_provenance(pdk_dir) -> dict:
    """``{"name": PDK_NAME, "revision": <full commit SHA>}`` of the ``--pdk-dir`` checkout.

    Captured once per run, before klt is called or anything is written, so a
    failing capture leaves no partial artifacts. Refuses to run
    (:class:`CharacterizeFailed`) when the revision cannot be recorded
    honestly:

    - ``pdk_dir`` is not inside a git work tree, or the work tree has no
      commit checked out (a plain unpacked tarball has no revision at all);
    - the enclosing repository's ``origin`` does not name IHP-Open-PDK -- a
      PDK copied into an unrelated git tree must never acquire that tree's
      SHA, and a mirror of unknown provenance is not a pin;
    - the checkout is dirty -- modified or untracked content means the
      simulated models are not the ones the recorded commit describes.

    The variant directory may be a subdirectory of the checkout (the usual
    ``<clone>/ihp-sg13g2`` layout): git resolves from it, the SHA and the
    cleanliness are the whole repository's.
    """
    pdk = Path(pdk_dir).resolve()

    def git(*args: str) -> str:
        try:
            proc = subprocess.run(["git", "-C", str(pdk), *args],
                                  capture_output=True, text=True, check=False)
        except OSError as exc:
            raise CharacterizeFailed(f"PDK revision capture failed: {exc}") from exc
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout).strip().splitlines()
            raise CharacterizeFailed(
                f"cannot determine the PDK revision of {pdk}: git {' '.join(args)} "
                f"exited {proc.returncode}"
                + (f": {detail[-1]}" if detail else ""))
        return proc.stdout.strip()

    if git("rev-parse", "--is-inside-work-tree") != "true":
        raise CharacterizeFailed(
            f"cannot determine the PDK revision of {pdk}: not inside a git work "
            f"tree -- check out IHP-Open-PDK at a named commit and pass its "
            f"ihp-sg13g2 variant directory")
    revision = git("rev-parse", "HEAD")
    if not _HEX_SHA_RE.fullmatch(revision):
        raise CharacterizeFailed(
            f"cannot determine the PDK revision of {pdk}: HEAD is {revision!r}, "
            f"not a commit SHA -- the checkout names no revision to record")
    origin = git("remote", "get-url", "origin")
    if _PDK_ORIGIN_MARKER not in origin.lower():
        raise CharacterizeFailed(
            f"{pdk} is inside a git repository whose origin is {origin!r}, not "
            f"an IHP-Open-PDK checkout -- a PDK copied into another project's "
            f"tree would silently stamp that project's SHA; refusing")
    if git("status", "--porcelain"):
        raise CharacterizeFailed(
            f"the IHP-Open-PDK checkout at {pdk} is dirty -- the models about "
            f"to be simulated would not be the ones commit {revision[:12]} "
            f"describes; re-checkout clean and retry")
    return {"name": PDK_NAME, "revision": revision}


def run_klt(request: dict, backend: str = "local", workdir: Path | None = None,
            lib_path: Path | None = None) -> dict:
    """Write ``request`` to a scratch dir, run klt, return the parsed JSON response.

    Raises :class:`CharacterizeFailed` loudly on a non-zero exit or unparsable output
    (e.g. a missing cell/arc) -- nothing is recorded in that case.

    When ``workdir`` is given, the caller owns scratch cleanup; the ``None``
    fallback creates a temp dir nothing reaps, so callers should pass ``workdir``.
    """
    scratch = Path(workdir or tempfile.mkdtemp(prefix="klt-characterize-"))
    scratch.mkdir(parents=True, exist_ok=True)
    req_path = scratch / "request.json"
    req_path.write_text(json.dumps(request, indent=2) + "\n")
    cmd = ["klt", "characterize", "--format", "json", "--backend", backend,
           "-o", str(scratch / "out"), str(req_path)]
    if lib_path is not None:
        cmd[-1:-1] = ["--lib", str(lib_path)]
    if backend == "batch":
        cmd[-1:-1] = ["--wait-for-capacity", str(BATCH_CAPACITY_WAIT_S)]
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


def simulator_of(response: dict, cell: CellSpec) -> dict:
    """Simulator identity for ``cell`` from the response's per-cell ``simulation`` block.

    The library/batch response deliberately nulls the top-level ``simulation``
    key, so the per-cell entry (the same lookup ``extract_arcs`` uses) is the
    only reliable source.
    """
    sim = next((e.get("simulation") for e in response.get("cells") or []
                if e["cell"]["name"] == cell.name), None) or {}
    return {"engine": sim.get("engine"), "version": sim.get("engine_version")}


def simulator_str(data: dict) -> str:
    """``engine-version`` as klt reports it (e.g. ``ngspice-47``); ``unknown`` if absent."""
    sim = data.get("simulator") or {}
    if not sim.get("engine") or not sim.get("version"):
        return "unknown"
    return f"{sim['engine']}-{sim['version']}"


def build_record_data(response: dict, cell: CellSpec, backend: str) -> dict:
    prov = response.get("provenance") or {}
    return {
        "cell": cell.name,
        "netlist_provenance": f"netlist supplied to klt characterize: {cell.netlist}",
        "corner": response["corner"],
        "backend": backend,
        "klt": {"version": klt_version(), "provenance_version": prov.get("klt_version"),
                "provenance": prov},
        "simulator": simulator_of(response, cell),
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
             f"**Repo commit**: {commit_stamp(git)}", ""]
    pdk = data.get("pdk")
    if pdk:
        lines.insert(3, f"**PDK**: {pdk['name']} @ {pdk['revision']}")
    klt_ver = str(data['klt']['version']).removeprefix("klt ")
    lines += [f"**Notes**: klt {klt_ver}, backend {data['backend']}, "
              f"simulator {simulator_str(data)}; "
              "delay/transition = worse of rise/fall, energy = rise + fall internal energy.", ""]
    for ext in exts:
        lines += [f"### {ext.cell} {ext.arc_related_pin} slew {ext.input_slew_ns} ns, load {ext.output_load_pf} pF",
                  *ext.render_lines(), ""]
    lines += ["", "## Data", "", "```json", json.dumps(data, indent=2, sort_keys=True), "```", ""]
    return "\n".join(lines)


def record(data: dict, records_dir: Path = RECORDS_DIR, repo_root: Path = REPO_ROOT,
           git: dict | None = None) -> Path:
    """Append one record. Never overwrites: exclusive-create, new id on collision.

    ``data`` is one cell's data, or a library ``{"cells": [...]}`` (one record per run).
    ``git`` is a pre-captured :func:`git_provenance` snapshot; callers that write
    other tracked artifacts around the record pass the snapshot taken before any
    write so the record's stamp describes the tree the measurement ran on.
    """
    records_dir.mkdir(parents=True, exist_ok=True)
    git = git or git_provenance(repo_root)
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


DEFAULT_CONFIG = REPO_ROOT / "layout" / "example_config.json"


def default_lib_path(corner: str = DEFAULT_CORNER) -> Path:
    """The corner-named default Liberty view path: ``views/<library_view_name>``."""
    return REPO_ROOT / "views" / f"{library_view_name(corner)}.lib"


DEFAULT_LIB = default_lib_path()


def generate_netlists(config: Path, out: Path) -> None:
    """Emit the config's SPICE with the repo generator."""
    proc = subprocess.run(
        ["python3", str(REPO_ROOT / "design" / "gen_netlists.py"), "--config", str(config),
         "--out", str(out)], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise CharacterizeFailed(f"gen_netlists failed: {(proc.stdout + proc.stderr).strip()[:2000]}")


def provenance_for(config: Path, corner: dict, data: dict, git: dict | None = None) -> dict:
    git = git or git_provenance(REPO_ROOT)
    rel = os.path.relpath(config, REPO_ROOT)
    prov = {
        "library": library_view_name(corner["name"]),
        "klt_version": data["klt"]["version"],
        "simulator": simulator_str(data),
        "repo_commit": commit_stamp(git),
        "corner": corner,
        "config": rel,
        "config_sha256": hashlib.sha256(Path(config).read_bytes()).hexdigest(),
        "cells": [c["cell"] for c in data["cells"]],
        "evidence_record": data.get("record_id"),
    }
    if data.get("pdk"):
        prov["pdk"] = data["pdk"]
    return prov


def characterize_library(config: Path, corner: str, pdk_dir, lib_path: Path | None = None,
                         backend: str = "local", records_dir: Path = RECORDS_DIR) -> Path:
    """Characterize every cell of ``config`` into one committed ``.lib`` + sidecar + record.

    The view defaults to the corner-named path under ``views/``
    (:func:`default_lib_path`), and the request's ``library.name`` is the name
    derived from the same corner -- view name and contents never disagree.

    The PDK revision is captured from the ``pdk_dir`` checkout before klt
    runs (:func:`pdk_provenance`), so a checkout that is dirty, foreign or
    not a git checkout at all refuses the run before anything is written.
    """
    pdk = pdk_provenance(pdk_dir)
    lib_path = lib_path or default_lib_path(corner)
    git = git_provenance(REPO_ROOT)
    with tempfile.TemporaryDirectory(prefix="sg13g2-lib-") as tmp:
        tmp = Path(tmp)
        generate_netlists(config, tmp / "netlists")
        cells = cells_from_config(config, tmp / "netlists")
        request = build_library_request(cells, corner, pdk_dir,
                                        library_name=library_view_name(corner))
        response = run_klt(request, backend=backend, workdir=tmp / "work", lib_path=lib_path)
    per_cell = [build_record_data(response, c, backend) for c in cells]
    data = {**per_cell[0], "cells": per_cell, "pdk": pdk,
            "netlist_provenance": f"design/gen_netlists.py --config {os.path.relpath(config, REPO_ROOT)}"}
    path = record(data, records_dir=records_dir, git=git)
    data["record_id"] = path.stem
    prov = provenance_for(config, response["corner"], data, git=git)
    Path(str(lib_path) + ".provenance").write_text(json.dumps(prov, indent=2, sort_keys=True) + "\n")
    return path


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python3 -m sim.characterize")
    ap.add_argument("--pdk-dir", default=os.environ.get("SG13G2_PDK_PATH") or
                    os.path.join(os.environ.get("PDK_ROOT", ""), "ihp-sg13g2"))
    ap.add_argument("--backend", default="local", choices=["local", "batch"])
    from ..harness.corners import CHAR_CORNER_PVT
    ap.add_argument("--corner", default=DEFAULT_CORNER, choices=list(CHAR_CORNER_PVT),
                    help="characterization corner (default: %(default)s)")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG,
                    help=f"cell config (default: {DEFAULT_CONFIG.relative_to(REPO_ROOT)})")
    ap.add_argument("--lib", type=Path, default=None,
                    help="Liberty output path (default: the corner-named view path "
                         "under views/)")
    args = ap.parse_args(argv)
    lib = args.lib or default_lib_path(args.corner)
    print(characterize_library(args.config.resolve(), args.corner, args.pdk_dir,
                               lib_path=lib.resolve(), backend=args.backend))
    return 0
