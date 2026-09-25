# sg13g2-stdcells

A 8-Track Standard-Cell Library on the [IHP SG13G2](https://github.com/IHP-GmbH/IHP-Open-PDK) open PDK,
designed by AI agents driving
[klayout-tools](https://github.com/2AMLogic/klayout-tools) and the open-source
flow — cocotb + Icarus and Yosys/OpenROAD on the digital side, xschem + ngspice
on the analog side.

It is the set of small logic gates — inverters, NANDs, adders, flip-flops —
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
- **Liberty characterization of any cell.** `klt` reads NLDM Liberty but no
  verb writes it (`2AMLogic/klayout-tools#2498`). Until that lands, a cell
  designed here cannot be synthesized against without a commercial
  characterizer, so no `.lib` is committed and `views/` stays empty.
- **The synthesis benchmark.** The area/timing/energy comparison in the table
  below cannot be run until there is a `.lib` to run it with. It waits on the
  same issue.
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

## Target specification (DRAFT — engineering to ratify, see issue #1)

All rows are DRAFT until issue #1 ratifies them. The reference column is
ETH Zurich's EZ130 8T (arXiv:2609.29965, Apache-2.0), a library for this same
process characterized with commercial tools — it is an external reference
point, not a result of this repo.

| Parameter | Target | Stretch | EZ130 8T (reference) |
|---|---|---|---|
| Row height | 3.36 um (8 tracks) | — | 3.36 um |
| Routing grid | 0.42 um x 0.42 um | — | 0.42 um x 0.42 um |
| Intra-cell routing | Metal1 only | — | Metal1 only |
| Pin access | every pin on a grid point | — | every pin on grid |
| Combinational cells | 40 | 120 | ~180 |
| Sequential cells | 0 (out of scope, see Status) | 8 | ~40 |
| DRC | clean, `klt drc`, sg13g2 deck | — | Calibre clean |
| LVS | layout-vs-schematic match, `klt lvs` | — | Calibre clean |
| Liberty corners | TT/1.20 V/25 C | + FF/1.32 V/-40 C, SS/1.08 V/125 C | all three |
| Benchmark cell area vs `sg13g2_stdcell` | <= 1.00x | <= 0.80x | 0.65x reported |
| Benchmark energy vs `sg13g2_stdcell` | <= 1.00x | <= 0.80x | 0.61x reported |
| Benchmark clock period vs `sg13g2_stdcell` | within 10% | within 5% | "virtually the same" |

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

## License

Apache License 2.0 — see [LICENSE](LICENSE).
