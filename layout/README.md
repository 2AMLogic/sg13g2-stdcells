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

One NMOS and one PMOS diffusion strip, one poly column per device pair, Metal1
only. Each strip must be a single chain of devices sharing source/drain nets, and
both chains must have the same gate-net sequence. Outside that model the generator
exits `3` naming the reason, e.g. a diffusion break is needed (XOR, mux), a
multi-finger device, a gate net driving two columns, more nets to join than
`channel_tracks`, or no Metal1-clean place for a gate contact. Sequential cells,
multi-row cells, well/substrate taps, and Metal2 routing are out of scope for this
first slice. The generator never relaxes a rule to place a cell.

### Pinning from a sibling

A sibling port (e.g. `2AMLogic/sg13cmos5l-stdcells`) pins this repo's generator in
its `reuse.lock.json` by this repo's commit plus the sha256 of
`layout/gen_layouts.py` and `design/gen_netlists.py`, supplies its own config (its
`process`, `layout.layers`, `layout.rules`, geometry), and runs `--check` in CI. It
needs no change to this code; `layout/tests/test_gen_layouts.py::FakeProcess` shows a
second process config producing different output with the same engine.

### Recorded DRC evidence

`layout/drc/*.json` are `klt drc --deck sg13g2 --format json` reports (curated
deck, klt pinned in `toolchain.json`) for `sg13g2_inv_1` and `sg13g2_nand2_1`
generated from `example_config.json`: 0 violations on each. That is a result
against the rules the curated deck models, not a sign-off. The reports list
`coverage.rules_checked`; the deck does not enforce e.g. contact-to-gate spacing or
the latch-up rules (see `coverage.unmodeled_rules`), and no LVS has been run on
these cells. The example rule values are this repo's draft SG13G2 geometry, not
ratified spec rows (issue #1).
