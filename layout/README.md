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
share one gate contact. The NMOS and PMOS device on one gate net default to the
same drawn finger count, the larger of the two netlist counts; the other is folded
into that many fingers (same total width, which must divide evenly on
`process.grid_nm`, default 10). When the larger count would divide the narrower
device's width off the grid, that gate net falls back to **each device's own
netlist count** (issue #170): the gate net's columns become a block of
`max(n, p)` columns with the shorter device on the first `min(n, p)` of them.
Its remaining block columns carry no channel for it -- the diffusion node that
spans the block, introducing no source/drain transition -- and the poly stripe
there stops `poly_to_activ_nm` beyond the tallest diffusion run within that
horizontal clearance of the stripe, including a step on either side. A PMOS device
whose fingers include such NMOS-free columns cannot reach the bridge below the
NMOS diffusion with them, so its fingers are joined by a second poly bridge
*above* the PMOS strip (`poly_to_activ_nm` clear of it); that bridge is the only
shape that raises the well tap band, by `max(0, poly_to_activ_nm +
poly_width_nm - poly_endcap_nm)`. A width is never rounded to make a fold fit --
the netlist `ng` divides its own width by construction -- so the drawn total
width of every device equals its netlist width and LVS keeps matching. Cell
width is `(columns + 1) * gate_pitch_nm`, counting block columns. Each strip
must be a single chain of devices sharing source/drain nets, and both chains
must have the same gate-net sequence.

A gate whose net is also driven from diffusion (a multi-stage cell's internal
net, e.g. `buf`'s `Y_i`) is routed as a terminal of that net (issue #201):
the gate pad grows into a Metal1 riser running down to the net's channel
track, and the track grows out to meet it, so pad, track and the driving
diffusion stubs are one conductor rather than a labelled island the extractor
reads as a split net. Nets that need a riser take the topmost tracks, so a
riser crosses no other net's track; an ordinary input keeps the standalone
pad. The riser and the widened track are cleared against every other net's
Metal1 at `m1_space_nm` like any other piece of the route.

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
* a row/channel too short, or no Metal1-clean place for a gate contact -- or,
  for a gate its net drives from diffusion, no Metal1-clean riser from that
  net's track up to the pad (issue #201; the standalone labelled pad that
  would otherwise be drawn is exactly the split net the riser exists to
  avoid, so the refusal is the only other outcome).

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

#### The unequal-count fallback, measured (issue #170)

The fallback (above) exists for cells whose shorter device width does not
divide at the larger netlist count. Every cell that hit the old
`cannot be drawn as N fingers on the G nm grid` refusal was re-measured after
it, one one-cell config per cell: the demo catalog at this repo's `main` @
`39fa6d1` (with the `process` and `layout` blocks of
`layout/example_config.json`), the consumer catalog
`2AMLogic/sg13cmos5l-stdcells` @ `d91a3a3` (its `layout.rules` completed with
this repo's `psd_space_nm` 310 / `nwell_space_nm` 620, as in the issue). None
reports the grid diagnostic any more; each names the next physical limit:

| cell | fallback (drawn) | next limit |
|---|---|---|
| `demo_nor4_1` | NMOS 1 x 500 vs PMOS 4 x 800 | PMOS even-finger series stack needs a diffusion break |
| `s5l_nor3_1` | NMOS 1 x 740 vs PMOS 3 x 1120 | 3 channel tracks needed, 1 allowed |
| `s5l_or3_1` / `s5l_or3_2` | NMOS 1 x 740 vs PMOS 3 x 1120 | 4 channel tracks needed (`X`, `X_i`, `n1`, `n2`), 1 allowed |
| `s5l_nor3_2` | NMOS 2 x 740 vs PMOS 6 x 1120 | PMOS even-finger series stack needs a diffusion break |
| `s5l_nand3_1` | PMOS 1 x 1120 vs NMOS 3 x 740 | 3 channel tracks needed, 1 allowed |
| `s5l_and3_1` / `and3_2` / `nand3b_1` | PMOS 1 x 1120 vs NMOS 3 x 740 | 4 channel tracks needed, 1 allowed |
| `s5l_a221oi_1` | NMOS 2 x 740 vs PMOS 3 x 1120 | no shared gate-net sequence |

The track-count wall is not the only one behind those cells: raising the
synthetic `channel_tracks` to 3 moves `nor3_1`/`nand3_1` to *channel too short
for track 2* on the 3360 nm row (the margin budget the consumer's issue #24
tracks), and a 4200 nm row moves them to the routing model's
`Metal1 of Y overlaps n1` -- a folded series stack puts its end net's stubs
inside the span of the interior nets' horizontal track bars, which one Metal1
layer cannot separate. That limit is pre-existing (the equal fold has the same
interleaving) and is not lifted here.

No *committed* cell changes: the four `layout/gds/*.gds` stay byte-identical
under `--check` (the fallback only fires where the old code exited `3`), which
`test_gen_layouts.py::Determinism::test_committed_gds_fresh` asserts.

**The new geometry itself is exercised and verified on two placeable
fixtures** (`test_gen_layouts.py::UnequalFingerCounts`): inverters sized
740/2430 nm (PMOS 3 x 810 vs NMOS 1 x 740 -- top bridge, NMOS tail columns,
stripes stopping above the NMOS diffusion) and 2100/1120 nm (NMOS 3 x 700 vs
PMOS 1 x 1120 -- low bridge, PMOS tail columns, stripes stopping below the
PMOS diffusion), on the 3360 nm row with the margins 350/330. Both, generated
with this repo's `layout/example_config.json` rules on the 5 nm grid:

* `klt drc --deck sg13g2`: `clean` on both -- run twice, once on the pinned
  klt `0.6.0+g068b0c1da0e8` (`layout/toolchain.json`'s `klt_install`) and once
  on this host's `0.9.3.dev2575+g6bd18bbc8637` / klayout `0.30.12`;
* `python3 layout/run_lvs.py`: `match` on both -- the tail columns extract as
  no transistor, so the drawn device set equals the netlist's (klt
  `0.9.3.dev2575`, klayout `0.30.12`; the pinned 0.6.0 `lvs` predates that
  runner's `-o` contract -- the committed `layout/lvs/` reports likewise
  record a newer-than-pin klt in their provenance).

In a fallback, the generator fits each diffusion contact stack between its
enclosures in whole grid steps. When the ideal centre lies halfway between
steps, the lower position wins. Two-finger inverter fixtures at 745/1760 nm
and 1700/1125 nm place on the 5 nm grid. Both match their netlists in LVS
and pass SG13G2 DRC (klt source `068b0c1da0e8`, KLayout 0.30.13). The deck
at `6bd18bbc8637`, which checks `cont.ongrid.1`, also reports zero violations.

The drive-2 buffer clearance regression (500/2430 nm, 550 nm pitch, 4200 nm
row, two tracks) passes both DRC decks. Its internal gate still fails LVS with
a split net, also reproduced on a common-fold buffer on `main`. [Issue #201](https://github.com/2AMLogic/sg13g2-stdcells/issues/201)

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

**The two 840-pitch `and2` controls were re-recorded on 2026-11-22** (issue
#201): the driven-gate routing fix above changed their streams -- `and2`'s
internal `X_i` gate now lands on its net's route, which adds one Metal1 box
per stream (the track extension; the pad itself becomes the riser's top) --
so the committed GDS and the two reports next to them were regenerated
together. The verdicts are unchanged: `notch-nmos-p840-admitted` is still
`clean` with 0 violations (`metal1.space.1` and `metal1.width.1` in
`rules_checked`), and `notch-pmos-p840-refused` still flags exactly one
`psd.space.1` at the same bbox (the notch sits in the PMOS strip and is
untouched by Metal1), negative control passing. Both were re-recorded on the
same klt `0.9.2.dev1029+g76f47afa48f1` / klayout `0.30.13` and the same
released deck (`sha256:cf6d...`) as the original set, so all four reports
still carry one deck hash. The two `inv_4`-based controls (420/600) are
byte-unchanged -- an inverter has no driven gate.

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

#### Re-verifying the committed reports (issue #198)

`--check` re-hashes, through whatever `klt` is first on `PATH`, the layout,
the reference netlist and the bundled `sg13g2` deck each report pins -- so
whether the committed evidence re-verifies is a property of the install, not
only of the tree: a klt build bundling a different deck than the recorded
`provenance.deck.content_hash` drifts on all four reports on a clean tree.
Each report names the toolchain it was minted with --
`provenance.klt_reinstall_spec` (a PEP 508 install requirement for klt) and
`provenance.klayout_version` (the engine wheel). Read them out of any report
(all four carry the same pair), install that exact toolchain into a
throwaway venv -- never into a host-wide install -- and put its `bin` first
on `PATH`, since the runner and `layout/toolchain_pin.py` both shell out to
`klt` by name:

```
python3 -c "import json; p = json.load(open('layout/lvs/sg13g2_inv_1.json'))['provenance']; print(p['klt_reinstall_spec'], p['klayout_version'])"

uv venv /tmp/lvs-verify
uv pip install --python /tmp/lvs-verify/bin/python \
  'klayout-tools @ git+https://github.com/2AMLogic/klayout-tools@2a9c52b27ce7986b4372ae5d73129dac4773e02c' \
  'klayout==0.30.13'
/tmp/lvs-verify/bin/klt --version    # the recorded klt: 0.9.2.dev1022+g2a9c52b27ce7

PATH=/tmp/lvs-verify/bin:$PATH \
  python3 layout/run_lvs.py --config layout/example_config.json --check    # exit 0
git diff --exit-code -- layout/gds layout/lvs    # the check wrote nothing
```

Installing `klayout==<provenance.klayout_version>` alongside the spec pins
the engine wheel too. A newer klt is not disqualified: on
`0.9.3.dev3+gd5d57daf9a14` (klayout `0.30.13`) the same runner check also
exits 0 with every hash `[OK]`, plus one informational
`[DRIFT] provenance.klt_version` line per report, and
`layout/toolchain_pin.py` checks subcommands rather than versions, so the
capability pin does not force the recorded build. Both installs verified at
`aeb7c25`.

**Reading a failure.** The runner's per-cell lines truncate `klt`'s stdout to
200 characters (`do_check` in `layout/run_lvs.py`; the absolute report path
eats about half the budget on its own), which on a drifting install cuts the
output mid-field and hides *which* field drifted. Run the check on one report
directly for the full diagnostic:

```
klt lvs --check layout/lvs/sg13g2_inv_1.json
```

On a host-wide install (`klt 0.9.3.dev2586+g9bac82596e2f`, klayout
`0.30.12`, clean tree at `aeb7c25`) that prints:

```
status: drifted
  [OK] environment.layout_sha256
  [OK] environment.reference_sha256
  [DRIFTED] provenance.deck.content_hash
      expected: sha256:cf6dfead…
      actual:   sha256:eaaf2989…
  [DRIFT] provenance.klt_version: 0.9.2.dev1022+g2a9c52b27ce7 (report) vs 0.9.3.dev2586+g9bac82596e2f (current)
  [DRIFT] provenance.klayout_version: 0.30.13 (report) vs 0.30.12 (current)
```

and exits `3` (the runner folds that into its exit `1`). The prefix is the
signal:

* `[DRIFT]` (singular) is an informational **tool-version** difference
  (`provenance.klt_version`, `provenance.klayout_version`): the checking
  install is not the minting one. It appears in passing runs too -- the
  `0.9.3.dev3` build above graded `status: match`, exit `0` -- so it never
  fails a check on its own.
* `[DRIFTED]` is a failing field, with expected vs actual on the two lines
  under it. In the example the failing field is
  `provenance.deck.content_hash`: that install bundles a different `sg13g2`
  deck than the report recorded, while both input hashes are still `[OK]`,
  so the committed GDS and reference netlist are intact and the *deck* is
  what moved -- re-verify under the recorded build (the recipe above)
  before suspecting the evidence. A `[DRIFTED]` on
  `environment.layout_sha256` or `environment.reference_sha256` instead is a
  real input drift: the committed bytes are not what the report graded, and
  the answer is a re-mint -- a new record, never an edit, the same
  append-only discipline as the supersession chains below.

#### The recorded result (issues #42, #73)

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

### Signoff manifest and attestation envelopes (issues #75, #103)

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

### Characterization records and their supersession chain (issues #82, #134)

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

**Resolution (2026-11-14, issue #82): the view was regenerated.** Of the two
ways out recorded above, regenerating was taken and narrowing the pin was
rejected — narrowing makes a claim about what provenance must cover (that a
digest over `process` + `cells` is adequate), which belongs in a `spec/`
decision record of its own, deferred until the coarse pin goes stale again;
this regeneration is the first data point on what that recurrence costs. The
regeneration (`python3 -m sim.characterize --library --pdk-dir
/home/ubuntu/share/pdk/ihp-sg13g2`) ran on a clean worktree and appended
record `sim/characterize/records/20261114-222806-f1cf294.md`; the superseded
record `20261107-222836-6ee1577.md` is kept, append-only. It re-measured under
a newer toolchain — klt 0.9.2.dev247 → 0.9.2.dev1029, ngspice-46 → ngspice-47 —
so any numeric difference between the two records is attributable to that; in
the event the committed `.lib` is byte-identical. Two side findings are
recorded with it: the first regeneration attempt surfaced that the runner
stamped the sidecar's `repo_commit` `(dirty)` from its own outputs (the
`.lib` and record are written before the sidecar is stamped), fixed by
snapshotting git provenance once before the run so the record and its sidecar
always name the same tree state; and regenerating the signoff report exposed a
pre-existing item-10 staleness on `main` — `README.md` was edited (commit
`df690f0`, the Status-block correction) after that envelope was minted —
re-attested here, unchanged checks, so the report reads T1 12/22 with item 8
[analog] `[MET]`. The envelope was re-minted a second time before merge: the update from `main`
moved both pinned files again (`README.md` and `.github/workflows/ci.yml`), so
the committed envelope pins those files' post-merge bytes; the six checks pass
unchanged and the report is byte-identical, still reading T1 12/22. The same
merge also moved `verification/Makefile` (PR #108), which item 9 [digital]'s
envelope pins — main had moved that file without re-minting there, a
staleness this branch inherited — so that envelope was re-minted identically
(cold start re-run, 6/6 checks unchanged); the report stays byte-identical.

**Resolution recurrence (2026-11-15, the data point that paragraph predicted):**
main's PR #104 added three more `layout.rules` keys (`psd_space_nm`,
`nwell_space_nm`, `sd_enc_activ_nm`), staleing the whole-file config pin again
on any merge of this branch — the second recurrence lap in eight days, and the
reason the narrowing option (a `spec/` decision record) is deferred no longer
lightly: it is filed structurally as #110/#116. Regenerated again exactly as
above — `python3 -m sim.characterize --library --pdk-dir
/home/ubuntu/share/pdk/ihp-sg13g2` on the clean merged tree (`921b1a8`) before
any bookkeeping edit, single corner TT/1.20 V/25 C, local backend — appending
record `sim/characterize/records/20261115-105337-921b1a8.md`, keeping both
superseded records, `.lib` byte-identical yet again. Toolchain moved again
(klt 0.9.2.dev1029 → 0.9.3.dev3+gd5d57daf9a14; ngspice unchanged at 47) and is
named in the record so any numeric difference stays attributable. Items 8 and
10 were re-minted against the merged bytes (item 8's inventory report field
names the new record, so its input digest moved to `6876f546…`, manifest
updated). The report is regenerated with the honest grade, **T1 11/22**, one
below the previous claim: `1.analog` grades `stale_evidence` because main's
#112 re-minted that envelope but left the manifest's `content_hash` entry at
the pre-#112 input digest (`e1e8354a…` vs the envelope's own `d5a5ee9c…`) — a
main-side omission tracked in #116, deliberately not repaired inside this PR
(design sources are not #82's scope); `--manifest --check` reads
`status: match` because the committed report **is** the fresh grade, which is
the criterion issue #82 actually sets.

**Resolution recurrence, third lap (2026-11-15, this branch's `main` update
`577d620`):** the merge brought #128's `1.analog` manifest-pin fix, so that
item is `[MET]` again and the regenerated report reads **T1 12/22** with
`T1 #8 [analog]` `[MET]` — the committed `manifests/signoff-report.json` is
the authority for the count. Item 8's input digest is `53f4ba2c…` after the
inventory `description` took main's narrowed #122 wording; items 8 and 10 were
re-minted against the merged bytes. The 11/22 sentence above is left as
written — it was true of `206dac1` — exactly as the earlier laps were left in
place.

**Resolution recurrence, fourth lap (2026-11-15, this branch's `main` update
`a100765`):** the merge brought #125's simulator-version recording (`af3b7b3`:
a `simulator` field in the sidecar, `simulator ngspice-47` in the record's
Notes line) and main's own refresh of the view, run on a dirty tree there —
its record stamps `3462cc84… (dirty)`, the exact defect class this branch's
pre-capture fix exists to close. Seven files conflicted; the only code hunk
was `runner.py`'s `render()` Notes line, where both halves are load-bearing and
both are kept: main's simulator key and this branch's doubled-`klt `-prefix
strip. Regenerated exactly as every lap above — `python3 -m sim.characterize
--library --pdk-dir /home/ubuntu/share/pdk/ihp-sg13g2` on the clean merged
tree (`13dc481`) before any bookkeeping edit, single corner TT/1.20 V/25 C,
local backend — appending record
`sim/characterize/records/20261115-220740-13dc481.md`, keeping all four
superseded records (`6ee1577`, `f1cf294`, `921b1a8`, `3462cc8`). This lap the
`.lib` is **not** byte-identical: exactly one `leakage_power` value moved a
last digit (`78.4631` → `78.4632`; main's run
was on klt 0.9.3.dev3, this run on 0.9.3.dev16+gdcf18e2e0c03, ngspice
unchanged at 47) — the toolchain is named in the record so the difference
stays attributable. Items 8 and 10 were re-minted against the merged bytes
(item 8's inventory `report` field names the new record, so its input digest
moved to `1910e308…`, manifest updated; item 10's README pin refreshed). The
report is regenerated and reads **T1 12/22** with `T1 #8 [analog]` `[MET]` —
the committed `manifests/signoff-report.json` is the authority for the count;
`klt signoff --manifest manifests/sg13g2-stdcells.json --check
manifests/signoff-report.json` reads `status: match`. The 11/22 sentence above
is left as written, exactly as the earlier laps were left in place.

The friction this surfaced is filed as 2AMLogic/klayout-tools#5688: `klt
signoff --attest 8` documents its `citations` as evidence-envelope paths but
checks only that each file exists, delegating all content verification to the
caller's `envelope_checks` command — which it accepts unconstrained, `true`
included. That is precisely why the command behind this repo's item 8 citation
was written to be falsifiable rather than merely present.

Resolution lap (prose corrections per review): the merge prose had dropped one
record from each README's chain — `921b1a8` from `sim/README.md`'s list,
`3462cc8` from `README.md`'s supersession chain — and `sim/README.md`'s Status
line still counted the pre-recurrence tree. Both records are restored,
`sim/README.md`'s Status now counts the committed tree (six records; the
library view characterized five times — four refreshes), and `README.md`
defers the full chain to `sim/characterize/records/` instead of restating it.
Editing `README.md` moved its byte pin in item 10's hygiene envelope, so that
envelope was re-minted (its three audit commands re-run, 6/6; the inventory
digest is unchanged at `50d2ba3a…`, so the manifest is untouched) and
`manifests/signoff-report.*` regenerated byte-identical: still **T1 12/22**,
`--check` reads `status: match`, no `stale_evidence` anywhere. No
characterization was re-run and no record was added — the record chain of the
fourth lap above is unchanged, and the count sentences earlier laps left are
left as written.

**Gate hardening (2026-11-16, issue #134): the freshness command now fails on
a dirty provenance stamp.** The command re-derived library name, cell set,
corner, config hash and record, but never read the `repo_commit` the sidecar
and its record carry — so the two committed records stamped `(dirty)`
(`20261107-222836-6ee1577`, `20261115-171205-3462cc8`) passed every gate in
the repo while citing measurements reproducible from no commit.
`check_library.check()` now reports a finding when the sidecar's
`repo_commit` or the cited record's `**Repo commit**` line carries the dirty
suffix, and the stamp format is one shared definition
(`sim/harness/report.py`'s `commit_stamp`/`is_dirty_stamp`) that the writer
(`runner.py`), the checker and their tests all read, so the suffix cannot
drift apart. The two historical dirty records are kept, append-only — the
check gates what the sidecar cites, not the archive — and the committed
sidecar and its record stamp clean (`13dc481`), so the command still passes
on main's bytes unchanged. The command's own claim (module docstring,
`--help` description, success line) names the stamp check now, per the #122
narrowing discipline. No characterization was re-run and no envelope was
re-minted: none of the edited files is envelope-pinned.
