"""Freshness check for the committed Liberty view and its provenance sidecar.

`klt characterize` writes `views/<library>.lib` together with a
`<library>.lib.provenance` sidecar naming the config it was characterized from
(and that config's SHA-256), the corner, the cells, and the id of the
append-only record under `sim/characterize/records/`. Without a re-check, a
config edit or a deleted record leaves a sidecar that still *claims* to
describe the view.

This is that check. It re-derives what the sidecar claims from the files
themselves -- the library name and cell set in the `.lib` (the name both
against the sidecar's field and against the name derived from the sidecar's
corner, so a view whose name asserts one corner while its data is another is
caught -- issue #143), the corner the view
declares (the operating_conditions group name and, via the nom_* attributes
and the group, voltage and temperature; the sidecar's process-corner entry is
a name like mos_tt while the view's process attributes are numeric factors,
so process is not comparable and is left unchecked), the config's SHA-256,
and the measurement blocks of the record -- and exits non-zero naming each
disagreement, so it fails when the evidence goes stale rather than when the
evidence is merely absent. It is what `manifests/inventories/item8.analog.json`
declares as the freshness command behind its T1 item 8 citation (issue #75):
a citation whose backing command cannot fail is not evidence.

The provenance stamps themselves are checked too: a `repo_commit` marked
dirty -- on the sidecar or on the record it names -- is a disagreement,
because a measurement taken on a dirty tree is reproducible from no commit.

What it deliberately does not catch: a hand-edited `.lib` whose library name,
cell set and declared corner still agree with the sidecar. The sidecar
records no hash of the `.lib` itself, so the delay tables are not pinned and
a tampered table passes. Pinning the bytes needs `klt characterize` to record
a content hash of the view it wrote (filed upstream on the klayout-tools
tracker); until then, the claim is exactly what this module re-derives, no
more.

Run from the repo root:  python3 -m sim.characterize.check_library
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from pathlib import Path

from ..harness.report import is_dirty_stamp
from .request import LIBRARY_NAME, RequestError, library_view_name

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_LIB = REPO_ROOT / "views" / f"{LIBRARY_NAME}.lib"
RECORDS_DIR = Path(__file__).resolve().parent / "records"

_CELL_RE = re.compile(r"^\s*cell \(([A-Za-z0-9_]+)\)", re.MULTILINE)
_LIBRARY_RE = re.compile(r"^\s*library \(([A-Za-z0-9_]+)\)", re.MULTILINE)
_MEASUREMENT_BLOCK_RE = re.compile(r"^### ", re.MULTILINE)
_RECORD_FIELD_RE = re.compile(r"^- \*\*(Cell|Corner|Netlist provenance)\*\*: (.*)$", re.MULTILINE)
# The record's provenance stamp is a top-of-file `**Repo commit**: <sha>[ (dirty)]`
# line, not a `- **Key**: value` bullet, so _RECORD_FIELD_RE does not match it.
_RECORD_COMMIT_STAMP_RE = re.compile(r"^\*\*Repo commit\*\*: (.*)$", re.MULTILINE)
_SPICE_PATH_RE = re.compile(r"\S+\.spice\b")
# The generated operating_conditions group is flat (attributes only, no
# nested groups), so the body is matched as a run of non-`}` characters.
_OPERATING_CONDITIONS_RE = re.compile(
    r"^\s*operating_conditions\s*\((?P<name>[A-Za-z0-9_]+)\)\s*\{(?P<body>[^}]*)\}",
    re.MULTILINE)
_OC_ATTR_RE = re.compile(
    r"^\s*(?P<key>process|temperature|voltage)\s*:\s*(?P<value>[^;]+);", re.MULTILINE)
_NOM_ATTR_RE = re.compile(
    r"^\s*nom_(?P<key>process|temperature|voltage)\s*:\s*(?P<value>[^;]+);", re.MULTILINE)

REQUIRED_KEYS = ("library", "corner", "config", "config_sha256", "cells",
                 "evidence_record", "repo_commit")


def cells_in_lib(text: str) -> list[str]:
    return _CELL_RE.findall(text)


def library_name_in_lib(text: str) -> str | None:
    found = _LIBRARY_RE.search(text)
    return found.group(1) if found else None


def operating_conditions_in_lib(text: str) -> list[dict[str, str]]:
    """The declared ``operating_conditions`` groups: name plus flat attributes."""
    return [{"name": m.group("name"), **dict(_OC_ATTR_RE.findall(m.group("body")))}
            for m in _OPERATING_CONDITIONS_RE.finditer(text)]


def nom_attributes_in_lib(text: str) -> dict[str, str]:
    """The ``nom_process`` / ``nom_temperature`` / ``nom_voltage`` attributes."""
    return {f"nom_{key}": value for key, value in _NOM_ATTR_RE.findall(text)}


def _number(value) -> float | None:
    """Parse a Liberty attribute value or sidecar number as a float."""
    if isinstance(value, bool):
        return None
    try:
        return float(str(value).strip().strip('"'))
    except ValueError:
        return None


def _measurement_blocks(record_text: str) -> list[dict[str, str]]:
    """One ``{field: value}`` dict per ``###`` measurement block of a record.

    Only the ``**Cell**`` / ``**Corner**`` / ``**Netlist provenance`` field lines
    inside a block are extracted, so a mention of a cell or corner anywhere else
    in the record (prose, a provenance path, the trailing ``## Data`` JSON) does
    not count as a measurement.
    """
    return [dict(_RECORD_FIELD_RE.findall(block))
            for block in _MEASUREMENT_BLOCK_RE.split(record_text)[1:]]


def _record_commit_stamp(record_text: str) -> str | None:
    """The record's ``**Repo commit**`` stamp, or None if the line is absent."""
    found = _RECORD_COMMIT_STAMP_RE.search(record_text)
    return found.group(1).strip() if found else None


def check(lib_path: Path, repo_root: Path = REPO_ROOT,
          records_dir: Path | None = None) -> list[str]:
    """Return a list of human-readable drift findings; empty means fresh."""
    records_dir = records_dir if records_dir is not None else RECORDS_DIR
    problems: list[str] = []
    sidecar_path = Path(str(lib_path) + ".provenance")

    if not lib_path.is_file():
        return [f"{_rel(lib_path, repo_root)}: Liberty view is missing"]
    if not sidecar_path.is_file():
        return [f"{_rel(sidecar_path, repo_root)}: provenance sidecar is missing"]

    try:
        prov = json.loads(sidecar_path.read_text())
    except json.JSONDecodeError as exc:
        return [f"{_rel(sidecar_path, repo_root)}: not parseable JSON ({exc})"]
    if not isinstance(prov, dict):
        return [f"{_rel(sidecar_path, repo_root)}: expected a JSON object"]

    missing = [k for k in REQUIRED_KEYS if k not in prov]
    if missing:
        return [f"{_rel(sidecar_path, repo_root)}: sidecar lacks {', '.join(missing)}"]

    lib_text = lib_path.read_text()

    # 1. The .lib declares the library the sidecar names.
    declared = library_name_in_lib(lib_text)
    if declared != prov["library"]:
        problems.append(
            f"{_rel(lib_path, repo_root)}: declares library {declared!r}, "
            f"sidecar names {prov['library']!r}")

    # 1b. The declared name is the one the sidecar's corner derives -- the one
    #     relation check 1 cannot span, since the sidecar's library field is
    #     stamped from the writer's own name choice. A view whose data says ff
    #     while its name still says tt_1p20v_25c is a mislabel either way.
    corner = prov["corner"]
    if isinstance(corner, dict) and corner.get("name") is not None:
        try:
            expected = library_view_name(corner["name"])
        except RequestError:
            problems.append(
                f"{_rel(sidecar_path, repo_root)}: names corner {corner['name']!r}, "
                f"not a characterization corner -- no library name can be derived")
        else:
            if declared != expected:
                problems.append(
                    f"{_rel(lib_path, repo_root)}: declares library {declared!r}, "
                    f"but corner {corner['name']!r} derives {expected!r}")

    # 2. The .lib holds exactly the cells the sidecar claims were characterized.
    in_lib = sorted(cells_in_lib(lib_text))
    claimed = sorted(prov["cells"]) if isinstance(prov["cells"], list) else []
    if in_lib != claimed:
        problems.append(
            f"{_rel(lib_path, repo_root)}: holds cells {in_lib}, "
            f"sidecar claims {claimed}")

    # 3. The .lib declares the corner the sidecar says it was characterized
    #    at: the operating_conditions group name, plus voltage and temperature
    #    both as nom_* attributes and inside the group. The sidecar's
    #    corner.process is a process-corner name (e.g. mos_tt) while the
    #    view's process attributes are numeric process factors, so process is
    #    not comparable and is deliberately left unchecked.
    corner = prov["corner"]
    if isinstance(corner, dict):
        groups = operating_conditions_in_lib(lib_text)
        noms = nom_attributes_in_lib(lib_text)
        corner_name = corner.get("name")
        if corner_name is not None and corner_name not in {g["name"] for g in groups}:
            declared = ", ".join(g["name"] for g in groups)
            if declared:
                problems.append(
                    f"{_rel(lib_path, repo_root)}: declares operating_conditions "
                    f"group(s) {declared}, sidecar names corner {corner_name!r}")
            else:
                problems.append(
                    f"{_rel(lib_path, repo_root)}: declares no operating_conditions "
                    f"group, sidecar names corner {corner_name!r}")
        group = next((g for g in groups if g["name"] == corner_name), None)
        for sidecar_key, group_key, nom_key in (
                ("supply_v", "voltage", "nom_voltage"),
                ("temperature_c", "temperature", "nom_temperature")):
            claimed_value = corner.get(sidecar_key)
            if claimed_value is None:
                continue
            sources: list[tuple[str, object]] = [(nom_key, noms.get(nom_key))]
            if group is not None:
                sources.append((f"operating_conditions({group['name']}) {group_key}",
                                group.get(group_key)))
            for source, actual in sources:
                if actual is None:
                    problems.append(
                        f"{_rel(lib_path, repo_root)}: declares no {source}, "
                        f"sidecar was characterized at {sidecar_key} {claimed_value}")
                    continue
                actual_n, claimed_n = _number(actual), _number(claimed_value)
                if (actual_n is None or claimed_n is None
                        or not math.isclose(actual_n, claimed_n,
                                            rel_tol=1e-9, abs_tol=1e-9)):
                    problems.append(
                        f"{_rel(lib_path, repo_root)}: {source} {actual} but "
                        f"the sidecar was characterized at {sidecar_key} {claimed_value}")

    # 4. The config is still the one that was characterized, byte for byte.
    config_path = repo_root / prov["config"]
    if not config_path.is_file():
        problems.append(f"{prov['config']}: config named by the sidecar is missing")
    else:
        actual = hashlib.sha256(config_path.read_bytes()).hexdigest()
        if actual != prov["config_sha256"]:
            problems.append(
                f"{prov['config']}: sha256 {actual} but the sidecar pins "
                f"{prov['config_sha256']} -- the config changed since this view "
                f"was characterized; regenerate it")

    # 5. The evidence record still exists and still speaks for these cells and corner.
    record_id = prov["evidence_record"]
    record_path = records_dir / f"{record_id}.md"
    if not record_path.is_file():
        problems.append(
            f"{_rel(record_path, repo_root)}: evidence record named by the sidecar is missing")
    else:
        record_text = record_path.read_text()

        # The record's own stamp is checked in this branch rather than in the
        # next step because the record text is already read here. Without the
        # line the cited measurement names no tree it is reproducible from.
        stamp = _record_commit_stamp(record_text)
        if stamp is None:
            problems.append(
                f"{_rel(record_path, repo_root)}: has no **Repo commit** line -- "
                f"the cited measurement names no tree it is reproducible from")
        elif is_dirty_stamp(stamp):
            problems.append(
                f"{_rel(record_path, repo_root)}: **Repo commit** {stamp!r} "
                f"stamps a dirty tree -- the cited measurement is not "
                f"reproducible from any commit; re-characterize on a clean tree")

        corner = (prov.get("corner") or {}).get("name")
        for cell in claimed:
            measured = [b for b in _measurement_blocks(record_text)
                        if b.get("Cell") == cell
                        and (not corner or b.get("Corner") == corner)]
            if not measured:
                where = f" at corner {corner!r}" if corner else ""
                problems.append(
                    f"{_rel(record_path, repo_root)}: no measurement of cell "
                    f"{cell!r}{where}")
                continue
            cell_netlist = f"{cell}.spice"
            named = [Path(p).name for b in measured for p in
                     _SPICE_PATH_RE.findall(b.get("Netlist provenance", ""))]
            if named and cell_netlist not in named:
                wrong = ", ".join(sorted(set(named)))
                problems.append(
                    f"{_rel(record_path, repo_root)}: measurements of cell {cell!r} "
                    f"were taken on netlist(s) {wrong}, not {cell_netlist!r}")

    # 6. The sidecar's own stamp is reproducible: the writer appends the dirty
    #    suffix on an uncommitted tree, and a view characterized there is not
    #    re-derivable from any commit (issue #134).
    if is_dirty_stamp(prov["repo_commit"]):
        problems.append(
            f"{_rel(sidecar_path, repo_root)}: repo_commit {prov['repo_commit']!r} "
            f"stamps a dirty tree -- the recorded view is not reproducible from "
            f"any commit; re-characterize on a clean tree")

    return problems


def _rel(path: Path, repo_root: Path) -> str:
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="python3 -m sim.characterize.check_library",
        description="Verify the committed Liberty view agrees with its provenance "
                    "sidecar -- library name, cell set, declared corner, the "
                    "config it pins, the evidence record it names, and the "
                    "provenance stamps both carry (a dirty stamp is reported).")
    ap.add_argument("--lib", type=Path, default=DEFAULT_LIB,
                    help=f"Liberty view to check (default: {_rel(DEFAULT_LIB, REPO_ROOT)})")
    args = ap.parse_args(argv)

    problems = check(args.lib.resolve())
    if problems:
        for problem in problems:
            print(f"stale: {problem}", file=sys.stderr)
        return 1
    print(f"fresh: {_rel(args.lib.resolve(), REPO_ROOT)} agrees with its provenance "
          f"sidecar's library, cell set, corner, pinned config and evidence "
          f"record; the provenance stamps are clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
