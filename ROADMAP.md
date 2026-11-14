# Roadmap

sg13g2-stdcells is an 8-track standard-cell library for the IHP SG13G2 open PDK,
built by generators and verified through klayout-tools (`klt`) and the open flow.

Status as of 2026-11-13, `main` @ `8d411c0`.

`WORK_PLAN.md` (generated from label state) and `WORK_LOG.md` (merged-PR log)
are separate files and are not replaced by this one.

## Where it stands

The ratified target is `spec/0001-target-specification.md` (rows 1-12). Against it:

- **Generators (rows 1-4).** `design/gen_netlists.py` (boolean function to
  static-CMOS netlist) and `layout/gen_layouts.py` (netlist plus process config
  to GDS) are on `main`, both with `--check` gated in CI (#5, #22, #35, #47).
  The generator existing is not the same claim as the geometry rows being met,
  so per row, for the cells it places: row 1 (3.36 um row height) is **met** —
  `layout/example_config.json` sets `row_height_nm: 3360` and
  `layout/tests/test_gen_layouts.py:113,127` assert the emitted cell height.
  Row 2's horizontal pitch (0.42 um) is **met** — widths and gate columns are
  multiples of `gate_pitch_nm: 420`
  (`layout/tests/test_gen_layouts.py:129,133`); the vertical grid is not
  separately checked. Row 3 (Metal1 only) is **met by construction** — the
  only metal entries in the `layout.layers` map in
  `layout/example_config.json` are `metal1` and `metal1_label` (its other six
  are well, diffusion, poly, implant and contact layers), and no generator
  draws a second metal.
  Row 4 (every pin on a grid point) is **not verified**: no check asserts that
  the emitted pin labels land on grid points.
- **Cells (row 5: target 40).** Four are generated from
  `layout/example_config.json`: `sg13g2_inv_1`, `_inv_2`, `_inv_4`,
  `sg13g2_nand2_1`. Sequential cells (row 6) are out of target scope.
- **DRC (row 7).** `layout/drc/*.json`: 0 violations on all four cells under
  the curated `sg13g2` deck, whose coverage limits each report lists.
- **LVS (row 8): not met.** `layout/lvs/*.json` are all `status: mismatch`
  (12, 16, 20 and 18 errors). `layout/README.md` gives the likely cause, not
  yet demonstrated: the layouts draw no well or substrate tap.
- **Liberty (row 9).** `views/sg13g2_stdcells_tt_1p20v_25c.lib` holds the four
  cells at TT / 1.20 V / 25 C, emitted by `klt characterize` (#40), with a
  provenance sidecar and the record `sim/characterize/records/20261107-222836-6ee1577.md`.
  It carries no `area` attribute.
- **Benchmark (rows 10-12): not started on this library.** `flow/records/`
  holds the `add8` baseline on the stock `sg13g2_stdcell` only: synthesis,
  place-and-route with all three power gates, gate-level LVS `match`, routed
  GDS and a clean `klt drc` (#9, #41).
- **Evidence grade.** `manifests/signoff-report.txt` (`klt signoff --manifest`):
  tier none, **T1 7/22 items met**. Met: items 1, 2, 3 on both partitions and
  item 4 digital. Unmet: item 4 analog (`check_failed`, the LVS above), item 11
  digital (`supply_spec_incomplete`), and items 5-10 and 11 analog
  (`no_evidence`). Tracker: #3, whose body still quotes the earlier 3/22.

### What the layout generator can place today

Probed on this commit by running `layout/gen_layouts.py` on one-cell configs
derived from `layout/example_config.json` (same process and rules):

| Result | Cells | Reason reported (exit 3) |
|---|---|---|
| places | `inv_1/2/4/8/16`, `nand2_1` | |
| fails | `nor2_1`, `nor2_2` | diffusion 250 nm tall is too short for a contact |
| fails | `and2_1`, `or2_1`, `a21oi_1`, `o21ai_1`, `xor2_1` | devices of different finger widths in one strip |
| fails | `nand3_1`, `nor3_1`, `nand4_1`, `a22oi_1` | needs a diffusion break |
| fails | `buf_1`, `nand2_2` | needs 2 channel tracks, config allows 1 |
| fails | `nor4_1` | 500 nm device cannot be drawn as 4 fingers on the 10 nm grid |

The placement model is what holds the generator to 6 of the 20 cells probed
above (row 5 targets 40); `layout/example_config.json`, which lists four of
those six, is what holds the committed count at 4.

## Now

All four items have issues, filed 2026-11-14 by the same roadmap pass as this
document and so after the date in its header: #73 (item 1), #74 (item 2), #75
(item 3) and #76 (item 4). Pick the issue up rather than re-filing it. Also
after this snapshot, #73 closed on 2026-11-14 — its taps-and-LVS work merged to
`main` in PR #79, which supersedes item 1 and the row 8 "not met" above, with
all four `layout/lvs/*.json` now `status: match`. As of 2026-11-14 #74 carries
`loom:issue` and is ready for a builder, #75 is `loom:building`, and #76 is
`loom:curated` but not yet promoted. Label state moves daily; read the tracker,
not this line.

1. **Draw well and substrate taps, then re-run LVS.** Done when
   `layout/gen_layouts.py` emits tap geometry from config, `layout/drc/` holds
   fresh clean reports for the regenerated cells, and new `layout/lvs/*.json`
   are recorded by `layout/run_lvs.py` with no `device.body_unverified`
   warning. If a cell still mismatches, the PR records which signal nets
   differ. The upstream diagnosis gap, klayout-tools#5125, closed on
   2026-11-08, after these reports were written.
2. **Place devices of different finger widths in one diffusion strip.** Done
   when `and2_1`, `or2_1`, `a21oi_1` and `o21ai_1` are in
   `layout/example_config.json` with committed GDS, netlists and clean
   `klt drc` reports, and the unit tests cover the new case.
3. **Cite the evidence already on `main` in the manifest and regrade.** The
   Liberty view and its record (item 8), `verification/test_add8.py` (item 9
   digital) and the README/LICENSE/CI inventory (item 10) exist but
   `manifests/sg13g2-stdcells.json` cites none of them. Done when each is
   cited through a `klt signoff --attest` envelope and
   `manifests/signoff-report.*` is regenerated, or the report records why the
   tool rejects a citation.
4. **Bring the README Status section in line with `main`.** It still says
   nothing is designed, that no `.lib` is committed and that `views/` is
   empty; the repo-layout line for `design/` still says xschem schematics.
   Done when the prose matches the files and the `Design stage` token is the
   highest rung with recorded evidence, which the LVS mismatch caps.

## Next

- **Diffusion breaks** in `gen_layouts.py` (unlocks `nand3_1`, `nor3_1`,
  `nand4_1`, `a22oi_1`, and the XOR and mux families). After Now 1 and 2,
  which edit the same file. Done when those cells are generated, DRC-clean
  and LVS-matched.
- **`nor2` placement.** Done when `nor2_1` and `nor2_2` generate without
  relaxing a rule; the PR states whether the fix is sizing or geometry.
- **Cell area in the Liberty view** (row 10 needs it). Done when each cell
  in the `.lib` has an `area` derived from the generated layout.
- **LEF abstracts in `views/`** with the 0.42 um track definition the
  benchmark basis requires. Blocked on LVS-matched cells (Now 1).
- **Baseline Liberty:** re-characterize the `sg13g2_stdcell` cells that
  `add8` maps to through the same `klt characterize` flow (benchmark basis,
  item 1). Done when the baseline `.lib` and its record are committed.
- **Digital item 11.** Re-run `flow/run.sh` on a current klt, then supply
  what `supply_spec_incomplete` asks for or file the gap upstream.

## Later

- **The 40-cell set.** Which 40 cells and drive strengths? The spec names
  the families only.
- **Two channel tracks** (`buf_1`, `nand2_2`, every folded series stack). Does
  the 3.36 um row leave room for a second Metal1 track between the strips
  under the ratified geometry, or do these cells need a different topology?
- **Rows 10-12 benchmark** against the re-characterized baseline. Which
  combinational designs beyond `add8`? The spec leaves that to the benchmark issue.
- **T1 items 5-7** (corner verification, statistical evidence, post-layout
  verification). What does each accept as evidence for a cell library
  rather than a block?
- **Stretch corners** (FF, SS) and **sequential cells** (stretch row 6); the
  latter waits on setup/hold support in `klt characterize`, per the spec.

## Blocked and waiting

- Not the Now list: #73-#76 cover all four of its items (see Now), and as of
  2026-11-14 #74 carries `loom:issue` — ready for a builder today. Nothing in
  this roadmap is waiting on an issue being filed.
- #59, #62 and #69 are simplification proposals awaiting maintainer approval:
  tidy-ups, not steps toward the spec. #3 stays open as the tracker and #56
  is an automated hold digest.
- Nothing is currently waiting on an open klayout-tools issue: #5031, #5125,
  #4913, #4914 and #4915 are all closed. Records made before those fixes
  have not been re-run.

## Not planned

- Hand-drawn cells: if a cell cannot be generated, the generator is the bug.
- Relaxing a design rule or a ratified spec row to make a check pass.
- Restating ETH Zurich's EZ130 figures as results of this repo.
