# layout

GDS, DRC/LVS reports, and the cell layout generator.

## `gen_layouts.py` — PDK-independent static-CMOS layout generator

Turns the same config `design/gen_netlists.py` reads, plus a `layout` block, into
one deterministic GDSII file per cell. Devices come from `gen_netlists.build`, so
layout and netlist agree by construction. The engine holds no PDK constants:
row height, pitch, layer map and every design rule come from the config. Python
stdlib only (it imports `design/gen_netlists.py` by relative path, so a sibling
pins both files).

```
python3 layout/gen_layouts.py --config layout/example_config.json           # write layout/gds/*.gds
python3 layout/gen_layouts.py --config layout/example_config.json --check   # freshness
python3 -m unittest discover -s layout/tests                                # tests
python3 layout/run_lvs.py --config layout/example_config.json               # LVS -> layout/lvs/
klt drc layout/gds/sg13g2_inv_1.gds --deck sg13g2                           # DRC
```

`--out` defaults to `<config dir>/gds`. Exit codes: `0` ok/fresh, `1` `--check`
found changed, missing or stray `.gds`, `2` invalid config, `3` a cell cannot be
placed (stderr names the cell and the reason; no GDS is written for any cell).
Output is byte-deterministic (own GDSII writer, zero timestamps, sorted shapes),
so `--check` is a byte compare.

### Config contract (`schema_version` 1)

The `process` and `cells` objects are exactly `design/README.md`'s contract. The
`layout` object adds (all required positive ints, nm, except `layers`):

```jsonc
"layout": {
  "row_height_nm": 3360,       // cell height; rails are centred on y=0 and y=row height
  "gate_pitch_nm": 420,        // even; poly pitch = node pitch; cell width = (columns+1) * pitch
  "channel_tracks": 1,         // max Metal1 tracks between the strips (more -> exit 3)
  "n_diff_y0_nm": 400,         // bottom of the NMOS diffusion
  "p_diff_top_margin_nm": 400, // PMOS diffusion top sits this far below the row top
  "layers": {                  // [layer, datatype]; "nsd" is optional
    "nwell": [..], "activ": [..], "gatpoly": [..], "psd": [..], "nsd": [..],
    "cont": [..], "metal1": [..], "metal1_label": [..]
  },
  "rules": {                   // minimum rules used to place shapes
    "poly_width_nm", "poly_space_nm", "poly_endcap_nm", "poly_to_activ_nm",
    "cont_nm", "cont_space_nm", "activ_enc_cont_nm", "poly_enc_cont_nm",
    "m1_width_nm", "m1_space_nm", "rail_width_nm",
    "nwell_enc_pactiv_nm", "sd_enc_activ_nm"
  }
}
```

### Placement model and its limits

One NMOS and one PMOS diffusion strip, Metal1 only. A device of F fingers (the
`ng` from `design/gen_netlists.py`) is F adjacent poly columns on the strip,
alternating source and drain; the columns of one device are joined by a poly bridge
below the NMOS diffusion (`poly_width_nm` tall, `poly_to_activ_nm` clear of it) and
share one gate contact. A poly column crosses both strips, so the NMOS and PMOS
device on one gate net get the same finger count, the larger of the two; the other
is folded into that many fingers (same total width, which must divide evenly on
`process.grid_nm`, default 10, else exit `3`). Cell width is `(columns + 1) *
gate_pitch_nm`, counting fingers. Each strip must be a single chain of devices
sharing source/drain nets, both chains must have the same gate-net sequence, and all
devices in a strip must have the same finger width.

Outside that model the generator exits `3` naming the cell and the reason:
* a diffusion break is needed (XOR, mux) -- including any series stack of
  even-finger devices: F alternating columns end on the net they started on for even
  F, so the next device in the chain cannot share that diffusion (`nand4_1`);
* a gate net driving the columns of two different devices;
* more nets to join than `channel_tracks` -- every extra finger boundary re-attaches
  its net, so a series stack that is folded (`nand2_2`: `Y` and `n1`) needs two
  tracks where the config allows one;
* devices of different finger widths in one strip (`a21oi_1`);
* a row/channel too short, or no Metal1-clean place for a gate contact.

Sequential cells, multi-row cells, well/substrate taps, and Metal2 routing are out
of scope for this first slice. The generator never relaxes a rule to place a cell;
`channel_tracks` and every `rules` value are unchanged from the first slice.

### Pinning from a sibling

A sibling port (e.g. `2AMLogic/sg13cmos5l-stdcells`) pins this repo's generator in
its `reuse.lock.json` by this repo's commit plus the sha256 of
`layout/gen_layouts.py` and `design/gen_netlists.py`, supplies its own config (its
`process`, `layout.layers`, `layout.rules`, geometry), and runs `--check` in CI. It
needs no change to this code; `layout/tests/test_gen_layouts.py::FakeProcess` shows a
second process config producing different output with the same engine.

