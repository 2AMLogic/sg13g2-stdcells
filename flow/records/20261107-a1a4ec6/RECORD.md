# Routed add8 GDS + `klt drc` (issue #41; T1 digital items 2 and 3)

Append-only: this record adds evidence to the flow baseline in
`../20261104-df96543/RECORD.md`, which is not edited. Produced by `flow/run.sh`
on `a1a4ec6`, stock `sg13g2_stdcell`, `klt 0.9.2.dev244+g92e2b15a66f2`,
KLayout 0.30.13 (klt warns it was tested against 0.30.12; verdict unaffected).
No ETH Zurich / EZ130 figure appears here, and this is not a result for this
library's own cells.

| Artifact | Role |
|---|---|
| `add8.routed.gds` (112150 B, committed) | routed add8 from `klt place-and-route` (`request-par.json`), sha256 `3a3336d6...f2f1fd` |
| `drc.json` | `klt drc --deck sg13g2 --top add8` on that GDS: `status: clean`, `violation_count: 0` |
| `layout-attest.json` | `klt signoff --attest 2`: stream readable, top cell `add8` non-empty, dbu on grid; cites the generator |

Reproducibility (item 2): a second cold run of `flow/run.sh` produced a
byte-identical GDS (same sha256). `layout-attest.json` records that hash as
`provenance.regeneration.regenerated_hash`; klt echoes the generator, it does
not run it.

## DRC coverage (quoted from `drc.json` `coverage`)

A clean verdict here is bounded by what the deck covers.

- `deck_scope` (19): Act, Cnt, Gat, M1, M2, M3, M4, M5, MIM, NW, TM1, TM2, TV1,
  TV2, V1, V2, V3, V4, pSD.
- `layers_in_stream_without_rules` (9): 8/2, 8/25, 10/2, 10/25, 30/2, 30/25,
  134/2, 134/25, 189/4.
- `rules_skipped` (8): metal5.enclosing.mim.1, mim.enclosing.topvia1.1,
  nwell.enclosing.nactiv.1, nwell.enclosing.nactiv.dig.1,
  nwell.enclosing.nactiv.hv.1, nwell.space.nactiv.1,
  nwell.space.nactiv.dig.1, nwell.space.nactiv.hv.1.
- `rules_checked`: 54.

The skipped n-well/n-active rules are not exercised on this layout. This is
the curated deck, not the full IHP signoff deck.

## Closed-issue check

klayout-tools#2444 (spurious violations on power-routed layouts): `klt drc`
now runs on a power-routed P&R GDS and reports 0 violations, consistent with
the fix. The earlier "klt drc was not run" caveat is superseded by this record.
