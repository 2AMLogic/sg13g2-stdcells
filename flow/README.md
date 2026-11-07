# flow

Synthesis and place-and-route recipes (Yosys, OpenROAD), driven through klt.

## Structural power delivery (T1 item 11)

**Every `klt place-and-route` request in this directory carries a `power`
block, and every digital claim built on one is gated on three reads, not
one.** Without `request.power`, `klt place-and-route` still reaches
`target_stage: "route"` and reports `status: "ok"` having run no `tapcell`,
no `global_connect`, no `pdngen` and no filler placement — the routed DEF
has no `SPECIALNETS` section at all, and gate-level LVS still reports
`match`, because a signal-only compare has nothing to say about power. That
is the exact shape `sky130-fpga#41` and `sky130-usb2-phy#59` shipped with.

**`power.row_rail.emitted: true` in a response is not evidence of a PDN
either.** It is a `sky130_fd_sc_hd`-only routing-obstruction fallback
(klayout-tools issue #1442): a real, drawn row-rail shape that keeps the
router from treating a standard cell's own `VPWR`/`VGND` rail as open space
even when `request.power` was omitted entirely. It draws no strap grid, runs
no `tapcell`, and inserts no filler — `emitted: true` only means the
fallback fired, never that a PDN exists.

The three gates, and where each is read:

1. **`power.pdn: true`** in the P&R response, with a named tapcell master.
2. **`power_connectivity.status: "match"`** in a `klt lvs` response — which
   requires `reference.form: "gate-level-verilog"`, the only reference form
   for which `klt lvs` runs the power/ground half of the compare at all.
   Gate on **both** `status` and `power_connectivity.status`; the exit code
   reflects the signal verdict only.
3. **A `klt erc` supply read** declaring `power_net`/`ground_net` as
   `"kind": "supply"` over every strap layer, reporting one electrical
   island per supply and zero `missing_tie`.

## Baseline run (issue #9)

`request-synth.json`, `request-par.json` (with `power: {"preset": "sg13g2"}`),
`request-lvs.json` and `erc-spec.json` run the combinational `rtl/add8.v` on
the stock `sg13g2_stdcell`: `flow/run.sh` writes a new, append-only
`records/<date>-<sha>/` and ends with `check-evidence.sh`, which rejects a
request without a `power` block (`test-check-evidence.sh` proves it). Results,
caveats and the metric definitions are in
`records/20261104-df96543/RECORD.md`.

The earlier note that gate 1 was "unreachable on this PDK today" is
superseded: klayout-tools#2441, #2444 and #2447 are closed, and
`power.preset: "sg13g2"` reaches `power.pdn: true` at `target_stage: route`.
The caveats that remain, from that record: the library has no tap/endcap
cells (`tapcell_master: null`, `tapless: true`), so gate 3's `missing_tie` is
inapplicable rather than zero. (That record's note that `klt drc` was not run
is superseded: `flow/run.sh` now copies the routed GDS into the record and
runs `klt drc`; see `records/20261107-a1a4ec6/RECORD.md`, which quotes the
deck's coverage limits. `GDS_HASH_ONLY=1` keeps only a sha256 and size.)

Cold start: `PDK_ROOT=<dir containing ihp-sg13g2> flow/run.sh`.