### Recorded DRC evidence

`layout/drc/*.json` are `klt drc --deck sg13g2 --format json` reports (curated
deck) for `sg13g2_inv_1`, `sg13g2_nand2_1`, `sg13g2_inv_2` and `sg13g2_inv_4`
generated from `example_config.json`: 0 violations on each. `inv_2` and `inv_4` are
the multi-finger cells (2 and 4 columns); both were run with klt `0.9.2.dev103`
(`9f4cec3`) on klayout `0.30.13`, whereas the first two reports were run on klt
`0.9.0.dev1379` / klayout `0.30.12` (each report's `provenance` says which; the
newer reports carry `klayout_version_mismatch: true`). Those are results against the
rules the curated deck models, not a sign-off. The reports list `coverage.rules_checked`;
the deck does not enforce e.g. contact-to-gate spacing or the latch-up and pad
rules, so `coverage.unmodeled_rules` -- `LU.a`, `LU.c`, `LU.c1`, `LU.d`, `LU.d1`,
`Pad.a1`, `Pad.aR`, `Pad.bR`, `Pad.d`, `Pad.d1R`, `Pad.dR`, `Pad.gR`, `Pad.jR`,
`Pad.kR` in every report -- stay unchecked. LVS is recorded separately below;
it does not pass. The example rule values are this repo's draft SG13G2
geometry, not ratified spec rows (issue #1).

Multi-input cells with fingers (`nand2_2`, `buf_2`, ...) are not in the config: with
`channel_tracks: 1` they exit `3` (see above), so the second multi-finger cell
is the 4-finger inverter, not a multi-input cell.

### Recorded LVS evidence (issue #42)

`layout/run_lvs.py` runs `klt lvs` (inline extraction, deck `sg13g2`, reference
form `subckt-call`) on every cell in the config against the netlist
`design/gen_netlists.py` generates from the **same** config
(`layout/example_config.json`; not the `design/netlists/demo_*.spice` files,
which use a different L and supply). It writes `layout/lvs/<cell>.json` and the
reference netlists it compared against, `layout/lvs/netlists/<cell>.spice`.

```
python3 layout/run_lvs.py --config layout/example_config.json           # run, write reports
python3 layout/run_lvs.py --config layout/example_config.json --check   # netlists fresh + klt lvs --check
```

Run from the repo root (klt gets cwd-relative paths). The runner first checks
`klt --help` against `layout/toolchain.json` (`layout/toolchain_pin.py`). Exit
codes: `0` all `match`; `1` tooling error or `--check` drift; `2` invalid
config; `4` reports written but a cell is not `match`.

**Result: all four cells are `status: mismatch`.** Reports are kept as-is.
`power_connectivity.status` is `unchecked` (it does not apply to the
`subckt-call` form, where the rails take part in the ordinary compare).

| cell | status | errors |
| --- | --- | --- |
| `sg13g2_inv_1` | mismatch | 12 |
| `sg13g2_inv_2` | mismatch | 16 |
| `sg13g2_inv_4` | mismatch | 20 |
| `sg13g2_nand2_1` | mismatch | 18 |

Observed in the reports: both sides have the same device count, but no device
or net pairs up, and each report carries `device.body_unverified` warnings. The
generated layouts draw no well or substrate tap (out of scope above), so the
extracted NMOS body sits on the deck-synthesized `vsubs` net and the PMOS body
on an anonymous well net, whereas the reference ties them to `VSS` / `VDD`.
That is the likely root cause, but it is **not demonstrated**: an attempt to
isolate it with `hints.same_nets` was rejected by klt (the anonymous well net
cannot be named), so the signal topology (poly bridge, folded fingers of
`inv_2`/`inv_4`) is still unverified. The tool gap is filed as
2AMLogic/klayout-tools#5125. Closing it in this repo means adding tap
generation to `gen_layouts.py` (separate work), then re-running the runner; a
passing run is a later record that supersedes these, not an edit of them.

Manifest: `manifests/sg13g2-stdcells.json` cites analog items 1 (attested
inventory `manifests/inventories/item1.analog.json`: generator, config and
generated netlists, each netlist freshness-checked), 2 (attested over the four
GDS streams) and 4 (the four LVS reports). `manifests/envelopes/*.json` are
`klt signoff --attest` output. `manifests/signoff-report.*` were regenerated
with `klt signoff --manifest` (T1 3/22 -> 5/22 met); analog item 4 grades
`unmet` / `check_failed`, as it should. Item 2 carries no regeneration claim
(`--generator`/`--regenerated-hash`): for a multi-stream attestation there is
no stated single hash to compare, so it binds the committed bytes only.
