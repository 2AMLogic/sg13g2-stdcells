# 0003 — Statistical delay row for the transistor-level cells (local mismatch)

Status: proposed

Issue: #182. Like 0001, this record is ratified by its own PR being reviewed
and merged with both reviewer keys (`ratification/ee-key/` and
`ratification/market-key/`, neither held by an author of the PR or the
design) plus the operator's ratification; the `Status:` line flips to
`RATIFIED` in that PR once both keys post and before the merge (`CLAUDE.md`).
Until then every limit here is a proposed limit, and evidence graded against
it is provisional by construction.

This is the statistical row the tier doc requires before T1 item 6
[analog] can pass (klayout-tools `docs/design-evidence-tiers.md`, item 6,
operator ruling 2AMLogic/klayout-tools#4183, 2026-10-28): an analog
partition with no statistical row is a gap in the spec, the digital
`not_applicable` form is refused, and the item is discharged by adding the
missing row through a ratifiable record and supplying `klt yield` Monte
Carlo evidence for it.

## The row this record adds

One statistical row for the library's transistor-level cells — the
manifest's analog partition — identified as **0003-R1**:

| Row | Parameter | Target | Stretch |
|---|---|---|---|
| 0003-R1 | Per-arc propagation delay under local device mismatch at the row-9 TT corner (TT / 1.20 V / 25 C), PDK mismatch models active | t_pd ≤ 1.10 × t_pd,nominal, with yield ≥ 0.99 per arc at the 95 % confidence lower bound | — |

Definitions:

- **Quantity**: the propagation delay `t_pd` of every input-to-output arc of
  every cell of the library's transistor-level set (the four cells of
  `layout/example_config.json` today; coverage grows append-only as cells
  are added — a cell is covered when a committed campaign covers its arcs,
  with no edit to this row text). The switching arc of a multi-input cell
  holds the non-switching inputs at the rail that enables the arc (the
  pilot holds NAND B high). Thresholds: 50 % of VDD (0.6 V) on the input and
  the output crossings; input edge 0.05 ns (0 → 1.2 V linear ramp); output
  load 10 fF; unit seconds. The committed testbench
  (`sim/yield/testbench-cells.spice`) and limits (`sim/yield/limits.json`)
  pin the measurement; a campaign at a different slew/load point commits its
  own testbench and limits and says so in its record.
- **t_pd,nominal** is the same arc's delay measured identically with
  mismatch off (`mos_tt`), from a committed deterministic run.
- **Corner combination**: the mismatch draws are taken at the row-9 TT
  process corner — `cornerMOSlv.lib` section `mos_tt_mismatch` (which loads
  `sg13g2_moslv_mismatch.lib`'s sigma parameters and
  `sg13g2_moslv_mod_mismatch.lib`'s per-instance `agauss` hooks on `delvto`,
  `factuo`, `w` and `l`, Pelgrom-scaled by 1/sqrt(m·l·w)), supply 1.20 V,
  25 C — combined with the process corner, not instead of it. Mismatch is
  from the PDK's own models, not assumed.
- **Bound**: `t_pd(mismatch) ≤ 1.10 × t_pd,nominal`, one-sided — a faster
  draw never fails, the same one-sidedness as row 12.
- **Required fraction of draws**: ≥ 0.99 per arc at the 95 % confidence
  lower bound (Clopper-Pearson), graded by `klt yield` with its
  sample-size verdict, distribution/capability report, and a deterministic
  negative control that must show the seeded degradation.

## Why this quantity

The analog partition is transistor-level SPICE. The variation that survives
inside a die for it is local (per-instance) mismatch — global PVT is already
the row-9 corner axis, and a statistical row must not re-measure a corner
axis. Delay is the quantity the benchmark rows consume: row 12 budgets path
delay, path delay is composed of cell-arc delays, so a per-arc delay-spread
row at the row-9 corner is the statistical complement of rows 9 and 12.

## The bound is derived from row 12, not from the pilot

Row 12 (spec 0001, RATIFIED): the benchmark clock period — the worst
input-to-output path delay on combinational netlists under a virtual clock
with identical input/output delays on both libraries, post-synthesis, at TT
— must be ≤ 1.10× the stock `sg13g2_stdcell` result (one-sided).

1. **Composition.** A path's delay is the sum of its cell-arc delays (slew
   propagation through the path treated as second-order — assumption A1,
   standard for a first statistical row). If every arc of a path is within
   1.10× its own nominal delay, the path is within 1.10× its nominal delay —
   for any path length, and under the worst-case correlation in which every
   arc of a path is slow in the same draw. Independent per-instance mismatch
   can only do better than that worst case (partial cancellation along a
   path); the row does not take that credit.
2. **Nominal parity (assumption A2).** The 10 % per-arc allowance is the
   row-12 budget exactly when our nominal path delay is at or below the
   stock library's on the benchmark paths (≤ 1.00× — the working target of
   rows 10–12; their benchmark is unrun, README Status "unmeasured"). Then
   path ≤ 1.10 × ours-nominal ≤ 1.10 × stock-nominal = the row-12 budget.
   The remaining margin row 12 offers for statistical spread is therefore
   10 % per arc — that is the bound. The pilot did not set it and cannot
   loosen it.
3. **Re-derivation rule.** A2 is a condition on the row, not a loophole: if
   the row-12 benchmark measures our nominal path ratio
   ρ = D_nominal,ours / D_ref,stock > 1, the per-arc allowance shrinks to
   1.10/ρ and this row must be re-derived through a new decision record.
   The row is never silently re-graded against a loosened bound.
