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
Design stage: layout-DRC-LVS-clean
```

<!-- The two fields above are a fixed-location summary a chip-level integrator
     reads without parsing the prose below, so the keys, their spelling, and
     their order do not change — only their values, which are kept current with
     what this repo has produced and recorded evidence for.

     Area (measured, post-layout): the as-built area of a DRC-clean,
     LVS-matched layout, as a number with units (e.g. 1.059 mm²), taken from
     this repo's own committed measurement. Never a target, a plan, or an
     estimate — the ratified bound is the AREA row of the target-specification
     table below. Until such a measurement is committed, the literal
     "not yet measured" — a DRC-clean, LVS-matched layout existing is not a
     measured area.

     Design stage: exactly one token, from this ladder, in order —
     spec | schematic-sim | layout-DRC-LVS-clean | extracted-verified | silicon
     — describing what this repo has produced and recorded evidence for, never
     what it is aiming at. One token; not a range, not a hedge, not prose. -->

**Four combinational cells are generated, DRC-clean and LVS-matched.** Nothing
has been taped out, and nothing has been measured in silicon. Every claim below
names the tracked file that records it; counts are as of `2546575`, 2026-11-14,
and are re-derived from those files rather than restated here where they move.

- **Two generators**, which are the unit of work here — not hand-drawn cells.
  `design/gen_netlists.py` emits transistor-level SPICE from a cell config and
  `layout/gen_layouts.py` emits GDS from the same config
  (`layout/example_config.json`); both re-derive and compare their committed
  outputs under `--check`.
- **Four cells** — `sg13g2_inv_1`, `sg13g2_inv_2`, `sg13g2_inv_4`,
  `sg13g2_nand2_1` — with GDS in `layout/gds/`.
- **DRC clean**, `klt drc`: every per-cell report in `layout/drc/` reads
  `status: "clean"`, `violation_count: 0` (the notch controls under
  `layout/drc/controls/` are negative evidence and read `violations` by
  construction).
- **LVS matched**, `klt lvs`: every report in `layout/lvs/` reads
  `status: "match"`, `error_count: 0`, `body_verification.status: "verified"`.
- **Pre-layout SPICE characterization**:
  `sim/characterize/records/20261121-045231-9214168.md` (the record the
  committed Liberty view cites; superseded originals
  `20261115-220740-13dc481.md`, `20261115-171205-3462cc8.md`,
  `20261115-105337-921b1a8.md`, `20261114-222806-f1cf294.md` and
  `20261107-222836-6ee1577.md` — the full chain is whatever
  `sim/characterize/records/` holds), raw per-arc delay, transition and
  energy tables from `klt characterize`, recorded as
  `Data provenance: simulated` (supersedes, append-only, the records above
  after #73's and #104's config edits and successive main-branch updates
  staled the view's provenance pin — see #82; this one is the first pinned
  to an IHP-Open-PDK commit, #178 — its measured tables are byte-identical
  to the previous view's).
- **One Liberty view**: `views/sg13g2_stdcells_tt_1p20v_25c.lib`, real
  `klt characterize` output covering all four cells at TT / 1.20 V / 25 C (spec
  row 9) — a single corner, combinational arcs only. It is not itself the
  characterization report cited for T1 item #8 — the record behind it is —
  and its `.provenance` sidecar pins the committed config's SHA-256, fresh as
  of that record.
- **Digital half**: the `add8` synthesis and place-and-route flow runs on the
  stock `sg13g2_stdcell` baseline, not yet on this library's cells —
  `flow/records/20261107-a1a4ec6/drc.json` (`clean`) and
  `flow/records/20261104-df96543/lvs.json` (`match`).
- **A graded signoff verdict**: `manifests/signoff-report.txt`, produced by
  `klt signoff` against klayout-tools' own `docs/design-evidence-tiers.md`. It
  reads `tier: none`; the current per-item T1 count is in that file rather than
  restated here, because open work moves it. Both halves of T1 #7 (post-layout
  verification) and the digital half of T1 #8 (characterization report) are
  `[UNMET] reason: no_evidence`; the analog half of #8 is `[MET]`, cited via a
  freshness-checked envelope.

`Design stage: layout-DRC-LVS-clean` is that evidence read against the ladder in
the comment above: DRC clean and LVS matched on all four cells is recorded, and
the rung above it is not — T1 #7 is `[UNMET] reason: no_evidence` and
`environment.extracted_netlist` is `null` in every LVS report, so no extracted
view has been verified.

Caveats the reports record themselves, rather than suppress: the DRC and LVS
runs both carry `provenance.klayout_version_mismatch: true` and
`provenance.deck.released: false`, and the DRC coverage block on `sg13g2_inv_1`
reports `rules_skipped=34` and `layers_in_stream_without_rules=1 (8/25)` against
a `deck_scope` of 20. That is genuine tool output, and `klt signoff` grades the
DRC and LVS items `[MET]` on it — but it is not a signoff against a released
deck, and this block does not claim to be one.

Deliberately not being built yet, and what each waits on:

- **Sequential cells.** Flip-flops and latches need a setup/hold constraint
  search, which is strictly harder than a combinational arc sweep. The
  combinational set comes first; sequential cells wait on that machinery
  working.
- **Liberty at the FF and SS corners.** The committed `.lib` is TT only (spec
  row 9's target); the two-corner stretch goal waits on a multi-corner
  `klt characterize` run and the evidence record for it.
- **The synthesis benchmark on this library.** The area/timing/energy comparison
  in the table below needs a `.lib` spanning enough of the cell set to synthesize
  against; four cells is not that set. It waits on the combinational cell count
  reaching target scope, and on the benchmark basis in the decision record.
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
design/        cell-family netlist generator (transistor-level SPICE)
flow/          synthesis + place-and-route (Yosys, OpenROAD)
layout/        layout generator, GDS + DRC/LVS reports (klayout-tools driven)
manifests/     signoff manifest, evidence envelopes + the klt signoff report
measurements/  silicon characterization (empty until tape-out)
rtl/           Verilog sources
sim/           analog characterization harness + recorded results
spec/          ratified spec + decision records
verification/  cocotb testbenches
views/         generated Liberty views
ratification/  the two reviewer-key skills a spec ratification needs
```

