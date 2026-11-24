# Roadmap

sg13g2-stdcells is an 8-track standard-cell library for the IHP SG13G2 open PDK,
built by generators and verified through klayout-tools (`klt`) and the open flow.

Status as of 2026-11-15, `main` @ `176f794`.

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
  `Geometry.test_cell_width_follows_pitch` in
  `layout/tests/test_gen_layouts.py` asserts the emitted cell height
  (`H == 3360`).
  Row 2's horizontal pitch (0.42 um) is **met** — widths are multiples of
  `gate_pitch_nm: 420` and neighbouring gate columns are 420 nm apart, at
  half-pitch offsets from the cell edge
  (`Geometry.test_cell_width_follows_pitch` asserts `W == 4 * 420`, and
  `MultiFinger.test_width_grows_with_finger_count` asserts widths of
  `3/4/6 * 420`, both in `layout/tests/test_gen_layouts.py`); the vertical grid is not
  separately checked. Row 3 (Metal1 only) is **met by construction** — the
  only metal entries in the `layout.layers` map in
  `layout/example_config.json` are `metal1` and `metal1_label` (its other six
  are well, diffusion, poly, implant and contact layers), and no generator
  draws a second metal.
  Row 4 (every pin on a grid point) is **met** (#225, measured on the
  regenerated cells):
  `PinOnGrid.test_every_pin_label_is_on_the_routing_grid` in
  `layout/tests/test_gen_layouts.py` asserts every `metal1_label` of every config cell — gate pads, outputs and
  the VSS/VDD rail labels — is a multiple of the same 420 nm on both axes from
  the cell origin and lies on Metal1, and `PinOnGrid.test_row4_off_grid_record` pins that no label is off the
  grid on the four cells (17 of 17 on grid, up from 2 of 17 before #225). The
  generator moved the diffusion nodes onto the grid columns and the gates a
  half pitch between them, so a cell is `(columns + 2)` pitches wide (inv_1
  840 -> 1260 nm). Row 2's 420 nm gate-to-gate spacing is unchanged. DRC and
  LVS were re-recorded on the new streams (below).
- **Cells (row 5: target 40).** Four are generated from
  `layout/example_config.json`: `sg13g2_inv_1`, `_inv_2`, `_inv_4`,
  `sg13g2_nand2_1`. Sequential cells (row 6) are out of target scope.
- **DRC (row 7).** `layout/drc/*.json`: 0 violations on all four cells under
  the curated `sg13g2` deck, whose coverage limits each report lists.
- **LVS (row 8): met.** All four `layout/lvs/*.json` are `status: match` with
  `error_count: 0`, closed by the well and substrate taps (#79). The rung
  above is not reached: `environment.extracted_netlist` is `null` in all four
  reports and T1 #7 is `[UNMET]` (no `7.analog` citation). `klt pex` was run
  on all four cells with the item 5 benches
  (`sim/item7/records/20261123-202000-5e308b6.md`): `sg13g2_inv_1/2/4` graded
  with failing delta rows against the 2 % limits (25 / 50 / 81 of 152), bodies
  all biased; `sg13g2_nand2_1` timing hit the 120 s cap, tracked as
  2AMLogic/klayout-tools#7646. Recorded as findings, not cited.
- **Liberty (row 9).** `views/sg13g2_stdcells_tt_1p20v_25c.lib` holds the four
  cells at TT / 1.20 V / 25 C, emitted by `klt characterize` (#40), with a
  provenance sidecar and the record `sim/characterize/records/20261115-220740-13dc481.md`.
  It carries no `area` attribute.
- **Corner verification (T1 item 5 analog, row 9): met.** Eight `klt sim`
  envelopes (`sim/item5/records/20261121-135717-f5cb68a/`, issue #180) cover
  the row at its target corner: per cell, the logical function at the rails
  (all input combinations, settled output within 10 mV of the rail the
  Liberty function demands) and delay plus rise/fall transition at every
  (input transition, output load) point of the committed view's 5x5 grid,
  each agreeing with the tabulated value at the same slew and load to within
  2 % (worst observed 0.058 %). Every measurement is limit-checked and
  `spec_row`-tagged `9`, so the report's row coverage is derived, and the
  item's declared row set is row 9 alone (the other eleven rows are graded
  elsewhere or not electrical — disposition in PR #180's description).
- **Benchmark (rows 10-12): not started on this library.** `flow/records/`
  holds the `add8` baseline on the stock `sg13g2_stdcell` only: synthesis,
  place-and-route with all three power gates, gate-level LVS `match`, routed
  GDS and a clean `klt drc` (#9, #41).
  Row 10 stays unmeasured; what is known is the geometry it starts from. As
  built under the `(columns + 2) * 420 nm` pin-on-grid phasing (#225), at the
  3360 nm row height (`layout/gen_layouts.py` over `layout/example_config.json`,
  `main` @ `829d86f`, 2026-11-23): `sg13g2_inv_1` 1260 nm / 4.2336 um^2,
  `sg13g2_inv_2` 1680 nm / 5.6448 um^2, `sg13g2_inv_4` 2520 nm / 8.4672 um^2,
  `sg13g2_nand2_1` 1680 nm / 5.6448 um^2; sum 7140 nm / 23.9904 um^2. The
  stock `sg13g2_stdcell` (IHP-Open-PDK v0.3.0 LEF, `CoreSite` 0.48 x 3.78 um)
  draws the same four cells at 1.44 / 1.92 / 2.88 / 1.92 um wide, 30.8448 um^2
  summed, so the same site count (17) on a smaller site gives 7/9 (about
  0.778x) per cell and summed. That is geometric headroom of about 22 % below
  row 10's `<= 1.00x` target, not a result: #225 spent the 1-pitch margin the
  off-grid `(columns + 1)` widths had (5460 nm, +30.8 % to 7140 nm), and
  diffusion-break and multi-track column overheads and post-synthesis drive
  sizing are still to draw from it. The `<= 0.80x` stretch is not covered by
  the site-count geometry alone.
- **Evidence grade.** See the committed
  [`manifests/signoff-report.txt`](manifests/signoff-report.txt)
  (`klt signoff --manifest`) — it contains the evidence tier, the T1 item
  total and the per-item results for each partition. Tracker:
  [#3](https://github.com/2AMLogic/sg13g2-stdcells/issues/3) collects
  the remaining follow-up work.

### What the layout generator can place today

Probed on `176f794` by running `layout/gen_layouts.py` on one-cell configs
derived from `layout/example_config.json` (same process and rules):

| Result | Cells | Reason reported (exit 3) |
|---|---|---|
| places | `inv_1/2/4/8/16`, `nand2_1` | |
| fails | `nor2_1`, `nor2_2` | diffusion 250 nm tall is too short for a contact |
| fails | `nand2_2`, `buf_1`, `and2_1` | needs 2 channel tracks, config allows 1 |
| fails | `or2_1`, `nor3_1` | PMOS devices do not form a single diffusion chain (needs a diffusion break) |
| fails | `nand3_1`, `nand4_1`, `a21oi_1`, `a22oi_1`, `xor2_1` | NMOS devices do not form a single diffusion chain (needs a diffusion break) |
| fails | `o21ai_1` | no NMOS/PMOS strip orderings share one gate-net sequence |
| fails | `nor4_1` | 500 nm device cannot be drawn as 4 fingers on the 10 nm grid |

The placement model is what holds the generator to 6 of the 20 cells probed
above (row 5 targets 40); `layout/example_config.json`, which lists four of
those six, is what holds the committed count at 4.

## Now

#73-#76, filed 2026-11-14 against the previous edition of this list, all
closed on 2026-11-14 through merged PRs #79/#83/#84/#85. Two of the four
items (taps and LVS; README Status) were delivered in full and are dropped;
the surviving remainder of the other two is the list below, judged against
each item's own done-criterion, not against whether its issue closed.

1. **Add the AND/OR and AOI/OAI cells.** #74's generator half merged as
   PR #85 — one strip may now hold devices of different finger widths — but
   it added no cell. Each of the four is blocked by a further limit, named in
   the placement table above and in `layout/README.md`: `and2_1` needs 2
   channel tracks, `or2_1` a PMOS diffusion break, `a21oi_1` an NMOS
   diffusion break, `o21ai_1` a shared gate-net sequence. Done when
   `and2_1`, `or2_1`, `a21oi_1` and `o21ai_1` are in
   `layout/example_config.json` with committed GDS, netlists and clean
   `klt drc` reports, and the unit tests cover the new cases.
2. **Cite the characterization evidence in the manifest and regrade.** Items
   9 digital and 10 on both partitions are cited and met (PR #83). Item 8 is
   not: the Liberty view and its record exist on `main`, but
   `manifests/sg13g2-stdcells.json` has no `evidence.8.*` key and
   `manifests/signoff-report.txt` records `[UNMET] T1 #8` with
   `reason: no_evidence`, which says nothing was cited, not why a citation
   cannot be made. Done when item 8 is cited through a `klt signoff
   --attest` envelope and the report is regenerated, or the report records
   why the tool rejects the citation. The provenance staleness #82 tracked is
   resolved — the view was regenerated against the committed config and its
   freshness command passes — leaving only the unminted envelope, which needs
   a local `klt signoff --attest` run (CI has no klt); tracked in #82.

## Next

- **Diffusion breaks** in `gen_layouts.py` (unlocks `or2_1` and `nor3_1` on
  the PMOS side and `nand3_1`, `nand4_1`, `a21oi_1`, `a22oi_1` and `xor2_1`
  on the NMOS side — see the placement table above). Overlaps the Now cell
  additions, which edit the same file. Done when those cells are generated,
  DRC-clean and LVS-matched.
- **`nor2` placement.** Done when `nor2_1` and `nor2_2` generate without
  relaxing a rule; the PR states whether the fix is sizing or geometry.
- **Cell area in the Liberty view** (row 10 needs it). Done when each cell
  in the `.lib` has an `area` derived from the generated layout.
- **LEF abstracts in `views/`** with the 0.42 um track definition the
  benchmark basis requires. No longer blocked on LVS: the four committed
  cells are matched (row 8).
- **Baseline Liberty:** re-characterize the `sg13g2_stdcell` cells that
  `add8` maps to through the same `klt characterize` flow (benchmark basis,
  item 1). Done when the baseline `.lib` and its record are committed.
- **Digital item 11.** Re-run `flow/run.sh` on a current klt, then supply
  what `supply_spec_incomplete` asks for or file the gap upstream.

## Later

- **The 40-cell set.** Which 40 cells and drive strengths? The spec names
  the families only.
- **Two channel tracks** (`and2_1`, `buf_1`, `nand2_2`, every folded series
  stack). It is now the named next limit for `and2_1`: PR #85 removed the
  mixed-width refusal ahead of it. Does the 3.36 um row leave room for a
  second Metal1 track between the strips under the ratified geometry, or do
  these cells need a different topology?
- **Rows 10-12 benchmark** against the re-characterized baseline. Which
  combinational designs beyond `add8`? The spec leaves that to the benchmark issue.
- **T1 items 6-7** (statistical evidence, post-layout verification; item 7
  attempted in #181, see the LVS row above). What
  does each accept as evidence for a cell library rather than a block?
  Item 5 analog left this list: its row set is row 9, covered by the
  `sim/item5/` envelopes (#180); item 5 digital is separate and still
  `no_evidence` (tracked by #175).
- **Stretch corners** (FF, SS) and **sequential cells** (stretch row 6); the
  latter waits on setup/hold support in `klt characterize`, per the spec.

## Blocked and waiting

- Not the old Now list: #73-#76 all closed on 2026-11-14 through merged PRs
  #79/#83/#84/#85, and what they left undone is the Now list above, not a
  waiting item. #82 is the named blocker for the T1 item-8 citation (Now
  item 2). Nothing in this roadmap is waiting on an issue being filed.
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
