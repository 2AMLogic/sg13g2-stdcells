# Routed-DEF-committed STA re-run (issue #235; T1 digital item 5)

Append-only: this record re-mints the STA + functional-verification pair of
`../20261121-be3a384/RECORD.md` with the one hygiene fix that record could
not carry -- the timed DEF is committed beside its envelope -- and edits no
earlier record. Produced by `flow/run.sh` on `32b1130`, stock
`sg13g2_stdcell`, `klt 0.9.3.dev4596+gaca420899fc0`, KLayout 0.30.13,
IHP-Open-PDK `fetched:0.3.0` (`PDK_ROOT=~/share/pdk`). No ETH Zurich / EZ130
figure appears here, and this is not a result for this library's own cells.

## Why this record exists

`../20261121-be3a384/sta.json` timed a DEF under `flow/.klt/` scratch
(gitignored), so `klt signoff` could only compare its
`provenance.input.content_hash` against the envelope's own claim:
`input: not re-hashed`, `input_verified: null`. Nothing inside the repo could
confirm the timing ran on the record's routed geometry.

`flow/run.sh` now copies the routed DEF into the record as
`add8.routed.def` and points `request-sta.json`'s `def` at that copy, so the
envelope's `def_path` is repo-scoped at
`flow/records/20261124-32b1130/add8.routed.def` and the grader re-hashes a
git-tracked file. Unlike the GDS there is no hash-only mode for the DEF: a
hash without bytes cannot be re-hashed, which is the whole point of the copy.

| Artifact | Role |
|---|---|
| `add8.routed.def` | The routed DEF `sta.json` timed, committed (52 KB) so `def_path` is re-hashable in any checkout |
| `sta.json` | `klt sta` on that copy (`request-sta.json`), same geometry for every corner: TT / 1.20 V / 25 C (`typ_1p20V_25C`), FF / 1.32 V / -40 C (`fast_1p32V_m40C`), SS / 1.08 V / 125 C (`slow_1p08V_125C`) -- spec row 9's target and stretch set |
| `functional-verification.json` | `klt functional-verification` (`../verification/request-fv.json`): the exhaustive `verification/test_add8.py` bench (2^17 = 131072 a/b/cin cases) on Icarus / cocotb, `status: pass` |
| `add8.routed.gds`, `add8.routed.v`, `add8_synth.v`, `synthesize.json`, `place-and-route.json`, `extract.json`, `lvs.json`, `erc.json`, `drc.json` | The full flow baseline, re-run unchanged (`../20261104-df96543/RECORD.md`, `../20261107-a1a4ec6/RECORD.md`) |

## STA results (quoted from `sta.json` `corners[]`)

| Corner | timing_status | setup WNS (ns) | hold WNS (ns) | fmax (MHz) |
|---|---|---|---|---|
| `typ_1p20V_25C` (TT) | constrained | 4.91372 | 4.03743 | 196.607 |
| `fast_1p32V_m40C` (FF) | constrained | 5.28513 | 4.02772 | 212.095 |
| `slow_1p08V_125C` (SS) | constrained | 4.3047 | 4.05772 | 175.583 |

Identical to `../20261121-be3a384/`, corner for corner: the constraint set
(`clk` 10.0 ns, 2.0 ns input/output delays) is unchanged and the geometry is
byte-identical (below).

## Reproducibility

- `add8.routed.def` sha256
  `3c692108ddda21013a3e4c69cc219b41516a7367c000a79601f2825de7d7aa68` --
  the same hash `../20261121-be3a384/sta.json` recorded for its scratch DEF,
  and equal to this record's `sta.json` `provenance.input.content_hash`, so
  `klt signoff` re-hashes the committed file and reports `input_verified:
  true` for the item 5 digital citation.
- `add8.routed.gds` is byte-identical to
  `../20261107-a1a4ec6/add8.routed.gds` and
  `../20261121-be3a384/add8.routed.gds` (sha256 `3a3336d6...f2f1fd`): same
  seed and request, deterministic P&R.
- The FV report's `provenance.input.content_hash`
  (`sha256:634aa17455f1...a53e139`) equals the `1.digital` synthesize pin --
  the same `rtl/add8.v` bytes.

## Gates

`flow/run.sh` ends in `flow/check-evidence.sh` (six-argument form); all five
gates hold on this record: `power.pdn: true`, LVS `match`/`match`, ERC 0
findings / one island per supply, every STA corner constrained with complete
`constraint_completeness` and non-negative setup and hold slack, and a
passing exhaustive FV run.