## Continuous integration

`.github/workflows/ci.yml` runs on every pull request and on push to `main`. It
needs only Python 3, `pytest` and `jq` — no klt, ngspice or PDK, so
tool-dependent runs (SPICE, DRC, LVS, place-and-route) are not covered by CI.

The command text lives in exactly one place, [`check-ci.sh`](check-ci.sh): the
workflow runs one stage of it per step, and `npm run check:ci` and `npm test`
call it too, so there is no second copy to drift. To reproduce CI locally, run
`./check-ci.sh` from the repo root, or one stage at a time with
`./check-ci.sh <stage>`:

- `tests` — unit tests (`design/tests`, `layout/tests`, `sim`)
- `attestations` — envelope `content_hash` values match the committed files
- `manifest-pins` — block manifest evidence pins match the envelopes they name
- `netlists` — generated LVS netlists are fresh
- `layouts` — generated layouts are fresh
- `evidence-accept` — the evidence check accepts the committed flow record
- `evidence-reject` — the evidence check rejects the negative control

Which flow record CI gates on is the `FLOW_RECORD` line of that script.

T1 item 10 inventory: README present (this file), license present
([LICENSE](LICENSE)), CI present (`.github/workflows/ci.yml`), and the CI entry script that
holds the item 10 audit checks (`check-ci.sh`, content-pinned so editing it
requires re-minting the item 10 envelope).

## Reproducing the characterization

The committed Liberty view `views/sg13g2_stdcells_tt_1p20v_25c.lib` and the
record behind it are real `klt characterize` output, reproducible from a
clean checkout with three prerequisites this repo does not vendor: `klt`,
`ngspice` (>= 44, for the PDK's OSDI v0.4 PSP103 models), and a git checkout
of [IHP-Open-PDK](https://github.com/IHP-GmbH/IHP-Open-PDK) at the pinned
commit. The runner refuses to measure against anything else: it captures the
checkout's commit before anything is written — a directory that is not a
clean IHP-Open-PDK checkout fails the run, and the revision it captures is
recorded in the evidence record's `**PDK**` header line and the view's
`.lib.provenance` sidecar, so the tree always states which PDK produced it.

The pinned commit is the one the current sidecar names (IHP-Open-PDK
release v0.3.0):

```
5cccb161f7492697cfa52eb14dc03beb00bdca9e
```

Check it out and build the OSDI models it ships as sources (the release
tarball/clone has no prebuilt `.osdi`; the PDK's own installer compiles them
into `libs.tech/ngspice/osdi/`, and that path is a build artifact, not PDK
content — keep the checkout clean by excluding it, e.g. via
`.git/info/exclude`):

```
git clone https://github.com/IHP-GmbH/IHP-Open-PDK.git
cd IHP-Open-PDK && git checkout 5cccb161f7492697cfa52eb14dc03beb00bdca9e
# compile ihp-sg13g2/libs.tech/verilog-a with OpenVAF into
# ihp-sg13g2/libs.tech/ngspice/osdi/psp103.osdi (psp103_nqs, r3_cmc and
# mosvar alongside it if you want the PDK's full set), then:
echo "ihp-sg13g2/libs.tech/ngspice/osdi/" >> .git/info/exclude
```

Then, from this repo's root (one corner per invocation; FF/SS go through
`--backend batch`, never a local loop):

```
python3 -m sim.characterize --library --pdk-dir <IHP-Open-PDK>/ihp-sg13g2
```

This rewrites the view and its sidecar and appends a new record — records
are append-only, so the previous ones stay. The tool-free cold start the T1
item 9 analog inventory attests (`sh sim/characterize/cold_start.sh`) is the
lighter check: request-construction tests plus the freshness checker, no
klt, ngspice or PDK; the invocation above is what actually re-measures.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
