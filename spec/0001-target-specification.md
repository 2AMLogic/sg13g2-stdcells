# 0001 — Target specification

Status: proposed

Issue: #1. This record is ratified by its own PR being reviewed and merged with
both reviewer keys (`ratification/ee-key/`, `ratification/market-key/`), neither
held by an author of the PR or the design. The `Status:` line above is flipped to
`RATIFIED` in that PR after both keys post and before merge (`CLAUDE.md`).

## Target table

| # | Parameter | Target | Stretch | Reference: EZ130 8T (ETH Zurich's, not ours) |
|---|---|---|---|---|
| 1 | Row height | 3.36 um (8 tracks) | — | 3.36 um |
| 2 | Routing grid | 0.42 um x 0.42 um | — | 0.42 um x 0.42 um |
| 3 | Intra-cell routing | Metal1 only | — | Metal1 only |
| 4 | Pin access | every pin on a grid point | — | every pin on grid |
| 5 | Combinational cells | 40 | 120 | ~180 |
| 6 | Sequential cells | 0 (out of scope, see README Status) | 8 | ~40 |
| 7 | DRC | clean, `klt drc`, sg13g2 deck | — | Calibre clean |
| 8 | LVS | layout-vs-schematic match, `klt lvs` | — | Calibre clean |
| 9 | Liberty corners | TT/1.20 V/25 C | + FF/1.32 V/-40 C, SS/1.08 V/125 C | all three |
| 10 | Benchmark cell area vs `sg13g2_stdcell` | <= 1.00x | <= 0.80x | 0.65x (paper) / 0.67x (library page) |
| 11 | Benchmark energy vs `sg13g2_stdcell` | <= 1.00x | <= 0.80x | 0.61x (paper) / 0.67x (library page) |
| 12 | Benchmark clock period vs `sg13g2_stdcell` | within 10% | within 5% | "virtually the same" |

### Reference attribution

The reference column is ETH Zurich's published result for their EZ130 8T
library, measured with commercial tools on their cells. It is a calibration
point, not a result of this repo, and ratifying this table does not ratify any of
it as ours. The two ETH sources disagree, so each figure carries its source:

| Row | Source | ETH Zurich's stated improvement | Ratio (arithmetic: 1 - stated %) |
|---|---|---|---|
| 10 area | arXiv:2609.29965 (paper) | 35% | 0.65x |
| 10 area | ETH library page | 33% | 0.67x |
| 11 energy | arXiv:2609.29965 (paper) | 39% | 0.61x |
| 11 energy | ETH library page | 33% | 0.67x |

Provenance caveat: the percentages were taken from this repo's `CLAUDE.md`, not
re-read from the paper or the library page by the author of this record. The
ratios are arithmetic on those percentages. The reference counts (~180, ~40) and
"virtually the same" are carried over from the DRAFT README unchanged and are
likewise not re-traced here. The two keys should treat all of these as cited,
not verified.

## Per-row reasoning

### Rows 1–4: geometry — copied deliberately, not derived

Row height, routing grid, Metal1-only intra-cell routing, and on-grid pin access
are taken directly from ETH Zurich's EZ130 8T (arXiv:2609.29965, Apache-2.0).
The copy is the point: a benchmark against `sg13g2_stdcell` is only evidence
about open tools if the geometry matches the reference's. A library on a
different grid would still be a library, but would show the effect of different
choices rather than of the tools. The question ratified here is whether that
reasoning holds, not whether these are the best possible numbers. They are not
re-derived and are unchanged from DRAFT.

### Rows 5–6: counts — ours, and the part that needs argument

Target 40 combinational cells, stretch 120, against the reference's ~180. Zero
sequential cells in target, 8 as stretch. Those are our commitments, not
inherited ones.

**Open question: is a 40-cell combinational set enough to run the synthesis
benchmark rows (10–12)?**

Answer: **yes for a combinational-only benchmark, no for a full-design one. The
counts stay at 40 / 120; the benchmark rows are scoped to match.**

- The risk this canary exists to retire is the generator and the
  characterization path, not cell count. 40 cells cover both: they span the
  families (inverter/buffer, NAND/NOR, AND/OR, AOI/OAI, XOR/XNOR, MUX, adder
  cells) and several drive strengths per family, which is what the generator has
  to produce. A library that cannot characterize is no more useful at 180 cells
  than at 40.
- Yosys/ABC maps combinational logic with only a combinational Liberty, so rows
  10–12 are reachable on combinational logic cones (for example adders,
  comparators, ALU slices) at 40 cells, provided the set is functionally
  complete with enough drive strengths for ABC to size paths.
- A synthesis run on a design containing registers needs flip-flops, which row 6
  puts out of target scope. Rows 10–12 are therefore defined as measured on
  **combinational-only netlists** at target. Whole-design benchmarks that
  include registers become reachable only at the row 6 stretch (8 sequential
  cells), and must be recorded as a separate, labelled benchmark.
- Consequence for comparison: ETH Zurich's figures were not stated to be on
  combinational-only netlists, so a result here at target scope is not
  like-for-like with theirs and must not be presented as such.

No count is changed. If the first benchmark run shows ABC cannot find a mapping
within the ratio bounds because the 40-cell set is too thin, that is recorded as
evidence and raised through a new decision record, not edited into this one.

### Rows 7–8: DRC and LVS

Clean under `klt drc` with the sg13g2 deck and matching under `klt lvs`. The
reference reports Calibre; this repo's tool path is klayout-tools. Numbers are
not comparable and none is claimed.

### Row 9: Liberty corners

TT/1.20 V/25 C at target; FF/1.32 V/-40 C and SS/1.08 V/125 C at stretch. Typical
corner first because Liberty writing is not yet available in `klt`
(`2AMLogic/klayout-tools#2498`); the other two multiply characterization work
without exercising anything new.

### Rows 10–12: benchmark ratios — deliberately weak

Target is <= 1.00x on area and energy ("do not lose to `sg13g2_stdcell`"),
stretch <= 0.80x. Setting the target at ETH Zurich's reported result (0.65x /
0.61x per the paper, 0.67x per the library page) would adopt someone else's
measurement as our commitment before anything is built. Clock period: within 10%
at target, within 5% at stretch; ETH Zurich describe theirs as "virtually the
same". These rows are measured on this repo's own cells with open tools and
recorded as evidence; until then they are unmeasured (README Status).

## Changes from DRAFT

Values: **none.** Every target and stretch value is unchanged from the DRAFT
table in `README.md`.

Wording and scoping, recorded here rather than silently edited:

1. Rows are numbered 1–12 so the keys and later records can cite them.
2. Reference column: the bare "0.65x reported" and "0.61x reported" are replaced
   by per-source figures (paper vs ETH library page), labelled as ETH Zurich's.
   The previous column carried no source, contrary to `CLAUDE.md` § scope
   discipline.
3. Rows 10–12 are scoped to combinational-only netlists at target (see rows
   5–6). This is a clarification of what the unchanged ratios are measured on,
   not a relaxation of any ratio.

## Not ratified here

Cell designs, generators, Liberty output, and the benchmark itself. Rows 9–12
are blocked on `2AMLogic/klayout-tools#2498`.
