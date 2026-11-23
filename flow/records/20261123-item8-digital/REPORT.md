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
rows 10-12 is met or passed.** The tables below are the denominator side only.
No bound is restated or changed.

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
constraint, not a register-to-register period.

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

## Evidence status

`8.digital` stays uncited and `unmet`. `klt signoff --attest 8` cannot accept an
inventory that owns rows 10-12 with no citation until
2AMLogic/klayout-tools#5856 lands; the rows are deliberately not dropped from
`spec_rows`, and no local checker or "not applicable" record stands in for the
klt field. Re-derive every number above with
`python3 manifests/check_item8_digital_report.py`.
