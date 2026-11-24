# Multi-corner STA + functional verification (issue #175; T1 digital item 5)

Append-only: this record adds evidence to the flow baseline in
`../20261104-df96543/RECORD.md` and `../20261107-a1a4ec6/RECORD.md`, neither
of which is edited. Produced by `flow/run.sh` on `be3a384`, stock
`sg13g2_stdcell`, `klt 0.9.3.dev2575+g6bd18bbc8637`, OpenROAD
`26Q3-1510-g6cb3f2b704`, IHP-Open-PDK `fetched:0.3.0`. No ETH Zurich / EZ130
figure appears here, and this is not a result for this library's own cells.

| Artifact | Role |
|---|---|
| `sta.json` | `klt sta` on this run's routed DEF (`request-sta.json`), the same geometry for every corner: TT / 1.20 V / 25 C (`typ_1p20V_25C`), FF / 1.32 V / -40 C (`fast_1p32V_m40C`), SS / 1.08 V / 125 C (`slow_1p08V_125C`) — spec row 9's target and stretch set |
| `functional-verification.json` | `klt functional-verification` (`../verification/request-fv.json`): the exhaustive `verification/test_add8.py` bench (2^17 = 131072 a/b/cin cases, 131072 ns sim time) on Icarus 13.0 / cocotb 2.0.1, `status: pass` |

## Timing constraint

`clk` (the port `rtl/add8.v` carries for this purpose), 10.0 ns period — the
same clock `request-par.json` sets — with `input_delay_ns`/`output_delay_ns`
of 2.0 ns each, so the in-to-out paths are really timed. No period or delay
was loosened to close a corner. The `place-and-route` envelope in this record
still reports `timing_status: unconstrained` (`worst_slack_ns: 1e+39`): the
in-flow STA carries no I/O delays and `clk` drives nothing, which is exactly
why the standalone `klt sta` run exists.

## STA results (quoted from `sta.json` `corners[]`)

| Corner | timing_status | setup WNS (ns) | hold WNS (ns) | fmax (MHz) | violations (setup/hold) |
|---|---|---|---|---|---|
| `typ_1p20V_25C` (TT) | constrained | 4.91372 | 4.03743 | 196.607 | 0 / 0 |
| `fast_1p32V_m40C` (FF) | constrained | 5.28513 | 4.02772 | 212.095 | 0 / 0 |
| `slow_1p08V_125C` (SS) | constrained | 4.3047 | 4.05772 | 175.583 | 0 / 0 |

`constraint_completeness.status` is `complete` at every corner. No SPEF was
supplied, so wire RC is LEF-capacitance-only (optimistic relative to a
post-route estimate; `spef_annotation` is `null`). Worst corner is SS with
4.30 ns setup margin: the 10 ns budget less 2.0 + 2.0 ns I/O delays leaves
6.0 ns for the path, and the routed 8-bit adder uses ~1.7 ns of it.

## Gates

`flow/check-evidence.sh` now takes the STA and functional-verification
envelopes as an optional pair (both or neither) and fails on any corner that
is not `constrained`, on negative setup or hold slack, on an empty corner
list, on a non-passing run, on a partial pair and on an unreadable report;
`flow/test-check-evidence.sh` exercises every case. The three power gates of
`../20261104-df96543/RECORD.md` are unchanged and also hold on this run
(`power.pdn: true`, LVS `match`/`match`, ERC 0 findings / one island per
supply).

## Reproducibility

The routed GDS in this record is byte-identical to
`../20261107-a1a4ec6/add8.routed.gds` (sha256 `3a3336d6...f2f1fd`): same seed
and request, deterministic P&R. The FV report's `provenance.input.content_hash`
(`sha256:634aa17455f1...a53e139`) equals the `1.digital` synthesize pin — the
same `rtl/add8.v` bytes. The DEF timed by `sta.json` is this run's own
`def_path` (`provenance.input.content_hash`
`sha256:3c692108ddda21013a3e4c69cc219b41516a7367c000a79601f2825de7d7aa68`);
it lives in `flow/.klt/` scratch and is pinned by that hash, not by a path.
