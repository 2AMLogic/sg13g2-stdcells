# T1 item 8 [digital]: add8 baseline characterization report (issue #177)

Aggregates numbers already recorded under `flow/records/`; it measures nothing
new and edits no record. Every figure is the **baseline leg on the stock
`sg13g2_stdcell`** for the `add8` flow. It is not a result for this library's
own cells, and no ETH Zurich / EZ130 figure appears here.

## Spec rows 10-12: owned, UNMEASURED

Rows 10 (benchmark cell area vs `sg13g2_stdcell`), 11 (benchmark energy) and
12 (benchmark clock period) of `spec/0001-target-specification.md` are ratios
of this library's cells against the baseline. This repo has no cell library
built from its own generator benchmarked yet, so **no ratio exists and none of
rows 10-12 is met or passed.** No bound is restated or changed.

**These numbers are NOT the ratio denominator.** Benchmark basis item 1
(`spec/0001-target-specification.md:133-139`) makes the denominator
`sg13g2_stdcell` *re-characterized through the same `klt characterize` flow*;
that re-characterized baseline does not exist yet (`ROADMAP.md`, **Next**:
"Baseline Liberty"). The tables below instead rest on the **PDK-shipped**
`sg13g2_stdcell` Liberty (deck `sg13g2_stdcell__typ_1p20V_25C`,
`released: false`; PDK `ihp-sg13g2` `fetched:0.3.0`, resolved from
`PDK_ROOT`), which basis item 1 allows to be reported only "labelled
separately". Do not divide this library's future numbers by these figures to
claim rows 10-12.

## Baseline numbers (stock `sg13g2_stdcell`, design `add8`)

| Quantity (Benchmark basis item) | Value | Source file | JSON field |
|---|---|---|---|
| Post-synthesis cell area (row 10) | 411.8688 um2 | `flow/records/20261104-df96543/synthesize.json` | `area_um2` |
| Liberty leakage sum (context) | 5.351730900000001 nW | `flow/records/20261104-df96543/synthesize.json` | `leakage_power_nw` |
| ABC critical-path delay, typ corner (row 12 basis 3, synthesis estimate) | 1048.49 ps | `flow/records/20261104-df96543/synthesize.json` | `timing.critical_path_ps` |
| Routed die area (post-layout, labelled separately) | 1674.45 um2 | `flow/records/20261121-be3a384/place-and-route.json` | `die_area_um2` |
| Routed core area (post-layout, labelled separately) | 850.954 um2 | `flow/records/20261121-be3a384/place-and-route.json` | `core_area_um2` |

Area is post-synthesis for row 10, as Benchmark basis item 2 requires; die and
core are post-layout, taps and fill not separately counted.

## Per-corner timing and power (`klt sta`, routed DEF, `flow/records/20261121-be3a384/sta.json`)

Constraint: 10.0 ns virtual `clk`, 2.0 ns input and output delay. The design is
combinational, so Fmax is derived from the worst in-to-out path under that
constraint, not a register-to-register period. No SPEF was supplied, so wire RC
is LEF-capacitance-only (optimistic relative to a post-route estimate;
`spef_annotation` is `null` at all three corners). Power is the engine-default
activity proxy (`power_basis`: `activity_source: engine_default`,
`parasitics: estimate_only`), not a measured-activity figure.

| Corner (`corners[].corner`) | `fmax_mhz` | `worst_slack_ns` | `estimated_power_mw` |
|---|---|---|---|
| `typ_1p20V_25C` | 196.607 | 4.91372 | 0.0063 |
| `fast_1p32V_m40C` | 212.095 | 5.28513 | 0.008 |
| `slow_1p08V_125C` | 175.583 | 4.3047 | 0.005 |

**Power is a default-activity proxy, not energy.** `estimated_power_mw` is
OpenROAD's power metric at the engine's default switching activity
(`power_basis.activity_source` = `engine_default`, `activity` null, parasitics
`estimate_only`). Benchmark basis item 4 requires total energy over one fixed
seeded random-vector set; no such vector-driven figure exists, and klt has no
activity input or energy-per-op metric (klayout-tools#4914). The values must
not be read as row 11 quantities.

## Evidence status on 2026-11-23

`8.digital` stays uncited and `unmet`. `klt signoff --attest 8` cannot accept an
inventory that owns rows 10-12 with no citation until
2AMLogic/klayout-tools#5856 lands; the rows are deliberately not dropped from
`spec_rows`, and no local checker or "not applicable" record stands in for the
klt field. Re-derive every number above with
`python3 manifests/check_item8_digital_report.py`. Nothing in `check-ci.sh`
runs that script today (`check-ci.sh` is itself hash-pinned in the item 10
envelope, so it is not edited here); enforcement arrives with the
`envelope_checks` entry added when the `8.digital` envelope is attested at
step 4. Until then it is a manual check.

### Attestation update, 2026-11-26

The digital item 8 inventory now cites the three source records under
`benchmark-basis-1-pdk-shipped-liberty`, the separately labelled stock-library
reference allowed by Benchmark basis item 1. Its `area` binding is the same
post-synthesis cell area at each STA corner because all three time the same
mapped netlist. The `fmax` and default-activity `power` bindings use the
corresponding corner in the STA record. Each citation runs
`python3 manifests/check_item8_digital_report.py` to check the tables.

The inventory declares the three ratio rows in `uncited_rows`. Their paired
measurements remain outstanding. [Benchmark tracking issue #286](https://github.com/2AMLogic/sg13g2-stdcells/issues/286)
