# item5 — T1 item 5 analog corner evidence (spec row 9)

`klt sim` testbenches and envelopes that grade **T1 item 5 [analog]** against
the ratified target specification (`spec/0001-target-specification.md`, rows
1-12). The item's declared analog row set is **row 9 alone** — "Liberty
corners", target TT / 1.20 V / 25 C — and the evidence set covers it at that
corner for the four committed cells (`sg13g2_inv_1`, `sg13g2_inv_2`,
`sg13g2_inv_4`, `sg13g2_nand2_1`). Dispositions for the other eleven rows
(graded by other T1 items or not electrical quantities) are in PR #180's
description; the manifest declares the set as `spec_rows."5.analog"`.

Nothing here edits or rewrites the spec, and nothing relaxes a bound: the
spec has **no cell delay or transition bound**, so the numeric limits below
are **testbench checks** — a testbench may only check a measurement against
something already committed, which for this row means the supply rails and
the committed Liberty view.

## The two testbenches (per cell)

Both run at the row 9 target corner — process `mos_tt`, 1.20 V supply, 25 C
(`sim/harness/corners.py`'s `tt` pairing, the same table `klt characterize`
uses) — with the PDK's `cornerMOSlv.lib` models and the `psp103.osdi`
preload, exactly as `sim/characterize/` binds them. Both requests are
assembled by one shared function that reads that pairing once and refuses a
stimulus rail that is not its supply: the function deck swings to the config's
`supply_v`, the timing deck to the view's `nom_voltage`, and a disagreement
raises before `klt` is ever run. The cell under test is never copied: each
generated testbench `.include`s the committed `design/gen_netlists.py` output
under `layout/lvs/netlists/` (the files CI's `netlists` stage checks fresh),
so the deck's netlist closure pins the generated cell's bytes
(`environment.netlist_closure` in each envelope).

**function** — one unloaded DUT; inputs step through every input combination
(two states for the inverters, four for the NAND), each held 3 ns after a
20 ps edge, output sampled 2 ns into each state.

**timing** — one DUT instance per (timing arc, input transition, output
load) of the committed view's 5x5 grid (25 points per arc, 2 arcs for the
NAND), each instance with its own ramp source and private load capacitor,
all in one `tran` — the same one-deck-many-instances layout `klt
characterize` documents. Timing arcs are derived from the cell's own
function string (first sensitizing input assignment in fixed enumeration
order), and the derived arc set and senses are asserted against the
committed view before any request is built.

## Measurement conventions

Every timing convention is read from the committed view's own header, never
retyped: delay thresholds (50 % of supply, in and out), slew thresholds
(20 % / 80 %), the axes themselves, and every expected value. The stimulus
replicates `klt characterize`'s: a **linear rail-to-rail ramp whose
threshold-to-threshold duration equals the tabulated input transition**
(`ramp = slew / (0.8 - 0.2)`), so the measured quantity is the same one the
view tabulates. The transient window mirrors the characterizer's settle
rule (2 ns settles, 8 ns window) and its pinned `tmax` (1 ps).

## Limits (testbench checks, not spec bounds)

| Measurement | Limit | Source of the bound |
|---|---|---|
| function, output high | within 10 mV of the 1.20 V rail | the committed supply rail (`layout/example_config.json` `supply_v`); a settled static-CMOS output draws no DC current |
| function, output low | at most 10 mV | same |
| timing, delay / transition | view value at the same (slew, load) ± 2 % | the committed `views/sg13g2_stdcells_tt_1p20v_25c.lib` |
| timing, input-slew self-check | tabulated input transition ± 2 % | the view's own axis |

**The 2 % tolerance, and why.** The committed view was measured by `klt
characterize` under the same conventions these testbenches replicate — same
ramp law, same thresholds, same models, same corner, same one-deck instance
isolation — so agreement is expected to solver noise, not to a characterizer
difference. Observed worst-case disagreement across the committed record
(`records/20261121-135717-f5cb68a`, all four cells, full grids): **0.058 %**.
2 % is ~35x that drift: far too tight to hide a real divergence — a stale
view, a wrong arc, a mis-sized or mis-wired instance moves a value by whole
percent — and far too loose to trip on solver noise, interpolation on the
1 ps grid, or a future ngspice point release. The 10 mV rail tolerance is
the same shape: 100x smaller than the opposite rail a wrong function
produces, 100x larger than the microvolt residual of a settled output.

## Running and records

```
python3 -m sim.item5 --pdk-dir <ihp-sg13g2 dir>   # local backend, one corner
python3 -m pytest sim/item5/tests                 # pure builders, no tools
```

One record per invocation, append-only (`sim/item5/records/<id>/` holds each
generated testbench, its request document and the `klt sim` envelope exactly
as klt emitted it; `<id>.md` summarises). A run that does not grade `pass`
on every measurement commits nothing. The record's Citations block is the
manifest's `evidence."5.analog"` list: one `{file, content_hash, rows:
["9"]}` entry per envelope, where `content_hash` pins the envelope's
`provenance.input.content_hash` (the testbench netlist's bytes), so editing
a committed testbench stales its citation. FF/SS corner legs (spec row 9
stretch) would be `--backend batch` runs with `--wait-for-capacity` per the
host rule; none exist yet, and the target corner is TT.

Row coverage is **derived**, not asserted: every measurement carries
`spec_row: "9"`, `klt sim` echoes the tag into the envelope, and `klt
signoff` derives the citation's coverage from those tags
(`row_coverage.row_sources: {"9": "derived"}` in the graded report).