4. **Required fraction.** 0.99 per arc: with no correlation assumption, a
   path of N arcs each meeting 0.99 has path-level yield ≥ 1 − N·0.01 by the
   union bound (≥ 0.95 at N = 5, ≥ 0.90 at N = 10). 0.99 is also the
   smallest round fraction a zero-failure campaign can claim at 95 %
   confidence at this repo's feasible campaign size: n ≥ 367 samples are
   required, and the committed pilot draws n = 400 (the
   `required_n_for_target` verdict in its yield report checks exactly this).

## Where the pilot arcs stand (evidence, not bound-setting)

Pilot: `sg13g2_inv_1` (arc A→Y, both output transitions) and
`sg13g2_nand2_1` (switching arc A→Y with B held high, both output
transitions) at the row's defined measurement point; campaign record
`sim/yield/records/20261122-105858-aeb7c25.md`, replayable inputs and
reports under `sim/yield/`.

Reference delay (the stock PDK inverter `sg13g2_inv_1`, the row-12 benchmark
denominator's equally named cell, same testbench shape, TT nominal):

| Measurement | Stock (s) | Ours nominal (s) | Ratio |
|---|---|---|---|
| inv_tpdlh | 5.00778e-11 | 6.09931e-11 | 1.22x |
| inv_tpdhl | 4.38288e-11 | 5.59375e-11 | 1.28x |

Mismatch draws (seed 20261122, n = 400, `vary: mismatch` at TT), against the
proposed limits (1.10 × nominal), required fraction 0.99:

| Measurement | mean (s) | stddev (ps) | rel. sigma | max (s) | limit (s) | yield [95 % CI] | Cpk | sample size | control |
|---|---|---|---|---|---|---|---|---|---|
| inv_tpdlh | 6.1082e-11 | 1.52 | 2.5 % | 6.5587e-11 | 6.709241e-11 | 1.0000 [0.9908, 1] | 1.32 | sufficient | detected |
| inv_tpdhl | 5.5894e-11 | 1.71 | 3.1 % | 6.0576e-11 | 6.153125e-11 | 1.0000 [0.9908, 1] | 1.10 | sufficient | detected |
| nand_tpdlh | 6.7586e-11 | 1.63 | 2.4 % | 7.2951e-11 | 7.434856e-11 | 1.0000 [0.9908, 1] | 1.38 | sufficient | detected |
| nand_tpdhl | 5.3973e-11 | 1.07 | 2.0 % | 5.7404e-11 | 5.937283e-11 | 1.0000 [0.9908, 1] | 1.69 | sufficient | detected |

No miss against the proposed limits: all four arcs pass at the 95 % lower
bound (0.9908 ≥ 0.99) with zero failures in 400 draws, the sample-size
verdict is sufficient on every arc (`required_n` 183, `required_n_for_target`
368, both ≤ 400), and the deterministic negative control (every DUT channel
width halved; its delays land at 1.55×–1.64× nominal, all draws past the
limits) is detected on all four measurements. Normality of the draws is
`consistent` (Anderson-Darling) on every arc; the parametric estimates agree.

**Finding — nominal parity at risk at the weakest drive bin.** At the
pilot's fixed 10 fF load our `inv_1` (500 n / 800 n) is 1.22×–1.28× slower
than the stock `inv_1` (740 n / 1.12 u). This is *not* the path-level ρ of
assumption A2 — the libraries bin drive strength differently (our `inv_2` at
1000 n / 1600 n is the nearer stock-`inv_1` equivalent, and the synthesis
mapper sizes paths from the whole set), so the definitive parity measure is
the row-12 benchmark itself, which is unrun. It is recorded because, if the
benchmark paths did inherit the weakest-bin ratio, row 12 would fail
nominally with no room left for mismatch; the re-derivation rule (item 3
above) is what reacts to that outcome, and the benchmark rows remain the
gate that decides it.

## Alternatives considered

- **A sigma/Cpk-style row** (e.g. "3σ of delay within ±10 % of nominal"):
  rejected as the ratified form — a `target_yield` on an explicit limit is
  the shape `klt yield` grades and `klt signoff`'s tier-verdict mode
  consumes; capability (Cpk, sigma-to-spec, normality) is reported alongside
  every campaign, not ratified as the row itself.
- **Whole-path Monte Carlo campaigns**: the more direct statistical form of
  the row-12 claim, and the natural successor — blocked on the benchmark
  designs and baseline re-characterization that spec 0001's "Benchmark
  basis" fixes for rows 10–12. The per-arc row is the sufficient condition
  available now (composition argument, item 1); a path-level statistical row
  can supersede it through a later record.
- **Declaring the cells a digital partition** (as 2AMLogic/asap7-stdcells
  does, using the digital `not_applicable` form for item 6): a question
  reserved for the operator. This record neither argues for it nor depends
  on it; for as long as the partition is analog, this row is its
  statistical row.

## Out of scope (unchanged by this record)

- No edit to any row, target or stretch of
  `spec/0001-target-specification.md`.
- No change to `manifests/sg13g2-stdcells.json` — no `kind` or
  `partition_boundary` edit, and no `not_applicable` or gap entry for
  `6.analog`. The row is not cited in the manifest until this record is
  ratified; the citation (and with it `klt signoff` grading T1 item 6
  [analog] against row 0003-R1 with the committed yield report) is the
  separate follow-up PR the issue prescribes.

## Not ratified here

- The pilot's numeric limits in `sim/yield/limits.json` are evidence of this
  pilot, hash-pinned by its yield report — not part of the ratified row. A
  future campaign re-derives its own limits from its own committed nominal
  runs by the row's definition (1.10 × its measured `t_pd,nominal`) and
  grades against them.
- Cells beyond the pilot's two (and arcs beyond the switching arcs measured)
  await their own campaigns; nothing here claims them measured.
