# sim/harness

What is left of the sim-harness scaffold after the local-ngspice half was
removed (#21; the removed modules remain in git history). Simulation runs
through `klt` — see `sim/characterize/`.

| Module | Covers |
|---|---|
| `corners.py` | The five MOS process corners (`tt`/`ff`/`ss`/`fs`/`sf`), PVT-grid arithmetic (`Corner`, `PvtPoint`, `build_grid`, `supply_points`, `resolve_corners`), `sabotage()`, and this library's characterization corners. |
| `evidence.py` | `BaseExtensions` (open `extra` + `notes` slot) and `CharacterizationExtensions`: a validated per-arc cell-characterization record. `from_manifest` returns it; fields are required on `record_kind=characterization` and rejected on other kinds. |
| `report.py` | `git_provenance` and `allocate_record_id` (`<YYYYMMDD>-<HHMMSS>-<short-sha>`, append-only: never returns an id whose record exists). |

No third-party dependencies. Tests: `python -m pytest sim/tests`.

## This library's characterization corners (DRAFT, pending #1)

`corners.py` registers the corner set `sg13g2-stdcells-char` = `tt`, `ff`, `ss`.
Their supply/temperature pairings live in one constant,
`corners.CHAR_CORNER_PVT` (TT/1.20 V/25 C, FF/1.32 V/-40 C, SS/1.08 V/125 C),
taken from the README target table and **not ratified** until #1 lands; a
ratification change is a one-line edit there. `corners.characterization_points()`
returns exactly those 3 paired points, not the 27-point `build_grid` factorial.
