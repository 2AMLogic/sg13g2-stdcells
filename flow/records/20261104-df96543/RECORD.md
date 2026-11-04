# Baseline run: `add8` on stock `sg13g2_stdcell` (issue #9)

**sg13g2_stdcell baseline, measured here.** Every number below was produced by
`flow/run.sh` in this repo on the stock IHP library. No ETH Zurich / EZ130
figure appears in this record. This is not a result for this library's own
cells (none exist yet).

Append-only: a later run gets a new `records/<id>/`; it does not edit this one.

Run on `df96543` (+ the issue-9 working tree), `klt 0.8.1.dev1329+g106513697889`,
Yosys 0.67+post, OpenROAD 26Q3-1510-g6cb3f2b704, IHP-Open-PDK `fetched:0.3.0`,
corner `typ_1p20V_25C`, seed 1, utilization 38 %.

| Quantity | Value | Where it comes from / how to read it |
|---|---|---|
| Cell area (post-synth) | 411.8688 um^2, 39 cells | `synthesize.json` `area_um2`, `instance_count` |
| Die / core area (routed) | 1674.45 / 850.954 um^2 | `place-and-route.json` `die_area_um2`, `core_area_um2` (floorplan-set at 38 % target utilization; not a library figure) |
| Wirelength | 1020 um | `place-and-route.json` |
| Leakage (Liberty sum) | 5.3517 nW | `synthesize.json` `leakage_power_nw` |
| Energy proxy | 0.0074 mW | `place-and-route.json` `estimated_power_mw` = OpenROAD `report_power_metric` after route, **at OpenROAD's default switching activity** (no vector, no activity file). It is a power proxy, not an energy-per-operation figure; klt emits no energy-per-op metric. Filed as friction (klayout-tools#4914). |
| Critical-path delay | 1048.49 ps | `synthesize.json` `timing.critical_path_ps` (ABC `stime`, no wire load, typ corner). The design is combinational, so this is a path delay, **not an achievable clock period**. |
| Achievable clock period | **not measured** | `place-and-route.json` reports `timing_status: "unconstrained"` and `worst_slack_ns: 1e+39` because `clk` is an unused port with no timed path. `fmax_mhz: 811.736` is emitted but is not backed by a constrained path; do not cite it as a period. Filed as friction (klayout-tools#4914). |
| Route DRC / antenna | 0 / 0 | `route_drc_violation_count`, `antenna_violation_count` (route-time counts; `klt drc` was not run) |

## The three power gates

1. **`power.pdn: true`** - yes (`power.preset: "sg13g2"`). `tapcell_master` is
   `null` and `tapless` is `true`: this PDK's standard-cell library ships no
   tap/endcap cells, so there is no named tapcell master. The PDN is Metal1
   rails + TopMetal1/TopMetal2 straps, filler `sg13g2_fill_1`/`sg13g2_fill_2`.
2. **LVS** (`reference.form: gate-level-verilog`, as-built `verilog_path`):
   `status: match` **and** `power_connectivity.status: match`.
3. **ERC supply read** (`erc-spec.json`, `VDD`/`VSS` as `kind: supply`):
   0 findings, one island each (`matched_islands 1` of `expected_islands 1`).
   Caveat: `erc.missing_tie` is reported **inapplicable** (`no_ties_declared`),
   so "zero `missing_tie`" is vacuous here - no tie could be declared because
   the library has no tap cells (substrate/well contacts live inside the
   cells). `erc.supply_short` is inapplicable (`substrate_continuity_not_modelled`).
   Three label-layer warnings (Metal4, Metal5, TopMetal1 carry no text) are
   expected: pins are labelled only on Metal1 and TopMetal2.

## Other checks

- `synthesize-equivalence.json`: `klt synthesize --verify-equivalence` ->
  `equivalent`.
- `negative-control-nopower.place-and-route.json`: the same request with
  `power` deleted reaches `status: ok`, `stage_reached: route`, with no
  `power` object; `flow/test-check-evidence.sh` shows `check-evidence.sh`
  rejects it.
- Closed klayout-tools#2441 / #2444 / #2447: this run confirms `request.power`
  (preset `sg13g2`) works for this flow. `klt drc` was not run here, so the
  #2444 spurious-violation fix is **not** verified by this record.

## Departures from the issue text

- `rtl/add8.v` carries an unused `clk` input. `klt place-and-route` refuses
  `target_stage: "route"` without `constraints.clock_port`/`clock_period_ns`,
  even for a design with no sequential cells. The port adds no cells or area.
  A first synth without it gave 442.7136 um^2 (ABC run with no delay target);
  the figures above are with `clock_period_ns: 10.0` set.

## Friction filed (klayout-tools)

- #4913 - combinational design cannot reach `route` without a dummy clock port.
- #4914 - `fmax_mhz` emitted for an unconstrained design; no activity input or energy-per-op metric.
- #4915 - `klt erc` tie check cannot be expressed for a library with no tap cells.
