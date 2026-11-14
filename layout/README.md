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
  "layers": {                  // [layer, datatype]; "nsd" is schema-optional
    "nwell": [..], "activ": [..], "gatpoly": [..], "psd": [..], "nsd": [..],
    "cont": [..], "metal1": [..], "metal1_label": [..]
  },
  "rules": {                   // minimum rules used to place shapes
    "poly_width_nm", "poly_space_nm", "poly_endcap_nm", "poly_to_activ_nm",
    "cont_nm", "cont_space_nm", "activ_enc_cont_nm", "poly_enc_cont_nm",
    "m1_width_nm", "m1_space_nm", "rail_width_nm",
    "nwell_enc_pactiv_nm", "nwell_enc_nactiv_nm", "activ_space_nm",
    "sd_enc_activ_nm"
  }
}
```

`nsd` is optional to the *schema* -- a process whose n+ implant is drawn some
other way may omit it -- but it is load-bearing for every cell this generator
draws: each has an n-well tap, and the sg13g2 deck derives a well tie as
`activ & nsd`. A config without `layout.layers.nsd` therefore exits `3` naming
`nsd`, rather than emitting a tap the deck cannot see as a tie.

The two rules the taps added (issue #73):

* `nwell_enc_nactiv_nm` -- n-well enclosure of the well-tie n+ diffusion
  (sg13g2 `nwell.enclosing.nactiv.1`, 0.24 um). A different rule from
  `nwell_enc_pactiv_nm` (`nwell.enclosing.pactiv.1`, 0.31 um); the n-well top
  edge is placed from this one, so reusing the looser p+ value cannot hide
  which rule actually governs the tie.
* `activ_space_nm` -- diffusion-to-diffusion space (`activ.space.1`, 0.21 um),
  the tap band's clearance from the device strips. The band's *height* stays
  derived (`cont_nm + 2 * activ_enc_cont_nm`), so it is not a config key.

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

### Well and substrate taps

Every cell gets two tap bands, generated from the config like everything else
(issue #73). Each is one contact tall plus the diffusion enclosure on either
side (`cont_nm + 2 * activ_enc_cont_nm`), spans the device diffusion's x-range,
and carries one contact per node column plus a Metal1 patch merged with its
rail:

* the **substrate tap** below the NMOS strip ties the p-substrate to VSS:
  `activ` + `psd` (the deck's substrate tie is `activ & psd`);
* the **well tap** above the PMOS strip ties the n-well to VDD: `activ` + `nsd`
  (the deck's well tie is `activ & nsd`), and the n-well's top edge moves up to
  `tap top + nwell_enc_nactiv_nm` to enclose it.

Each band is pushed as close to its rail as the diffusion space
(`activ_space_nm`) and the field-poly clearance (`poly_to_activ_nm`) allow. On
all four cells the **poly**, not the diffusion, is what binds on the VSS side --
the endcap below the NMOS strip on a single-finger cell, and the lower finger
bridge on a folded one, which pushes the band 20 nm further down and off the
rail centre (hence the Metal1 patch). A tap implant abuts the device implant of
the opposite type instead of overlapping it. The generator checks the band it
computed against every shape it actually drew and exits `3` naming the conflict
rather than shrinking a clearance.

Sequential cells, multi-row cells, dedicated tap cells, and Metal2 routing are
out of scope for this slice. The generator never relaxes a rule to place a cell;
`channel_tracks` and every `rules` value carried over from the first slice are
unchanged, and `test_gen_layouts.py::MultiFinger::test_no_rule_value_loosened`
asserts the whole `rules` dict by exact equality, so a relaxation cannot pass
unnoticed.

### Pinning from a sibling

A sibling port (e.g. `2AMLogic/sg13cmos5l-stdcells`) pins this repo's generator in
its `reuse.lock.json` by this repo's commit plus the sha256 of
`layout/gen_layouts.py` and `design/gen_netlists.py`, supplies its own config (its
`process`, `layout.layers`, `layout.rules`, geometry), and runs `--check` in CI. It
needs no change to this code; `layout/tests/test_gen_layouts.py::FakeProcess` shows a
second process config producing different output with the same engine.

### Recorded DRC evidence

`layout/drc/*.json` are `klt drc --deck sg13g2 --format json` reports (curated
deck) for `sg13g2_inv_1`, `sg13g2_inv_2`, `sg13g2_inv_4` and `sg13g2_nand2_1`
generated from `example_config.json`: 0 violations on each. `inv_2` and `inv_4`
are the multi-finger cells (2 and 4 columns).

**These four reports were re-recorded on 2026-11-14** (issue #73), superseding
the 2026-11-07 set, because the tapped layouts are different GDS: the earlier
reports hash layouts with no well or substrate tap and so cannot speak for the
streams now committed. All four were run together on klt
`0.9.2.dev1022+g2a9c52b27ce7` / klayout `0.30.13`, so the split provenance of
the previous set (two reports on klt `0.9.0.dev1379` / klayout `0.30.12`) is
gone; they still carry `klayout_version_mismatch: true`. The deck now models 63
rules, one more than it did for the superseded set (`cont.ongrid.1`, added
upstream; none removed) -- re-running the *unmodified* committed GDS on the
current klt was still clean before the taps were drawn, so nothing in this
re-record is inherited from the version bump.

Those are results against the rules the curated deck models, not a sign-off. The
reports list `coverage.rules_checked` (29 of the deck's 63 rules bite on these
streams; 34 are skipped for layers these cells do not draw). The deck does not
enforce e.g. contact-to-gate spacing or the latch-up and pad rules, so
`coverage.unmodeled_rules` -- `LU.a`, `LU.c`, `LU.c1`, `LU.d`, `LU.d1`,
`Pad.a1`, `Pad.aR`, `Pad.bR`, `Pad.d`, `Pad.d1R`, `Pad.dR`, `Pad.gR`, `Pad.jR`,
`Pad.kR` in every report -- stay unchecked. In particular the latch-up rules are
unmodeled, so these reports do **not** grade tap density or well-tie distance;
what they do check about the new taps is
`nwell.enclosing.nactiv.1` (in `rules_checked` on every report). Note that 0
violations alone never proved a tap exists: the superseded tapless reports were
also clean with that same rule listed as checked, its derived layer simply
empty. The discriminating evidence is the LVS report's
`body_verification.status`, below. The example rule values are this repo's draft
SG13G2 geometry, not ratified spec rows (issue #1).

Multi-input cells with fingers (`nand2_2`, `buf_2`, ...) are not in the config: with
`channel_tracks: 1` they exit `3` (see above), so the second multi-finger cell
is the 4-finger inverter, not a multi-input cell.

### Recorded LVS evidence (issues #42, #73)

`layout/run_lvs.py` runs `klt lvs` (inline extraction, deck `sg13g2`, reference
form `subckt-call`) on every cell in the config against the netlist
`design/gen_netlists.py` generates from the **same** config
(`layout/example_config.json`). It writes `layout/lvs/<cell>.json` and the
reference netlists it compared against, `layout/lvs/netlists/<cell>.spice`.

```
python3 layout/run_lvs.py --config layout/example_config.json           # run, write reports
python3 layout/run_lvs.py --config layout/example_config.json --check   # netlists fresh + klt lvs --check
```

Run from the repo root (klt gets cwd-relative paths). The runner first checks
`klt --help` against `layout/toolchain.json` (`layout/toolchain_pin.py`). Exit
codes: `0` all `match`; `1` tooling error or `--check` drift; `2` invalid
config; `4` reports written but a cell is not `match`.

The request sends `options.combine_devices: true`, recorded in each report's
`options` block. It is there because this generator *folds*: a device of F
fingers is F parallel transistors on one gate net in the layout, where the
reference netlist carries a single device with `ng=F`. Combining parallel
devices makes the comparison count the device the netlist declares. It
configures how the two sides are matched, not how strictly -- the nets are
already 1:1 without it (`counts.nets` was 4/4 on both folded cells while their
devices were 4-vs-2 and 8-vs-2), so what it resolves is the folding alone, not
a topology difference being waved through.

**Result (2026-11-14, issue #73): all four cells are `status: match`,
`error_count: 0`, `body_verification.status: verified`, with no
`device.body_unverified` warning.** `power_connectivity.status` is `unchecked`
(it does not apply to the `subckt-call` form, where the rails take part in the
ordinary compare). `device_parameter_coverage` is empty: these are
topology-and-body matches, not W/L-verified ones. That is not a choice made
here -- asking for `options.compare_parameters` on the MOS classes is accepted
and echoed, and then covers nothing while still grading `match`, which is filed
as 2AMLogic/klayout-tools#5653. Until it closes, no report in this directory
claims a device-geometry comparison.

| cell | status | errors | devices (layout / ref / matched) | nets |
| --- | --- | --- | --- | --- |
| `sg13g2_inv_1` | match | 0 | 2 / 2 / 2 | 4 / 4 / 4 |
| `sg13g2_inv_2` | match | 0 | 2 / 2 / 2 | 4 / 4 / 4 |
| `sg13g2_inv_4` | match | 0 | 2 / 2 / 2 | 4 / 4 / 4 |
| `sg13g2_nand2_1` | match | 0 | 4 / 4 / 4 | 6 / 6 / 6 |

**These reports supersede the 2026-11-07 set**, which recorded all four cells as
`mismatch` (12 / 16 / 20 / 18 errors) with `body_verification.status:
unverified`. They are not an edit of those: the earlier reports were a correct
record of tapless layouts, and the layouts themselves have changed. Two things
in this slice moved the verdict, in this order:

1. **The taps.** The earlier reports named the cause as a guess -- no well or
   substrate tap, so the extracted NMOS body sat on the deck-synthesized
   `vsubs` net and the PMOS body on an anonymous well net while the reference
   tied them to `VSS` / `VDD` -- and could not demonstrate it, because
   `hints.same_nets` cannot name an anonymous net
   (2AMLogic/klayout-tools#5125, still open; this slice did not need it to
   close). Drawing the taps settles it: `body_verification` flips to `verified`
   on all four cells, the layout net count drops from 6 to 4 as `vsubs` and the
   anonymous well net collapse into `VSS` / `VDD`, and `sg13g2_inv_1` and
   `sg13g2_nand2_1` reach `match` on the taps alone.
2. **`combine_devices`.** With bodies verified, the two folded cells were still
   `mismatch` -- `sg13g2_inv_2` 14 errors, `sg13g2_inv_4` 18 -- with
   `counts.devices` 4-vs-2 and 8-vs-2 but `counts.nets` already 4/4. That
   residue was finger folding and nothing else, and the option above closes it.

So the signal topology of the folded cells -- the poly bridge and the per-finger
source/drain alternation that the earlier record left unverified -- is now
verified against the generated netlist.

Manifest: `manifests/sg13g2-stdcells.json` cites analog items 1 (attested
inventory `manifests/inventories/item1.analog.json`: generator, config and
generated netlists, each netlist freshness-checked), 2 (attested over the four
GDS streams) and 4 (the four LVS reports). `manifests/envelopes/*.json` are
`klt signoff --attest` output. Both analog envelopes were **re-attested** for
issue #73 and their `content_hash` values updated in the manifest: item 1
because the new `rules` keys changed `layout/example_config.json`, item 2
because every GDS was regenerated. Item 2 carries no regeneration claim
(`--generator`/`--regenerated-hash`): for a multi-stream attestation there is
no stated single hash to compare, so it binds the committed bytes only. The
reference netlists under `layout/lvs/netlists/` are byte-unchanged --
`design/gen_netlists.py` never reads the `layout` block -- so item 1's
freshness commands still pass on the same bytes.

`manifests/signoff-report.*` were then regenerated with `klt signoff
--manifest` (write them with a shell redirect; `-o` applies only to
`--attest`). **T1 is now 8/22 met, up from 7/22, with `T1 #4 [analog] LVS
clean` MET** on the strength of the reports above; item 3 `[analog]` still
cites only `layout/drc/sg13g2_inv_1.json`, so widening that citation to all
four DRC reports remains open. `klt signoff --manifest --check
manifests/signoff-report.json` reports `status: match` against the committed
report; the generating run exits `3` because the block has not reached T1 as a
whole, not because a cited check failed.

**T1 is now 11/22 met, up from 8/22 (issue #75).** Three items the repo had
already recorded but never cited are now cited, each by a `klt signoff
--attest` envelope under `manifests/envelopes/`: `T1 #9 [digital] Testbenches
shipped` (inventory `manifests/inventories/item9.digital.json` — the exhaustive
cocotb check of `rtl/add8.v`, its Makefile and `verification/cold_start.sh`,
whose cold start is *run* by the attestation, not merely declared), and `T1 #10
Repo hygiene` on **both** partitions from the single envelope
`manifests/envelopes/item10.attest.json` (inventory
`manifests/inventories/item10.json` — the three files `README.md` names as its
item 10 inventory, backed by the three dependency-free gates of
`.github/workflows/ci.yml`). No new evidence was produced for any of them; only
the citations were missing. `klt signoff --manifest --check
manifests/signoff-report.json` reports `status: match` with `doc_drift: false`,
and both new envelopes re-attest (`klt signoff --attest <n> --inventory <inv>
--check <envelope>`, exit 0).

`T1 #8 [analog] Characterization report` is **not** cited, and stays
`no_evidence` — deliberately, with the attestation committed as it graded. Its
inventory (`manifests/inventories/item8.analog.json`) is committed and names
the report `sim/characterize/records/20261107-222836-6ee1577.md` and, for spec
row 9, the Liberty view and its provenance sidecar; its freshness command
(`python3 -m sim.characterize.check_library`, new) re-derives every claim the
sidecar makes, and it **fails**: the sidecar pins
`layout/example_config.json` at `sha256:1a02f3cc…`, and the committed config
hashes `sha256:8e360822…`. Issue #73 added two `layout.rules` keys
(`activ_space_nm`, `nwell_enc_nactiv_nm`) for the well and substrate taps
*after* the view was characterized. Nothing the characterization consumes
changed — the config's `process` and `cells` blocks are byte-identical at both
hashes, and `design/gen_netlists.py` never reads the `layout` block — but the
sidecar pins the whole file, so the recorded provenance no longer matches the
tree. The view has to be regenerated (or the pin narrowed to what
characterization actually consumes) before item 8 can be cited; that needs a
`klt characterize` run against the PDK, which issue #75 put out of scope. The
check was deliberately not weakened to pass: a freshness command that cannot
fail is not evidence. Tracked in issue #82.

The friction this surfaced is filed as 2AMLogic/klayout-tools#5688: `klt
signoff --attest 8` documents its `citations` as evidence-envelope paths but
checks only that each file exists, delegating all content verification to the
caller's `envelope_checks` command — which it accepts unconstrained, `true`
included. That is precisely why the command behind this repo's item 8 citation
was written to be falsifiable rather than merely present.
