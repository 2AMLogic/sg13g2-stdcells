"""Freshness check for the committed Liberty view and its provenance sidecar.

`klt characterize` writes `views/<library>.lib` together with a
`<library>.lib.provenance` sidecar naming the config it was characterized from
(and that config's SHA-256), the corner, the cells, and the id of the
append-only record under `sim/characterize/records/`. Nothing re-checks that
those four artifacts still agree, so a config edit, a hand-edited `.lib`, or a
deleted record leaves a sidecar that still *claims* to describe the view.

This is that check. It re-derives every claim the sidecar makes from the files
themselves and exits non-zero naming each disagreement, so it fails when the
evidence goes stale rather than when the evidence is merely absent. It is what
`manifests/inventories/item8.analog.json` declares as the freshness command
behind its T1 item 8 citation (issue #75): a citation whose backing command
cannot fail is not evidence.

Run from the repo root:  python3 -m sim.characterize.check_library
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_LIB = REPO_ROOT / "views" / "sg13g2_stdcells_tt_1p20v_25c.lib"
RECORDS_DIR = REPO_ROOT / "sim" / "characterize" / "records"

_CELL_RE = re.compile(r"^\s*cell \(([A-Za-z0-9_]+)\)", re.MULTILINE)
_LIBRARY_RE = re.compile(r"^\s*library \(([A-Za-z0-9_]+)\)", re.MULTILINE)

REQUIRED_KEYS = ("library", "corner", "config", "config_sha256", "cells", "evidence_record")


def cells_in_lib(text: str) -> list[str]:
    return _CELL_RE.findall(text)


def library_name_in_lib(text: str) -> str | None:
    found = _LIBRARY_RE.search(text)
    return found.group(1) if found else None


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

    # 2. The .lib holds exactly the cells the sidecar claims were characterized.
    in_lib = sorted(cells_in_lib(lib_text))
    claimed = sorted(prov["cells"]) if isinstance(prov["cells"], list) else []
    if in_lib != claimed:
        problems.append(
            f"{_rel(lib_path, repo_root)}: holds cells {in_lib}, "
            f"sidecar claims {claimed}")

    # 3. The config is still the one that was characterized, byte for byte.
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

    # 4. The evidence record still exists and still speaks for these cells and corner.
    record_id = prov["evidence_record"]
    record_path = records_dir / f"{record_id}.md"
    if not record_path.is_file():
        problems.append(
            f"{_rel(record_path, repo_root)}: evidence record named by the sidecar is missing")
    else:
        record_text = record_path.read_text()
        for cell in claimed:
            if cell not in record_text:
                problems.append(
                    f"{_rel(record_path, repo_root)}: no measurements for cell {cell!r}")
        corner = (prov.get("corner") or {}).get("name")
        if corner and f"**Corner**: {corner}" not in record_text:
            problems.append(
                f"{_rel(record_path, repo_root)}: no measurement at corner {corner!r}")

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
                    "sidecar, the config it pins and the evidence record it names.")
    ap.add_argument("--lib", type=Path, default=DEFAULT_LIB,
                    help=f"Liberty view to check (default: {_rel(DEFAULT_LIB, REPO_ROOT)})")
    args = ap.parse_args(argv)

    problems = check(args.lib.resolve())
    if problems:
        for problem in problems:
            print(f"stale: {problem}", file=sys.stderr)
        return 1
    print(f"fresh: {_rel(args.lib.resolve(), REPO_ROOT)} agrees with its provenance "
          f"sidecar, pinned config and evidence record")
    return 0


if __name__ == "__main__":
    sys.exit(main())
