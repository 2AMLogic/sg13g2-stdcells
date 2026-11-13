# sim/harness

What is left of the sim-harness scaffold after the local-ngspice half was
removed (#21; the removed modules remain in git history). Simulation runs
through `klt` — see `sim/characterize/`.

| Module | Covers |
|---|---|
| `corners.py` | The five MOS process corners (`tt`/`ff`/`ss`/`fs`/`sf`), `Corner`, and this library's characterization corner pairings (`CHAR_CORNER_PVT`). |
| `evidence.py` | `BaseExtensions` (open `extra` + `notes` slot) and `CharacterizationExtensions`: a validated per-arc cell-characterization record; fields are required on `record_kind=characterization` and rejected on other kinds. |
| `report.py` | `git_provenance` and `allocate_record_id` (`<YYYYMMDD>-<HHMMSS>-<short-sha>`, append-only: never returns an id whose record exists). |

The harness modules import only the standard library. Their tests need
pytest: `python3 -m pytest sim/tests` from the repo root.

## This library's characterization corners (DRAFT, pending #1)

Their supply/temperature pairings (`tt`/`ff`/`ss`) live in one constant,
`corners.CHAR_CORNER_PVT` (TT/1.20 V/25 C, FF/1.32 V/-40 C, SS/1.08 V/125 C),
taken from the README target table and **not ratified** until #1 lands; a
ratification change is a one-line edit there. They are paired, not a full
factorial. The sibling harness's corner-set registry and PVT grid were removed
(#51) as unused; add a grid back only against a real `klt characterize` need.
