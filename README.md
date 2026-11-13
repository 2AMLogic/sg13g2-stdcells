# sg13g2-stdcells

A 8-Track Standard-Cell Library on the [IHP SG13G2](https://github.com/IHP-GmbH/IHP-Open-PDK) open PDK,
designed by AI agents driving
[klayout-tools](https://github.com/2AMLogic/klayout-tools) and the open-source
flow — cocotb + Icarus and Yosys/OpenROAD on the digital side, xschem + ngspice
on the analog side.

It is the set of small logic gates — inverters, NANDs, adders and, later, flip-flops (see Status) —
that a synthesis tool assembles a digital chip out of, laid out by hand-written
generators at a fixed 3.36 um row height and characterized into the timing and
power tables (`.lib`) that every downstream tool reads.

## Status

```
Area (measured, post-layout): not yet measured
Design stage: spec
```

<!-- The two fields above are correct as they stand for a repo where nothing is
     built yet, so there is nothing to fill in here — only to keep current. They
     are a fixed-location summary a chip-level integrator reads without parsing
     the prose below, so the keys, their spelling, and their order do not change.

     Area (measured, post-layout): the as-built area of a DRC-clean,
     LVS-matched layout, as a number with units (e.g. 1.059 mm²), taken from
     this repo's own committed measurement. Never a target, a plan, or an
     estimate — the ratified bound is the AREA row of the target-specification
     table below. Until a layout exists, the literal "not yet measured".

     Design stage: exactly one token, from this ladder, in order —
     spec | schematic-sim | layout-DRC-LVS-clean | extracted-verified | silicon
     — describing what this repo has produced and recorded evidence for, never
     what it is aiming at. One token; not a range, not a hedge, not prose. -->

**Just opened, specification phase.** Nothing is designed yet, nothing has been
taped out, and nothing has been measured.

Deliberately not being built yet, and what each waits on:

- **Sequential cells.** Flip-flops and latches need a setup/hold constraint
  search, which is strictly harder than a combinational arc sweep. The
  combinational set comes first; sequential cells wait on that machinery
  working.
- **Liberty characterization of any cell.** `klt characterize` emits Liberty
  (klayout-tools#2528), but there is no cell yet to characterize, so no `.lib`
  is committed and `views/` stays empty.
- **The synthesis benchmark.** The area/timing/energy comparison in the table
  below cannot be run until there is a `.lib` to run it with. It waits on
  cells and a generator, and on the benchmark basis in the decision record.
- **Any claim about beating `sg13g2_stdcell`.** The reference numbers in this
  repo are ETH Zurich's, measured with commercial tools on their own library.
  Nothing here restates them as ours, and nothing will until this repo has
  produced its own measurement on its own cells.

## Built agent-native

Every specification, decision record, testbench, and line of documentation in
this repo is produced by AI agents working from a ratified spec and an
append-only evidence trail — not human-authored work that agents merely
assisted with. Verification is the product: every claim traces to a recorded
result. Where the agents hit friction with the open-source tooling — most often
[klayout-tools](https://github.com/2AMLogic/klayout-tools) — that friction gets
filed as a public issue against the tool itself, so the fix benefits everyone
using IHP SG13G2, not just this repo.

## Target specification

Ratified by decision record
[`spec/0001-target-specification.md`](spec/0001-target-specification.md), which
carries the per-row reasoning. The reference column is ETH Zurich's EZ130 8T
(arXiv:2609.29965; the library is Apache-2.0), a library for this same process characterized
with commercial tools — it is an external reference point, ETH Zurich's
published result, not a result of this repo. Where the paper and the ETH library
page disagree, both are shown with their source.

| # | Parameter | Target | Stretch | EZ130 8T (ETH Zurich's reference) |
|---|---|---|---|---|
| 1 | Row height | 3.36 um (8 tracks) | — | 3.36 um |
| 2 | Routing grid | 0.42 um x 0.42 um | — | 0.42 um x 0.42 um |
| 3 | Intra-cell routing | Metal1 only | — | Metal1 only |
| 4 | Pin access | every pin on a grid point | — | every pin on grid |
| 5 | Combinational cells | 40 | 120 | 220 total, all cell types (ETH paper; library page); split not published |
| 6 | Sequential cells | 0 (out of scope, see Status) | 8 | included in the 220 total; split not published |
| 7 | DRC | clean, `klt drc`, sg13g2 deck | — | Calibre (ETH's physical verification tool; "clean" is not stated) |
| 8 | LVS | layout-vs-schematic match, `klt lvs` | — | Calibre (ETH's physical verification tool; "clean" is not stated) |
| 9 | Liberty corners | TT/1.20 V/25 C | + FF/1.32 V/-40 C, SS/1.08 V/125 C | all three |
| 10 | Benchmark cell area vs `sg13g2_stdcell` | <= 1.00x | <= 0.80x | 0.65x (ETH paper) / 0.67x (ETH library page) |
| 11 | Benchmark energy vs `sg13g2_stdcell` | <= 1.00x | <= 0.80x | 0.61x (ETH paper) / 0.67x (ETH library page) |
| 12 | Benchmark clock period vs `sg13g2_stdcell` | <= 1.10x | <= 1.05x | "virtually the same" (ETH) |

Rows 10–12 are measured on combinational-only netlists at target scope; see the
record for why and for what that means for comparison with ETH Zurich's figures.

## Repo layout

```
design/        schematics (xschem)
flow/          synthesis + place-and-route (Yosys, OpenROAD)
layout/        GDS + DRC/LVS reports (klayout-tools driven)
measurements/  silicon characterization (empty until tape-out)
rtl/           Verilog sources
sim/           analog testbenches + PVT corner results
spec/          ratified spec + decision records
verification/  cocotb testbenches
views/         generated LEF/Liberty views
ratification/  the two reviewer-key skills a spec ratification needs
```

## Continuous integration

`.github/workflows/ci.yml` runs on every pull request and on push to `main`. It
needs only Python 3, `pytest` and `jq` — no klt, ngspice or PDK, so
tool-dependent runs (SPICE, DRC, LVS, place-and-route) are not covered by CI.
To reproduce locally, run `npm run check:ci` from the repo root, or the same
commands individually:

```
python3 -m pytest design/tests layout/tests sim
python3 design/gen_netlists.py --config design/example_config.json --check
python3 layout/gen_layouts.py --config layout/example_config.json --check
R=flow/records/20261104-df96543
flow/check-evidence.sh flow/request-par.json $R/place-and-route.json $R/lvs.json $R/erc.json   # must exit 0
flow/check-evidence.sh flow/request-par.json $R/negative-control-nopower.place-and-route.json $R/lvs.json $R/erc.json   # must exit non-zero
```

T1 item 10 inventory: README present (this file), license present
([LICENSE](LICENSE)), CI present (`.github/workflows/ci.yml`).

## License

Apache License 2.0 — see [LICENSE](LICENSE).
