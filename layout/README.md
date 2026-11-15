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
  "layers": {                  // [layer, datatype], all required
    "nwell": [..], "activ": [..], "gatpoly": [..], "psd": [..], "nsd": [..],
    "cont": [..], "metal1": [..], "metal1_label": [..]
  },
  "rules": {                   // minimum rules used to place shapes
    "poly_width_nm", "poly_space_nm", "poly_endcap_nm", "poly_to_activ_nm",
    "cont_nm", "cont_space_nm", "activ_enc_cont_nm", "poly_enc_cont_nm",
    "m1_width_nm", "m1_space_nm", "rail_width_nm",
    "nwell_enc_pactiv_nm", "nwell_enc_nactiv_nm", "activ_space_nm",
    "sd_enc_activ_nm", "psd_space_nm", "nwell_space_nm"
  }
}
```

Every layer in the block is required, including `nsd` (issue #80): each cell
draws an n-well tap, and the sg13g2 deck derives a well tie as
`activ & nsd`, so there is no configuration in which the generator does not
need it. A config without `layout.layers.nsd` is a config error -- exit `2`
naming `nsd`, before any placement work -- not a placement outcome.

The two rules the taps added (issue #73):

* `nwell_enc_nactiv_nm` -- n-well enclosure of the well-tie n+ diffusion
  (sg13g2 `nwell.enclosing.nactiv.1`, 0.24 um). A different rule from
  `nwell_enc_pactiv_nm` (`nwell.enclosing.pactiv.1`, 0.31 um); the n-well top
  edge is placed from this one, so reusing the looser p+ value cannot hide
  which rule actually governs the tie.
* `activ_space_nm` -- diffusion-to-diffusion space (`activ.space.1`, 0.21 um),
  the tap band's clearance from the device strips. The band's *height* stays
  derived (`cont_nm + 2 * activ_enc_cont_nm`), so it is not a config key.

The two rules the notch predicate added (issue #86):

* `psd_space_nm` -- p+ implant space-or-notch (`psd.space.1`, 0.31 um), the
  PMOS strip's implant notch minimum. The deck models no `nsd` space rule, so
  there is deliberately no `nsd_space_nm`: the NMOS strip's implant has
  nothing to violate, which is what makes the notch check strip-asymmetric.
* `nwell_space_nm` -- n-well space-or-notch (`nwell.space.1`, 0.62 um), the
  widest notch minimum the generator enforces; on the PMOS strip it binds
  wherever `k * gate_pitch_nm` sits between the psd band and 1540 nm.
  Both are required keys: the notch predicate refuses a config that omits one
  (exit `2` naming the key) rather than silently skipping a check.

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
sharing source/drain nets, and both chains must have the same gate-net sequence.

A strip may hold devices of **different drawn finger widths** (issue #74). Each
strip keeps a fixed outer edge -- the NMOS strip grows up from `n_diff_y0_nm`,
the PMOS strip grows down from `row_height_nm - p_diff_top_margin_nm` -- and its
channel-facing edge steps at the device boundary. The strip is drawn as one
rectangle per run of equal-height columns, each reaching `cont_nm / 2 +
activ_enc_cont_nm` past the node column it shares with its neighbour, so the
runs overlap there and merge into a single stepped polygon. `psd`, `nsd` and the
n-well follow the same step rather than being drawn once over the tallest run,
which would over-enclose the short runs and can break the implant space rule
against a neighbouring cell. Every channel-facing value -- the channel check,
`track_base`, the gate-pad height -- is taken from the **tallest** run, so a
short device cannot loosen a clearance by accident, and each node's contact
stack is sized from the **shorter** of its two columns.

Two limits the step brings with it:

* **A valley in the height profile may not notch narrower than a space rule.**
  `activ.space.1`, `psd.space.1` and `nwell.space.1` are minimum space *or
  notch* rules, so a tall-short-tall run leaves a re-entrant notch in the
  merged polygon whose facing edges can sit under a minimum -- but whether
  one actually does is a function of the short run's width, the pitch and the
  strip, not a yes/no on "has a valley":

  - a short run of `k` columns leaves an opening of
    `k * gate_pitch_nm - 2 * hang` in each layer drawn over it, where `hang` is
    how far that layer's rectangle reaches past the node columns it spans
    (`cont_nm / 2 + activ_enc_cont_nm` for activ; the implant and the n-well
    reach further by `sd_enc_activ_nm` and `nwell_enc_pactiv_nm`, so they are
    the *binding* layers wherever they notch at all);
  - a layer is legal when the opening is **<= 0** -- the taller neighbours'
    rectangles overlap and the layer merges, leaving no notch in it at all --
    or **>= the layer's space minimum**. Strictly between is the forbidden
    band, so legality is *non-monotone* in the pitch: wider can be legal again;
  - the check is **strip-asymmetric**: activ is checked on both strips, psd
    and the n-well on the PMOS strip only. The sg13g2 deck models no `nsd`
    space rule, so the NMOS strip's implant has nothing to violate -- a notch
    can be legal on NMOS and refused on PMOS at the same geometry. The three
    thresholds live in `layout.rules` as `activ_space_nm`, `psd_space_nm` and
    `nwell_space_nm`; the generator refuses a config that omits one rather
    than silently skipping the check.

  The generator refuses a profile whose valley falls into some layer's
  forbidden band, naming the cell, the strip, the profile, the offending
  layer and both numbers -- opening vs. threshold (exit `3`); a valley every
  layer admits is drawn. The predicate is measured, not just asserted:
  `layout/drc/controls/` holds a stub-forced NMOS notch at `gate_pitch_nm`
  840 (admitted: `clean`) and refused controls at 840 (PMOS, one
  `psd.space.1`) and at the shipped 420 (NMOS, one `activ.space.1`). A
  monotone step is a single concave corner and is fine. The generator does
  not reorder the strip to avoid a notch: a width-aware `order_strips` would
  place a few more cells, but on its own it would silently draw a notch for
  any cell with no monotone ordering, and this generator never draws a shape
  a rule forbids. So a cell that has a monotone ordering which
  `order_strips` does not happen to pick is refused today -- making the
  ordering width-aware *in addition to* the notch predicate is deliberately
  left as separate work. No cell reachable through `design/gen_netlists.py`
  produces a notched profile at present.
* **A contact needs `2 * activ_enc_cont_nm + cont_nm` of diffusion height
  (300 nm as shipped), per device.** A device folded below it is refused even
  when the strip's tallest run is far above it, because the contact has to fit
  inside that device's own run.

Outside that model the generator exits `3` naming the cell and the reason:
* a diffusion break is needed (XOR, mux) -- including any series stack of
  even-finger devices: F alternating columns end on the net they started on for even
  F, so the next device in the chain cannot share that diffusion (`nand4_1`);
* a gate net driving the columns of two different devices;
* more nets to join than `channel_tracks` -- every extra finger boundary re-attaches
  its net, so a series stack that is folded (`nand2_2`: `Y` and `n1`) needs two
  tracks where the config allows one;
* a strip whose height profile is tall-short-tall, or a device drawn too short
  for a contact (both above);
* a channel narrower than the two implant enclosures (`2 * sd_enc_activ_nm`),
  where `psd` over the PMOS strip would overlap `nsd` over the NMOS strip;
* a row/channel too short, or no Metal1-clean place for a gate contact.

A failure message names the **netlist** finger width and the **drawn**
(post-fold) one separately, because the fold divides a width that can be uniform
in the netlist: `nor2_1`'s netlist is a uniform 500 nm and it is drawn as
`2 x 250 nm`, so a message quoting only the drawn number sends the reader
hunting for a width the netlist does not contain.

#### What still blocks the AND/OR and AOI/OAI families

Lifting the one-height-per-strip limit does not by itself add a cell: each of
the four cells issue #74 originally named is blocked by a *further* limit, and
three of them by one this generator has never had. Measured on `2546575` by
building a one-cell config per cell and reading the reported failure:

| cell | drawn NMOS / PMOS finger widths | next limit |
|---|---|---|
| `and2_1` | `[1000, 1000, 500]` / `[800]` | needs 2 channel tracks (`X`, `X_i`), config allows 1 |
| `or2_1` | `[250, 500]` / `[800]` | PMOS needs a diffusion break |
| `a21oi_1` | `[250, 500]` / `[800]` | NMOS needs a diffusion break |
| `o21ai_1` | `[500, 1000]` / `[800]` | no shared gate-net sequence (gate nets cannot align in columns) |
| `xor2_1` | `[250, 500]` / `[400, 800]` | NMOS needs a diffusion break |

So the capability is exercised in `test_gen_layouts.py::MixedFingerWidths` on
synthetic configs, the way `FakeProcess` exercises a second process -- `and2_1`
places with a stepped NMOS strip once the synthetic row gives it two channel
tracks and a wider pitch. The committed config's `channel_tracks` and `rules`
are unchanged.

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

### Recorded notch controls (issue #86)

`layout/drc/controls/` holds the measured counterpart of the height-profile
predicate: four stub-forced layouts covering the predicate's arms (the
`opening >= threshold` admit, the `opening <= 0` merged admit, and the
refusal), each with its `klt drc --deck sg13g2 --format json` report next to
it (and `klt drc --check` passing against the committed GDS):

* `notch-nmos-p840-admitted` -- an `and2`-shaped row at `gate_pitch_nm` 840
  whose NMOS strip is forced from `[1000, 1000, 500]` to `[1000, 500, 1000]`.
  The predicate admits it (activ opening `840 - 300 = 540 >= 210`; the deck
  models no `nsd` space rule) and the deck agrees: `clean`, 0 violations,
  with `activ.space.1`, `psd.space.1` and `nwell.space.1` all in
  `rules_checked`. This is the row the issue was filed from.
* `notch-pmos-p840-refused` -- the same row with the *PMOS* strip forced to
  `[800, 500, 800]`, drawn only because the predicate was stubbed off. The
  deck flags exactly one `psd.space.1` (`840 - 660 = 180 < 310`), recorded
  via `--negative-control-categories psd.space.1`. This is the row an
  activ-only check would wrongly admit.
* `notch-nmos-p420-refused` -- `inv_4` at the shipped 420 pitch, NMOS forced
  to `[500, 320, 500, 500]`: one `activ.space.1` (`420 - 300 = 120 < 210`),
  the row where refusing every valley was already right.
* `notch-pmos-p600-merged` -- the shipped `inv_4` device set at
  `gate_pitch_nm` 600, PMOS strip forced to `[800, 500, 800, 800]`, drawn
  with `_notch_violation` left live (the predicate admits this row). This is
  the `opening <= 0` arm's measurement: the psd opening `600 - 660 = -60` and
  the n-well opening `600 - 920 = -320` are both negative -- the taller
  neighbours' rectangles overlap, the layers merge, and there is no notch in
  them at all. **It measures the merged arm for psd and nwell only**: activ
  is admitted here on the *other* arm (`600 - 300 = 300 >= 210`), and
  activ's own merged arm (`k * pitch <= 300` at `k = 1`) is reached by no
  shipped-cell geometry at a placeable pitch, so no control covers it. The
  deck agrees the merged rows are clean: `clean`, 0 violations, with all
  three space-or-notch rules in `rules_checked`.

The controls are regenerable the way the shipped GDS is:
`python3 layout/gen_controls.py --check` rebuilds every stream in memory and
fails on any drift (`check-ci.sh layouts` runs it on every PR); without
`--check` it rewrites the `.gds` files (the `.json` reports are recorded
evidence and are never touched). The script holds the control table -- per
control the base cell, the `layout` overrides, the forced strip profile and
whether `_notch_violation` was stubbed off -- and drives the generator's own
drawing engine with `_strip_profile` patched, the same forcing
`layout/tests/test_gen_layouts.py::ForcedNotch` exercises. Two inputs the
per-control notes above do not spell out: the config cell is renamed to
`notch_<strip>_p<pitch>` -- it is the stream's GDS structure name, with
`_lib` appended for the library name (`notch_n_p420_lib` / `notch_n_p420`)
-- and the two 840-pitch rows need `row_height_nm` 4200 and
`channel_tracks` 2 alongside the `gate_pitch_nm` 840 bump; the table is the
source of truth for both. The committed GDS is deterministic, and each
report's `provenance.input.content_hash` pins the exact stream it graded. Recorded on klt `0.9.2.dev1029+g76f47afa48f1` /
klayout `0.30.13`, deck `sg13g2` -- except `notch-pmos-p600-merged`, recorded
on klt `0.9.3.dev3+gd5d57daf9a14` (klayout `0.30.13`). The deck's
`content_hash` is byte-identical across the two klt versions
(`sha256:cf6dfeadf75bd95bf89beb0a64e06ed43b65f6ff782df10ae200ea200a73d8e9`,
the value every four reports carry), so the three earlier controls remain
valid evidence without re-recording.

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

**The envelopes are now gated (issue #103).** When an attested file changes,
its envelope must be re-attested — the same practice as the #73 re-attestation
above — and, until #103, nothing committed noticed when that step was skipped:
`df690f0` edited `README.md` and PR #90 edited `.github/workflows/ci.yml`
without re-attesting item 10, and a re-attestation of item 9 (its
`verification/Makefile` changed in PR #108) went missing the same way. All
three are re-attested here through `klt signoff --attest <n>` (item 10: 6/6
checks pass; item 9: the cocotb cold start passes, 2.0.0/iverilog 13.0, 6/6).
The merge of `main` during PR #112's own fix round brought #105's edit to
`design/gen_netlists.py` — an attested path in item 1's envelope
(`manifests/envelopes/item1.analog.attest.json`) — plus PR #104's edits to
`layout/example_config.json` and the root `README.md` (`9a82f9b`, finalised
in `3df01b7`), turning item 1's and item 10's envelopes red on the post-merge
tree. Both were re-attested at `5e419cc` before the PR could land — item 1,
whose envelope reads `status: pass` with 10/10 checks, and item 10 a second
time (6/6, for the PR #104 `README.md` change) — so unlike the three skipped
steps above, nothing went missing here: the step and its record happened
together.
To close the class, `manifests/check_attestations.py` — new, stdlib Python
only — re-hashes every committed file named by every envelope under
`manifests/envelopes/` (both provenance shapes klt emits) and fails on any
disagreement; `./check-ci.sh attestations` runs it as a CI step, and
`manifests/tests/` pins it (the corrupted-hash negative control included). The
consequence to expect: once this gate is in CI, any edit to an attested file
(`README.md`, `LICENSE`, `.github/workflows/ci.yml`, the item 9 testbench
files, the item 1/2 sources and generated artifacts) turns CI red until the
owning envelope is re-attested — and re-attesting needs `klt`, which CI
deliberately does not have, so the fix is always a local
`klt signoff --attest <n> --inventory <inv> -o <envelope>`, never a change to
the gate. The envelope hash check is deliberately *not* delegated to
`klt signoff --attest --check` in CI: that would break CI's tool-free
constraint; the `klt` check stays the deeper local verification (it also
re-runs each inventory's commands).

`T1 #8 [analog] Characterization report` is **not** cited, and stays
`no_evidence` — deliberately, with the attestation committed as it graded. Its
inventory (`manifests/inventories/item8.analog.json`) is committed and names
the report `sim/characterize/records/20261115-171205-3462cc8.md` and, for spec
row 9, the Liberty view and its provenance sidecar; its freshness command
(`python3 -m sim.characterize.check_library`, new) re-derives what the sidecar
claims -- library name, cell set, declared corner, config hash and record, but
not the view's delay tables, which the sidecar does not hash. The staleness
that used to block citation is resolved: issue #73 had added two `layout.rules`
keys (`activ_space_nm`, `nwell_enc_nactiv_nm`) for the well and substrate taps
*after* the view was characterized, leaving the sidecar pinning
`layout/example_config.json` at `sha256:1a02f3cc…` — a hash the committed
config no longer had (nothing the characterization consumes changed, but the
sidecar pins the whole file). The view was regenerated against the committed
config, and the freshness command now **passes**: the sidecar pins the
committed config's current hash. What still keeps item 8 at `no_evidence` is
the envelope itself, which is unminted — minting needs a local
`klt signoff --attest` run, and CI deliberately has no klt. The check was
deliberately not weakened to pass: a freshness command that cannot fail is not
evidence. Tracked in issue #82.

The friction this surfaced is filed as 2AMLogic/klayout-tools#5688: `klt
signoff --attest 8` documents its `citations` as evidence-envelope paths but
checks only that each file exists, delegating all content verification to the
caller's `envelope_checks` command — which it accepts unconstrained, `true`
included. That is precisely why the command behind this repo's item 8 citation
was written to be falsifiable rather than merely present.
