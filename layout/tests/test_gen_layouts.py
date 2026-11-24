"""Tests for layout/gen_layouts.py: config validation, determinism, --check
exit codes, named placement failures, and a second (fake) process config."""
import copy
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from unittest.mock import patch

LAYOUT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAYOUT))
import gen_controls as gc  # noqa: E402
import gen_layouts as gl  # noqa: E402

CONFIG = LAYOUT / "example_config.json"
CFG = json.loads(CONFIG.read_text())
SCRIPT = LAYOUT / "gen_layouts.py"


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def read_gds_boxes(data):
    """Independent minimal GDS reader: [(layer, datatype, xs, ys)] for BOUNDARYs."""
    import struct
    i, out, cur = 0, [], {}
    while i < len(data):
        n, rt, _dt = struct.unpack(">HBB", data[i:i + 4])
        body = data[i + 4:i + n]
        if rt == 0x0D:
            cur["l"] = struct.unpack(">h", body)[0]
        elif rt == 0x0E:
            cur["d"] = struct.unpack(">h", body)[0]
        elif rt == 0x10 and "d" in cur:
            v = struct.unpack(f">{len(body) // 4}i", body)
            out.append((cur["l"], cur["d"], v[0::2], v[1::2]))
            cur = {}
        elif rt == 0x11:
            cur = {}
        i += n
    return out


class Validation(unittest.TestCase):
    def bad(self, mutate):
        cfg = copy.deepcopy(CFG)
        mutate(cfg)
        with self.assertRaises(ValueError):
            gl.generate(cfg)

    def test_missing_layout_block(self):
        self.bad(lambda c: c.pop("layout"))

    def test_missing_rule(self):
        self.bad(lambda c: c["layout"]["rules"].pop("m1_width_nm"))

    def test_missing_notch_space_rule(self):
        """The notch predicate reads psd_space_nm / nwell_space_nm; a config
        without one must exit 2 naming the key, not silently skip a check."""
        self.bad(lambda c: c["layout"]["rules"].pop("psd_space_nm"))
        self.bad(lambda c: c["layout"]["rules"].pop("nwell_space_nm"))

    def test_bad_layer(self):
        self.bad(lambda c: c["layout"]["layers"].update(metal1=[8]))

    def test_odd_pitch(self):
        self.bad(lambda c: c["layout"].update(gate_pitch_nm=421))

    def test_netlist_side_validation_still_applies(self):
        self.bad(lambda c: c["process"].pop("l_nm"))

    def test_schema_version_must_be_1(self):
        self.bad(lambda c: c.update(schema_version=99))
        self.bad(lambda c: c.pop("schema_version"))
        self.bad(lambda c: c.update(schema_version=True))

    def test_cli_exit_2(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "c.json"
            p.write_text("{}")
            self.assertEqual(run("--config", str(p)).returncode, 2)


class Determinism(unittest.TestCase):
    def test_two_runs_identical(self):
        self.assertEqual(gl.generate(CFG), gl.generate(copy.deepcopy(CFG)))

    def test_committed_gds_fresh(self):
        r = run("--config", str(CONFIG), "--check")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_check_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d)
            cfg = d / "c.json"
            cfg.write_text(json.dumps(CFG))
            self.assertEqual(run("--config", str(cfg), "--check").returncode, 1)  # missing
            self.assertEqual(run("--config", str(cfg)).returncode, 0)
            self.assertEqual(run("--config", str(cfg), "--check").returncode, 0)
            edited = copy.deepcopy(CFG)
            edited["layout"]["rules"]["rail_width_nm"] += 10
            cfg.write_text(json.dumps(edited))
            self.assertEqual(run("--config", str(cfg), "--check").returncode, 1)  # changed
            (d / "gds" / "stray.gds").write_bytes(b"")
            cfg.write_text(json.dumps(CFG))
            self.assertEqual(run("--config", str(cfg), "--check").returncode, 1)  # stray


class Geometry(unittest.TestCase):
    def test_gds_is_parseable_and_on_layout_grid(self):
        files = gl.generate(CFG)
        L = {tuple(v): k for k, v in CFG["layout"]["layers"].items()}
        for name, data in files.items():
            boxes = read_gds_boxes(data)
            seen = {L[(l, d)] for l, d, _, _ in boxes}
            self.assertTrue({"activ", "gatpoly", "cont", "metal1", "nwell", "psd"} <= seen, name)
            for _, _, xs, ys in boxes:
                self.assertTrue(all(x >= -1000 for x in xs + ys))

    def test_cell_width_follows_pitch(self):
        cell = next(c for c in CFG["cells"] if c["name"] == "sg13g2_nand2_1")
        S, W, H = gl.layout_cell(cell, CFG["process"], CFG["layout"])
        self.assertEqual((W, H), (4 * 420, 3360))


def cell_named(name):
    return next(c for c in CFG["cells"] if c["name"] == name)


def layout_of(cell, cfg=CFG):
    return gl.layout_cell(cell, cfg["process"], cfg["layout"])


def off_grid_labels(S, pitch):
    """Spec row 4's check over one cell's shapes, against row 2's routing grid.

    The grid is `pitch` on both axes with its origin at the cell origin: the
    rails are centred on y=0 and y=row_height_nm (= 8 * pitch), so the grid's
    (0, 0) is the cell's. Every `metal1_label` -- the gate pads, the outputs
    and the VSS/VDD rail labels -- must lie at a multiple of `pitch` on both
    axes and on a Metal1 shape. Returns [(text, x, y, why)] for the labels
    that fail, in drawing order."""
    metal = [b[1:] for b in S.boxes if b[0] == "metal1"]
    out = []
    for layer, x, y, text in S.labels:
        if layer != "metal1_label":
            continue
        axes = [a for a, v in (("x", x), ("y", y)) if v % pitch]
        why = ["off grid on " + " and ".join(axes)] if axes else []
        if not any(b[0] <= x <= b[2] and b[1] <= y <= b[3] for b in metal):
            why.append("not on Metal1")
        if why:
            out.append((text, x, y, " and ".join(why)))
    return out


class PinOnGrid(unittest.TestCase):
    """Spec row 4, pin access: every pin on a grid point (issue #221).

    Row 2's routing grid is `gate_pitch_nm` -- the config carries no separate
    routing-grid key, and row 2's own check reads the widths off the same
    value -- with its origin at the cell origin: the rails are centred on
    y=0 and y=row_height_nm = 8 * pitch, so both are grid lines and the cell's
    (0, 0) is a grid point. The row is **met** (issue #225): the generator
    puts the diffusion nodes on the grid columns (x = (j + 1) * pitch) and the
    gates a half pitch between them, so a cell is (columns + 2) pitches wide;

      * a rail label sits on the first node column, on its rail;
      * an output label is a grid point of the net's final Metal1, on its
        node column;
      * an input gate's pad reaches the node column beside it by a vertical
        Metal1 bar up to a grid y in the channel.

    The label of an *internal* net's gate pad (a multi-stage cell's `X_i`)
    stays on the pad centre. It is still checked: `off_grid_labels()` tests
    every `metal1_label` with no exemption, so a shipped multi-stage cell would
    fail this row for that label."""

    P = CFG["layout"]["gate_pitch_nm"]
    maxDiff = None
    OFF_GRID_RECORD = {}  # cell name -> [(label, x, y)] of its off-grid labels: none (#225)

    def offenders(self, cells):
        """One line per failing label of {cell name: shapes}."""
        return [f"{name}: {text} at ({x}, {y}) -- {why}"
                for name, S in cells.items() for text, x, y, why in off_grid_labels(S, self.P)]

    def assert_on_grid(self, cells):
        self.assertEqual(self.offenders(cells), [],
                         f"every pin label at a multiple of {self.P} nm from the cell origin, and on Metal1")

    def test_grid_origin_is_the_cell_origin(self):
        """The rails are centred on y=0 and y=row_height_nm = 8 * pitch: both
        are grid lines, so the cell origin is a grid point and the top rail
        lies on the grid."""
        self.assertEqual(CFG["layout"]["row_height_nm"], 8 * self.P)
        for cell in CFG["cells"]:
            S, W, H = layout_of(cell)
            rails = sorted((b[2] + b[4]) // 2 for b in S.boxes if b[0] == "metal1" and b[1] == 0 and b[3] == W)
            self.assertEqual(rails, [0, H], cell["name"])

    def test_every_pin_label_is_on_the_routing_grid(self):
        """Row 4's assertion over every config cell (ROADMAP's row-4 sentence
        cites this test)."""
        self.assert_on_grid({c["name"]: layout_of(c)[0] for c in CFG["cells"]})

    def test_row4_off_grid_record(self):
        """The measurement ROADMAP quotes, pinned so it is CI-checked: no
        shipped cell has an off-grid label. A failure here means the
        generator's pin placement moved: re-measure, then update the record
        and ROADMAP's row-4 sentence together."""
        found = {c["name"]: off_grid_labels(layout_of(c)[0], self.P) for c in CFG["cells"]}
        self.assertEqual({n: [o[:3] for o in off] for n, off in found.items() if off}, self.OFF_GRID_RECORD)
        self.assertTrue(all(o[3].startswith("off grid") for off in found.values() for o in off),
                        "a label is not on Metal1")

    def rail_only(self):
        """inv_1 with only its two rail labels, the committed cells' only
        on-grid ones: a control's clean baseline (the boxes are shared read-only)."""
        S = copy.copy(layout_of(cell_named("sg13g2_inv_1"))[0])
        S.labels = [l for l in S.labels if l[3] in (CFG["process"]["vss_net"], CFG["process"]["vdd_net"])]
        return S

    def test_control_baseline_passes(self):
        self.assert_on_grid({"sg13g2_inv_1": self.rail_only()})

    def test_control_one_label_moved_off_the_grid_fails_naming_it(self):
        """One DBU (the GDS unit, 1 nm) on either axis, or the half pitch the
        generator's own labels carry: the check fails on exactly that label."""
        for dx, dy, axes in ((1, 0, "x"), (0, 1, "y"), (self.P // 2, 0, "x")):
            S = self.rail_only()
            layer, x, y, text = S.labels[-1]
            S.labels[-1] = (layer, x + dx, y + dy, text)
            cells = {"sg13g2_inv_1": S}
            self.assertEqual(self.offenders(cells),
                             [f"sg13g2_inv_1: {text} at ({x + dx}, {y + dy}) -- off grid on {axes}"])
            with self.assertRaises(AssertionError):
                self.assert_on_grid(cells)

    def test_control_label_on_the_grid_but_off_metal_fails_naming_it(self):
        S = self.rail_only()
        layer, x, y, text = S.labels[-1]
        S.labels[-1] = (layer, x, y + self.P, text)
        cells = {"sg13g2_inv_1": S}
        self.assertEqual(self.offenders(cells), [f"sg13g2_inv_1: {text} at ({x}, {y + self.P}) -- not on Metal1"])
        with self.assertRaises(AssertionError):
            self.assert_on_grid(cells)


class MultiFinger(unittest.TestCase):
    def test_two_finger_inverter_places(self):
        S, W, H = layout_of(cell_named("sg13g2_inv_2"))
        self.assertEqual((W, H), (4 * 420, 3360))
        cols = [b for b in S.boxes if b[0] == "gatpoly" and b[4] - b[2] > 1000]  # full-height stripes
        self.assertEqual(sorted((b[1] + b[3]) // 2 for b in cols), [630, 1050])

    def test_width_grows_with_finger_count(self):
        w = {n: layout_of(cell_named(n))[1] for n in ("sg13g2_inv_1", "sg13g2_inv_2", "sg13g2_inv_4")}
        self.assertEqual(w, {"sg13g2_inv_1": 3 * 420, "sg13g2_inv_2": 4 * 420, "sg13g2_inv_4": 6 * 420})

    def test_fingers_share_a_gate_bridge_and_one_pad(self):
        S, _, _ = layout_of(cell_named("sg13g2_inv_4"))
        pw = CFG["layout"]["rules"]["poly_width_nm"]
        bridges = [b for b in S.boxes if b[0] == "gatpoly" and b[4] - b[2] == pw and b[3] - b[1] > pw]
        self.assertEqual(len(bridges), 1)
        self.assertEqual(sum(1 for lbl in S.labels if lbl[3] == "A"), 1)

    def test_single_finger_cell_has_no_bridge(self):
        S, _, _ = layout_of(cell_named("sg13g2_inv_1"))
        pw = CFG["layout"]["rules"]["poly_width_nm"]
        self.assertEqual(sum(1 for b in S.boxes if b[0] == "gatpoly" and b[4] - b[2] == pw and b[3] - b[1] > pw), 0)

    def test_multi_finger_output_deterministic(self):
        a = gl.generate(CFG)["sg13g2_inv_4.gds"]
        self.assertEqual(a, gl.generate(copy.deepcopy(CFG))["sg13g2_inv_4.gds"])

    def test_series_stack_of_fingers_still_exits_3_with_reason(self):
        cfg = copy.deepcopy(CFG)
        cfg["cells"].append({"name": "x_nand2_2", "family": "nand2", "drive": 2, "inputs": ["A", "B"], "outputs": {"Y": "!(A*B)"}})
        with self.assertRaises(gl.PlaceError) as cm:
            gl.generate(cfg)
        self.assertIn("x_nand2_2", str(cm.exception))
        self.assertIn("channel tracks", str(cm.exception))
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "c.json"
            p.write_text(json.dumps(cfg))
            r = run("--config", str(p))
            self.assertEqual(r.returncode, 3)
            self.assertIn("x_nand2_2", r.stderr)

    def test_even_finger_series_stack_needs_two_tracks(self):
        """The break model places nand4's even-finger series stack as two
        chains, but the stack's middle net is split across them, so with one
        track the refusal is the channel-track one, naming the split net."""
        cfg = copy.deepcopy(CFG)
        cfg["cells"] = [{"name": "x_nand4_1", "family": "nand4", "drive": 1, "inputs": ["A", "B", "C", "D"], "outputs": {"Y": "!(A*B*C*D)"}}]
        with self.assertRaises(gl.PlaceError) as cm:
            gl.generate(cfg)
        self.assertIn("x_nand4_1", str(cm.exception))
        self.assertIn("channel tracks", str(cm.exception))
        self.assertIn("'n2'", str(cm.exception))
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "c.json"
            p.write_text(json.dumps(cfg))
            r = run("--config", str(p))
            self.assertEqual(r.returncode, 3)
            self.assertIn("x_nand4_1", r.stderr)

    def test_no_rule_value_loosened(self):
        self.assertEqual(CFG["layout"]["rules"], {
            "poly_width_nm": 130, "poly_space_nm": 180, "poly_endcap_nm": 180, "poly_to_activ_nm": 70, "cont_nm": 160,
            "cont_space_nm": 180, "activ_enc_cont_nm": 70, "poly_enc_cont_nm": 70, "m1_width_nm": 160, "m1_space_nm": 180,
            "rail_width_nm": 160, "nwell_enc_pactiv_nm": 310, "nwell_enc_nactiv_nm": 240, "activ_space_nm": 210,
            "sd_enc_activ_nm": 180, "psd_space_nm": 310, "nwell_space_nm": 620})
        self.assertEqual(CFG["layout"]["channel_tracks"], 1)


def tap_bands(S, H):
    """The two tap `activ` rectangles: the only ones outside the row's strips."""
    return sorted((b for b in S.boxes if b[0] == "activ" and (b[2] < 0 or b[4] > H)), key=lambda b: b[2])


class Taps(unittest.TestCase):
    """Well/substrate taps (issue #73): without them extraction puts the device
    bodies on a synthesized substrate net and an anonymous well net."""

    def bands(self, name, cfg=CFG):
        S, W, H = layout_of(cell_named(name), cfg)
        bands = tap_bands(S, H)
        self.assertEqual(len(bands), 2, f"{name}: expected one tap band per rail")
        return S, W, H, bands[0], bands[1]

    def test_every_cell_gets_both_taps(self):
        for cell in CFG["cells"]:
            S, W, H, sub, well = self.bands(cell["name"])
            R = CFG["layout"]["rules"]
            tap_h = R["cont_nm"] + 2 * R["activ_enc_cont_nm"]
            self.assertEqual(sub[4] - sub[2], tap_h, cell["name"])   # derived, not a config key
            self.assertEqual(well[4] - well[2], tap_h, cell["name"])
            self.assertLess(sub[2], 0, cell["name"])                 # the VSS band straddles y=0
            self.assertGreater(well[4], H, cell["name"])             # the VDD band straddles y=H

    def test_tap_implants_are_the_tie_type_and_do_not_overlap(self):
        for cell in CFG["cells"]:
            S, W, H, sub, well = self.bands(cell["name"])
            # well tie is activ & nsd, substrate tie is activ & psd (sg13g2 deck)
            for band, layer in ((sub, "psd"), (well, "nsd")):
                cover = [b for b in S.boxes if b[0] == layer
                         and b[1] <= band[1] and b[2] <= band[2] and b[3] >= band[3] and b[4] >= band[4]]
                self.assertTrue(cover, f"{cell['name']}: {layer} does not cover its tie band")
            psd = [b for b in S.boxes if b[0] == "psd"]
            nsd = [b for b in S.boxes if b[0] == "nsd"]
            for a in psd:  # opposite implants over one area is not a real mask
                for b in nsd:
                    self.assertFalse(a[1] < b[3] and b[1] < a[3] and a[2] < b[4] and b[2] < a[4],
                                     f"{cell['name']}: psd {a[1:]} overlaps nsd {b[1:]}")

    def test_tap_has_one_contact_per_node_column_on_its_rail(self):
        R = CFG["layout"]["rules"]
        rail = R["rail_width_nm"]
        for cell in CFG["cells"]:
            S, W, H, sub, well = self.bands(cell["name"])
            for band, ry in ((sub, 0), (well, H)):
                conts = [b for b in S.boxes if b[0] == "cont" and band[2] <= b[2] and b[4] <= band[4]]
                self.assertEqual(len(conts), W // CFG["layout"]["gate_pitch_nm"] - 1, cell["name"])  # one per node column
                for c in conts:  # enclosed by the band diffusion
                    self.assertGreaterEqual(c[2] - band[2], R["activ_enc_cont_nm"], cell["name"])
                    self.assertGreaterEqual(band[4] - c[4], R["activ_enc_cont_nm"], cell["name"])
                # a Metal1 shape merged with the rail covers the contacts
                patch = [b for b in S.boxes if b[0] == "metal1" and b[1] <= conts[0][1] and b[3] >= conts[-1][3]
                         and b[2] <= min(c[2] for c in conts) and b[4] >= max(c[4] for c in conts)]
                self.assertTrue(patch, f"{cell['name']}: tap contacts at y={ry} are not covered by Metal1")
                self.assertTrue(any(b[2] <= ry - rail // 2 and b[4] >= ry + rail // 2 for b in patch),
                                f"{cell['name']}: tap Metal1 at y={ry} is not merged with its rail")

    def test_vss_band_is_poly_bound_not_diffusion_bound(self):
        """The poly caps the VSS band on every cell -- its endcap below the NMOS
        strip on a single-finger cell, and the lower finger bridge on a folded
        one. Reading the NMOS diffusion alone would place the band too high."""
        R, lay = CFG["layout"]["rules"], CFG["layout"]
        diffusion_bound = lay["n_diff_y0_nm"] - R["activ_space_nm"]
        for name in ("sg13g2_inv_1", "sg13g2_inv_2", "sg13g2_inv_4", "sg13g2_nand2_1"):
            S, _, _, sub, _ = self.bands(name)
            poly_y0 = min(b[2] for b in S.boxes if b[0] == "gatpoly")
            self.assertEqual(sub[4], poly_y0 - R["poly_to_activ_nm"], name)
            self.assertLess(sub[4], diffusion_bound, name)
        # and the folded cells sit lower still, because the bridge is below the endcap
        single = self.bands("sg13g2_inv_1")[3][4]
        for name in ("sg13g2_inv_2", "sg13g2_inv_4"):
            self.assertLess(self.bands(name)[3][4], single, name)

    def test_nwell_extends_to_enclose_the_well_tie(self):
        R = CFG["layout"]["rules"]
        for cell in CFG["cells"]:
            S, W, H, sub, well = self.bands(cell["name"])
            nwell = [b for b in S.boxes if b[0] == "nwell"]
            self.assertEqual(len(nwell), 1, cell["name"])
            nw = nwell[0]
            self.assertEqual(nw[4], well[4] + R["nwell_enc_nactiv_nm"], cell["name"])
            self.assertGreater(nw[4], H + R["rail_width_nm"] // 2, cell["name"])  # above the row, as the rule needs
            for lo, hi in ((nw[1], well[1]), (well[3], nw[3])):  # and on both sides
                self.assertGreaterEqual(abs(hi - lo), R["nwell_enc_nactiv_nm"], cell["name"])

    def test_missing_nsd_layer_names_nsd(self):
        # nsd is a required layer (issue #80): a config without it is an
        # exit-2 config error from validate(), not a per-cell placement
        # failure -- the message names the key and no cell.
        cfg = copy.deepcopy(CFG)
        cfg["layout"]["layers"].pop("nsd")
        with self.assertRaises(ValueError) as cm:
            gl.generate(cfg)
        self.assertIn("layout.layers.nsd", str(cm.exception))
        self.assertNotIn("sg13g2_inv_1", str(cm.exception))

    def test_malformed_nsd_layer_is_a_config_error(self):
        cfg = copy.deepcopy(CFG)
        cfg["layout"]["layers"]["nsd"] = [7]  # not [layer, datatype]
        with self.assertRaises(ValueError) as cm:
            gl.generate(cfg)
        self.assertIn("layout.layers.nsd must be [layer, datatype]", str(cm.exception))
        self.assertNotIn("sg13g2_inv_1", str(cm.exception))

    def test_implant_reaching_past_the_band_is_a_named_failure(self):
        cfg = copy.deepcopy(CFG)
        cfg["layout"]["rules"]["sd_enc_activ_nm"] = 260  # > activ_space_nm, so psd would swallow the band
        with self.assertRaises(gl.PlaceError) as cm:
            gl.generate(cfg)
        self.assertIn("sd_enc_activ", str(cm.exception))

    def test_taps_follow_the_second_process(self):
        """FakeProcess geometry: taps come from the config, with no engine change."""
        cfg = copy.deepcopy(CFG)
        cfg["process"].update(nmos_model="fake_n", pmos_model="fake_p", vdd_net="PWR", vss_net="GND", l_nm=200)
        lay = cfg["layout"]
        lay["row_height_nm"] = 4800
        lay["gate_pitch_nm"] = 600
        lay["rules"].update(m1_width_nm=200, m1_space_nm=220, rail_width_nm=200, poly_width_nm=200)
        R = lay["rules"]
        for name in ("sg13g2_inv_1", "sg13g2_inv_4"):
            S, W, H, sub, well = self.bands(name, cfg)
            self.assertEqual((sub[4] - sub[2], well[4] - well[2]),
                             (R["cont_nm"] + 2 * R["activ_enc_cont_nm"],) * 2, name)
            self.assertEqual(well[2], lay["row_height_nm"] - lay["p_diff_top_margin_nm"]
                             + R["poly_endcap_nm"] + R["poly_to_activ_nm"], name)
            nw = next(b for b in S.boxes if b[0] == "nwell")
            self.assertEqual(nw[4], well[4] + R["nwell_enc_nactiv_nm"], name)
            self.assertEqual(len([b for b in S.boxes if b[0] == "cont" and sub[2] <= b[2] <= sub[4]]),
                             W // lay["gate_pitch_nm"] - 1, name)


class MixedFingerWidths(unittest.TestCase):
    """One diffusion strip, devices of different drawn finger widths (issue #74).

    No cell in `example_config.json` has a mixed-width strip -- every candidate
    that does is still blocked by a limit this slice does not lift (a second
    channel track, a contact floor, gate-net realignment), so the capability is
    exercised on synthetic configs, the way `FakeProcess` exercises a second
    process. `channel_tracks` and every `rules` value in the committed config are
    untouched; see `test_no_rule_value_loosened`."""

    # and2_1's NMOS strip is the series pair (1000 nm fingers) plus the output
    # inverter (500 nm). It needs two channel tracks and a wider pitch to place
    # at all -- both out of scope here, hence the synthetic row.
    AND2 = {"name": "x_and2_1", "family": "and2", "drive": 1,
            "inputs": ["A", "B"], "outputs": {"X": "(A*B)"}}

    def mixed_cfg(self, cell=None):
        cfg = copy.deepcopy(CFG)
        cfg["layout"].update(row_height_nm=4200, gate_pitch_nm=840, channel_tracks=2)
        cfg["cells"] = [copy.deepcopy(cell or self.AND2)]
        return cfg

    def strip_runs(self, S, lay, strip):
        """The strip's `activ` rectangles, left to right (the tap bands sit on
        neither strip edge, so matching an edge selects the device runs)."""
        edge = lay["n_diff_y0_nm"] if strip == "n" else lay["row_height_nm"] - lay["p_diff_top_margin_nm"]
        i = 1 if strip == "n" else 3
        return sorted((b for b in S.boxes if b[0] == "activ" and b[i + 1] == edge), key=lambda b: b[1])

    def test_mixed_width_strip_places(self):
        cfg = self.mixed_cfg()
        S, W, H = gl.layout_cell(cfg["cells"][0], cfg["process"], cfg["layout"])
        self.assertEqual((W, H), (5 * 840, 4200))

    def test_activ_really_steps(self):
        cfg = self.mixed_cfg()
        lay = cfg["layout"]
        S, _, _ = gl.layout_cell(cfg["cells"][0], cfg["process"], lay)
        runs = self.strip_runs(S, lay, "n")
        self.assertEqual([b[4] - b[2] for b in runs], [1000, 500])  # two heights, not one
        self.assertEqual(len({b[4] - b[2] for b in self.strip_runs(S, lay, "p")}), 1)  # PMOS is uniform
        # Consecutive runs overlap in x, so the two rectangles merge into one
        # stepped polygon instead of leaving a gap at the shared node column.
        act_hang = CFG["layout"]["rules"]["cont_nm"] // 2 + CFG["layout"]["rules"]["activ_enc_cont_nm"]
        for a, b in zip(runs, runs[1:]):
            self.assertEqual(a[3] - b[1], 2 * act_hang, "runs must overlap at the shared node")

    def test_implants_and_well_follow_the_step(self):
        """One rectangle over the tallest run would over-enclose the short one."""
        cfg = self.mixed_cfg()
        lay, R = cfg["layout"], cfg["layout"]["rules"]
        sd = R["sd_enc_activ_nm"]
        S, _, _ = gl.layout_cell(cfg["cells"][0], cfg["process"], lay)
        for strip, implant in (("n", "nsd"), ("p", "psd")):
            for run in self.strip_runs(S, lay, strip):
                cover = [b for b in S.boxes if b[0] == implant
                         and b[1] <= run[1] - sd and b[2] <= run[2] - sd
                         and b[3] >= run[3] + sd and b[4] >= run[4] + sd]
                self.assertTrue(cover, f"{implant} does not enclose the run at {run[1:]}")
                self.assertTrue(any(b[4] - b[2] == (run[4] - run[2]) + 2 * sd for b in cover),
                                f"{implant} over {run[1:]} is not sized to that run")
        nwell = [b for b in S.boxes if b[0] == "nwell"]
        for run in self.strip_runs(S, lay, "p"):
            self.assertTrue(any(b[2] <= run[2] - R["nwell_enc_pactiv_nm"] for b in nwell), run[1:])

    def test_mixed_width_output_is_byte_deterministic(self):
        cfg = self.mixed_cfg()
        a = gl.generate(cfg)
        self.assertEqual(a, gl.generate(self.mixed_cfg()))
        self.assertEqual(set(a), {"x_and2_1.gds"})
        self.assertTrue(read_gds_boxes(a["x_and2_1.gds"]))

    def test_committed_cells_still_draw_one_run_per_strip(self):
        """The uniform-width cells must not pick up a spurious step."""
        for cell in CFG["cells"]:
            S, _, _ = layout_of(cell_named(cell["name"]))
            for strip in ("n", "p"):
                self.assertEqual(len(self.strip_runs(S, CFG["layout"], strip)), 1, cell["name"])

    def test_device_folded_below_the_contact_floor_is_named(self):
        """nor2's NMOS folds to 250 nm fingers, under the 300 nm a contact needs
        (2 * activ_enc_cont + cont). The floor is per device, so it fires even
        though the strip's tallest run is 800 nm."""
        cell = {"name": "x_nor2_1", "family": "nor2", "drive": 1,
                "inputs": ["A", "B"], "outputs": {"Y": "!(A+B)"}}
        cfg = self.mixed_cfg(cell)
        with self.assertRaises(gl.PlaceError) as cm:
            gl.generate(cfg)
        msg = str(cm.exception)
        self.assertIn("x_nor2_1", msg)
        self.assertIn("too short for a contact", msg)
        self.assertIn("250", msg)
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "c.json"
            p.write_text(json.dumps(cfg))
            r = run("--config", str(p))
            self.assertEqual(r.returncode, 3)
            self.assertIn("x_nor2_1", r.stderr)
            self.assertFalse((pathlib.Path(d) / "gds").exists())

    def test_failure_message_names_one_fingered_geometry(self):
        """The netlist generator states the fold itself (its `build` folds
        devices on a gate net to the shared count), so the netlist and the
        drawing cannot disagree on fingering and the message names one
        geometry -- nor2's NMOS is 2 fingers of 250 nm in both (issue #272
        dropped the layout-side fold that made the two differ)."""
        cell = {"name": "x_nor2_1", "family": "nor2", "drive": 1,
                "inputs": ["A", "B"], "outputs": {"Y": "!(A+B)"}}
        with self.assertRaises(gl.PlaceError) as cm:
            gl.generate(self.mixed_cfg(cell))
        msg = str(cm.exception)
        self.assertIn("2 fingers of 250 nm", msg)
        self.assertNotIn("netlist 500 nm", msg)

    def test_no_equal_split_names_the_gate_and_fingers(self):
        """The divisibility refusal lives once, in the netlist generator: a
        nor4's unit NMOS on gate A cannot share the gate's 4-finger split at
        any width on this grid, and the failure names the gate and the split.
        This is the scenario the demo config's removed `demo_nor4_1` encoded
        (#267); no committed config reaches it."""
        cell = {"name": "x_nor4_1", "family": "nor4", "drive": 1,
                "inputs": ["A", "B", "C", "D"], "outputs": {"Y": "!(A+B+C+D)"}}
        with self.assertRaises(gl.PlaceError) as cm:
            gl.generate(self.mixed_cfg(cell))
        msg = str(cm.exception)
        self.assertIn("x_nor4_1", msg)
        self.assertIn("gate A", msg)
        self.assertIn("4-finger split", msg)

    def test_implants_may_not_meet_in_the_channel(self):
        """Both implants grow `sd_enc_activ` into the channel, so a channel that
        clears the strips can still leave psd over nsd -- not a real mask."""
        cfg = self.mixed_cfg()
        cfg["layout"]["rules"] = dict(cfg["layout"]["rules"], sd_enc_activ_nm=900)
        with self.assertRaises(gl.PlaceError) as cm:
            gl.generate(cfg)
        self.assertIn("sd_enc_activ", str(cm.exception))


class DiffusionBreaks(unittest.TestCase):
    """Several diffusion chains per strip, separated by a diffusion break
    (issue #169): the break is a rule-derived gap, both strips shift at the
    union of their break positions so poly columns still cross both, the
    continuing strip bridges the other's break with its own diffusion, the
    n-well bridges every break (one well, one tap), and a net the break splits
    must be re-joined in Metal1 like any multi-node net -- the channel-track
    budget is the named limit it is, and some census break cells hit it next
    (others hit the contact floor or the n-well notch). No reachable cell
    places through a break under the committed config, so the geometry is exercised the way `ForcedNotch` exercises a profile: one
    break forced into the pairing the model picks -- the forcing behind the
    recorded `break-pmos-p420` control, whose DRC report and LVS match are
    committed in layout/drc/controls/."""

    A22OI = {"name": "x_a22oi_1", "family": "a22oi", "drive": 1,
             "inputs": ["A1", "A2", "B1", "B2"], "outputs": {"X": "!((A1*A2)+(B1*B2))"}}

    def force_break(self, strip="p", at=1):
        """The shared forcing (`gen_controls.forced_break`), entered for the
        rest of the test: one diffusion break forced into the pairing the
        model picks, keeping everything else about it."""
        self.enterContext(gc.forced_break(strip, at))

    def strip_runs_at(self, S, layer, edge_y, i):
        return sorted((b for b in S.boxes if b[0] == layer and b[i + 1] == edge_y), key=lambda b: b[1])

    def forced(self, cfg=None):
        cfg = cfg or CFG
        return gl.layout_cell(cell_named("sg13g2_nand2_1"), cfg["process"], cfg["layout"])

    def test_forced_break_places_and_parts_the_strip(self):
        self.force_break("p", 1)
        S, W, H = self.forced()
        # (N+2)*pitch + one gap: the 970 nm rule need rounded up to 3 pitches
        self.assertEqual((W, H), (4 * 420 + 1260, 3360))
        lay = CFG["layout"]
        pruns = self.strip_runs_at(S, "activ", lay["row_height_nm"] - lay["p_diff_top_margin_nm"], 3)
        self.assertEqual(len(pruns), 2, "the PMOS strip must part at its break")

    def test_break_gap_meets_the_space_rules(self):
        R, lay = CFG["layout"]["rules"], CFG["layout"]
        self.force_break("p", 1)
        S, _, _ = self.forced()
        act_hang = R["cont_nm"] // 2 + R["activ_enc_cont_nm"]
        pruns = self.strip_runs_at(S, "activ", lay["row_height_nm"] - lay["p_diff_top_margin_nm"], 3)
        self.assertGreaterEqual(pruns[1][1] - pruns[0][3], R["activ_space_nm"])
        psd = self.strip_runs_at(S, "psd", lay["row_height_nm"] - lay["p_diff_top_margin_nm"] + R["sd_enc_activ_nm"], 3)
        self.assertEqual(len(psd), 2)
        self.assertGreaterEqual(psd[1][1] - psd[0][3], R["psd_space_nm"])
        gap = pruns[1][1] - pruns[0][3] + 2 * act_hang  # the break width between node centres
        self.assertGreaterEqual(gap, 970)  # the rule need (psd binds) ...
        self.assertEqual(gap, 1260)  # ... rounded up to whole gate pitches (node columns stay on the grid)
        self.assertEqual(gap % CFG["layout"]["gate_pitch_nm"], 0)

    def test_break_cell_pins_stay_on_the_row4_grid(self):
        """The gap is a whole number of gate pitches, so node columns after a
        break are still routing-grid columns (issue #225 phase) and spec row 4's
        `off_grid_labels` is empty for a break cell, for a PMOS-strip break."""
        P = CFG["layout"]["gate_pitch_nm"]
        self.force_break("p", 1)
        S, W, _ = self.forced()
        self.assertEqual(off_grid_labels(S, P), [])
        self.assertEqual(W % P, 0)

    def test_continuing_strip_bridges_the_break(self):
        """The NMOS chain runs through the PMOS break: one activ run spans
        the gap, so the unbroken strip's diffusion stays continuous."""
        self.force_break("p", 1)
        lay = CFG["layout"]
        S, _, _ = self.forced()
        nruns = self.strip_runs_at(S, "activ", lay["n_diff_y0_nm"], 1)
        self.assertEqual(len(nruns), 1)
        pruns = self.strip_runs_at(S, "activ", lay["row_height_nm"] - lay["p_diff_top_margin_nm"], 3)
        self.assertLess(pruns[0][3], nruns[0][3])  # the gap is inside the NMOS span

    def test_nwell_bridges_the_break_as_one_well(self):
        self.force_break("p", 1)
        S, W, H = self.forced()
        nwell = sorted((b for b in S.boxes if b[0] == "nwell"), key=lambda b: b[1])
        # A uniform strip that breaks draws one box per chain, but each
        # reaches past the gap's midpoint, so the two merge into one region:
        # one well, one tap -- no nwell_space is owed across the break.
        self.assertEqual(len(nwell), 2)
        for a, b in zip(nwell, nwell[1:]):
            self.assertLessEqual(b[1], a[3], "the n-well boxes must overlap across the break")
        self.assertLessEqual(nwell[0][1], 420 - (CFG["layout"]["rules"]["cont_nm"] // 2
                                                 + CFG["layout"]["rules"]["activ_enc_cont_nm"]
                                                 + CFG["layout"]["rules"]["nwell_enc_pactiv_nm"]))
        self.assertGreater(nwell[-1][3], W)

    def test_break_width_comes_from_the_rules(self):
        cfg = copy.deepcopy(CFG)
        # The binding rule grows the gap: need 970 -> 1370, so the gap goes from
        # 3 to 4 pitches. (+100 would stay inside the 1260 nm quantum.)
        cfg["layout"]["rules"]["psd_space_nm"] += 400
        self.force_break("p", 1)
        a = self.forced()[1]
        b = self.forced(cfg)[1]
        self.assertEqual(b - a, CFG["layout"]["gate_pitch_nm"])

    def test_break_output_is_byte_deterministic(self):
        def gen():
            with gc.forced_break("p", 1):
                return gl.generate(copy.deepcopy(CFG))
        a, b = gen(), gen()
        self.assertEqual(a, b)
        self.assertTrue(read_gds_boxes(a["sg13g2_nand2_1.gds"]))

    def test_committed_config_names_the_split_nets(self):
        """a22oi's strips order only as two chains each; every internal net
        then has nodes in both chains and the split is named per net, with
        the break no longer the failure."""
        with self.assertRaises(gl.PlaceError) as cm:
            gl.generate({**copy.deepcopy(CFG), "cells": [self.A22OI]})
        msg = str(cm.exception)
        self.assertIn("x_a22oi_1", msg)
        self.assertIn("channel tracks", msg)
        for net in ("'X'", "'n1'", "'n2'", "'n3'"):
            self.assertIn(net, msg)
        self.assertNotIn("diffusion break", msg)

    def test_demo_census_reports_no_diffusion_break(self):
        """AC of issue #169: every demo cell either places or names a different
        limit. demo_xor2_1 / demo_mux2_1 / demo_a21oi_1 land on their measured
        next limits (a contact floor, a 550 nm nwell opening, a contact floor)."""
        design = json.loads((LAYOUT.parent / "design" / "example_config.json").read_text())
        for cell in design["cells"]:
            cfg = copy.deepcopy(CFG)
            cfg["cells"] = [cell]
            try:
                gl.generate(cfg)
                continue
            except gl.PlaceError as e:
                msg = str(e)
            self.assertNotIn("diffusion break", msg, cell["name"])
        for name, fragment in (("demo_xor2_1", "too short for a contact"),
                               ("demo_mux2_1", "an opening of 550 nm in nwell"),
                               ("demo_a21oi_1", "too short for a contact")):
            cell = next(c for c in design["cells"] if c["name"] == name)
            cfg = copy.deepcopy(CFG)
            cfg["cells"] = [cell]
            with self.assertRaises(gl.PlaceError) as cm:
                gl.generate(cfg)
            self.assertIn(fragment, str(cm.exception), name)


class GreedyFallback(unittest.TestCase):
    """The first-fit pairing `order_strips` falls back to when the bounded
    search exhausts its step cap (strips too large to search): at each
    position the lowest gate net and device indices win, and each strip
    independently takes the first orientation that continues its chain, or
    the first orientation at all when only breaking ones remain. The cap
    fires only on strips far larger than any census cell, so the fallback is
    asserted directly (the way NotchPredicate asserts its predicate), on a
    pairing with repeated gate nets and a break in each strip at a position
    where the other strip continues -- the tie-breaking the fallback owns,
    frozen from the nested-scan implementation it replaces (issue #269)."""

    def dev(self, i, kind, l, g, r, fingers=1):
        return (i, kind, l, g, r, 500 * fingers, fingers, fingers)

    def test_repeated_gates_and_asymmetric_breaks(self):
        ndevs = [self.dev(0, "n", "Y", "A", "Z", fingers=2),  # even fingers: the chain ends on its left net
                 self.dev(1, "n", "Y", "A", "X"),
                 self.dev(2, "n", "M", "B", "K"),  # no free B device continues X: the NMOS strip parts here
                 self.dev(3, "n", "K", "B", "W")]
        pdevs = [self.dev(0, "p", "Q", "A", "Z"),
                 self.dev(1, "p", "Z", "A", "V"),
                 self.dev(2, "p", "V", "B", "T"),  # continues its chain where the NMOS strip parts ...
                 self.dev(3, "p", "R", "B", "S")]  # ... and parts where the NMOS strip continues
        self.assertEqual(gl._greedy_pairing(ndevs, pdevs), (
            [(0, "Y", "Z"), (1, "Y", "X"), (2, "M", "K"), (3, "K", "W")], (2,),
            [(0, "Q", "Z"), (1, "Z", "V"), (2, "V", "T"), (3, "R", "S")], (3,),
        ))


def m1_components(S):
    """Metal1 boxes grouped into connected components: two boxes whose edges
    touch or that overlap are one conductor, the way extraction merges
    abutting metal."""
    boxes = [b[1:] for b in S.boxes if b[0] == "metal1"]
    parent = list(range(len(boxes)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(boxes):
        for j in range(i):
            b = boxes[j]
            if a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]:
                parent[find(i)] = find(j)
    return boxes, [find(i) for i in range(len(boxes))]


class DrivenGateRoute(unittest.TestCase):
    """A gate whose net is also driven from diffusion -- buf's internal Y_i,
    the first stage's output feeding the second stage's gate -- is a terminal
    of that net's Metal1 route, not a standalone labelled pad (issue #201).
    Before the fix this exact fixture generated cleanly and LVS split Y_i:
    6 layout nets for the reference's 5, one net.split, two device.unmatched,
    with the pad's left edge 515 nm from its track's right edge."""

    def buf_cfg(self, **layout_over):
        cfg = copy.deepcopy(CFG)
        cfg["process"].update(grid_nm=5, unit_n_nm=900, unit_p_nm=2430)
        cfg["layout"].update(row_height_nm=4200, gate_pitch_nm=550, channel_tracks=2)
        cfg["layout"].update(layout_over)
        cfg["cells"] = [{"name": "buf", "family": "buf", "drive": 2,
                         "inputs": ["A"], "outputs": {"Y": "A"}}]
        return cfg

    def route(self, S, text):
        """(Metal1 boxes, contacts under them) of the component carrying a
        net label: reading the drawn geometry, not the generator's bookkeeping
        -- the bug was that the bookkeeping said fine while the metal was
        two pieces."""
        boxes, roots = m1_components(S)
        lx, ly = next((x, y) for lay, x, y, t in S.labels if lay == "metal1_label" and t == text)
        root = next(roots[i] for i, b in enumerate(boxes) if b[0] <= lx <= b[2] and b[1] <= ly <= b[3])
        comp = [b for i, b in enumerate(boxes) if roots[i] == root]
        conts = [c for c in S.boxes if c[0] == "cont"
                 and any(c[1] < b[2] and b[0] < c[3] and c[2] < b[3] and b[1] < c[4] for b in comp)]
        return comp, conts

    def on_poly(self, S, cont):
        return any(cont[1] < p[3] and p[1] < cont[3] and cont[2] < p[4] and p[2] < cont[4]
                   for p in S.boxes if p[0] == "gatpoly")

    def test_driven_gate_is_a_terminal_of_its_nets_route(self):
        cfg = self.buf_cfg()
        S, W, H = gl.layout_cell(cfg["cells"][0], cfg["process"], cfg["layout"])
        comp, conts = self.route(S, "Y_i")
        # the second-stage gate contact: a contact of this component on poly
        self.assertTrue(any(self.on_poly(S, c) for c in conts), "no gate contact on the Y_i route")
        # the first-stage drains: contacts of the SAME component in each strip
        mid = cfg["layout"]["row_height_nm"] // 2
        diffs = [c for c in conts if not self.on_poly(S, c)]
        self.assertTrue(any((c[2] + c[4]) // 2 < mid for c in diffs), "Y_i does not reach the NMOS strip")
        self.assertTrue(any((c[2] + c[4]) // 2 > mid for c in diffs), "Y_i does not reach the PMOS strip")

    def test_input_gate_keeps_its_standalone_pad(self):
        cfg = self.buf_cfg()
        S, _, _ = gl.layout_cell(cfg["cells"][0], cfg["process"], cfg["layout"])
        comp, conts = self.route(S, "A")
        self.assertEqual(len(conts), 1, "an input pad should carry exactly its gate contact")
        self.assertTrue(self.on_poly(S, conts[0]))

    def test_nets_stay_separate_conductors(self):
        cfg = self.buf_cfg()
        S, W, H = gl.layout_cell(cfg["cells"][0], cfg["process"], cfg["layout"])
        boxes, roots = m1_components(S)
        seen = set()
        for text in ("A", "Y_i", "Y", "VSS", "VDD"):
            lx, ly = next((x, y) for lay, x, y, t in S.labels if lay == "metal1_label" and t == text)
            root = next(roots[i] for i, b in enumerate(boxes) if b[0] <= lx <= b[2] and b[1] <= ly <= b[3])
            self.assertNotIn(root, seen, f"{text} shares Metal1 with another labelled net")
            seen.add(root)

    def test_placed_buffer_is_byte_deterministic(self):
        cfg = self.buf_cfg()
        self.assertEqual(gl.generate(cfg), gl.generate(self.buf_cfg()))

    def test_unroutable_driven_gate_refuses_naming_cell_net_and_constraint(self):
        """At the shipped 420 pitch the same drive-2 buffer cannot land Y_i's
        riser clear of the neighbouring stubs: exit 3 naming the cell, the
        internal net and the routing constraint, with no partial GDS written
        (a standalone labelled pad instead of the riser is exactly the split
        this issue is about, so the refusal is the only other outcome)."""
        cfg = self.buf_cfg(gate_pitch_nm=420)
        with self.assertRaises(gl.PlaceError) as cm:
            gl.generate(cfg)
        msg = str(cm.exception)
        self.assertIn("buf", msg)
        # Whichever gate pad runs out of room first is the one named: the
        # input's contact or the internal net's riser.
        self.assertRegex(msg, r"riser|gate contact of A")
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "c.json"
            p.write_text(json.dumps(cfg))
            r = run("--config", str(p))
            self.assertEqual(r.returncode, 3)
            self.assertRegex(r.stderr, r"riser|gate contact of A")
            self.assertFalse((pathlib.Path(d) / "gds").exists())

    def test_break_selected_buffer_beside_inverter_is_placed_or_refused(self):
        """A buffer on A beside an inverter on B needs an automatic diffusion
        break (issue #169 review). Its internal gate net Y_i must either be
        one conductor with the first stage's drains, or the cell must be
        refused naming Y_i and the riser -- never drawn with Y_i's pad as an
        island (the split LVS reports as net.split)."""
        cfg = copy.deepcopy(CFG)
        cfg["layout"].update(row_height_nm=6200, gate_pitch_nm=840, channel_tracks=5)
        cfg["cells"] = [{"name": "probe", "family": "probe", "drive": 1,
                         "inputs": ["A", "B"], "outputs": {"Y": "A", "Z": "!B"}}]
        try:
            S, W, H = gl.layout_cell(cfg["cells"][0], cfg["process"], cfg["layout"])
        except gl.PlaceError as e:
            self.assertIn("Y_i", str(e))
            self.assertIn("riser", str(e))
            return
        # Read the drawn conductor, not its rectangle count: Y_i's component
        # must carry the second stage's gate contact AND drain contacts in
        # both strips, or the gate is an island however many boxes it has.
        comp, conts = self.route(S, "Y_i")
        self.assertTrue(any(self.on_poly(S, c) for c in conts), "no gate contact on the Y_i route")
        mid = cfg["layout"]["row_height_nm"] // 2
        diffs = [c for c in conts if not self.on_poly(S, c)]
        self.assertTrue(any((c[2] + c[4]) // 2 < mid for c in diffs), "Y_i does not reach the NMOS strip")
        self.assertTrue(any((c[2] + c[4]) // 2 > mid for c in diffs), "Y_i does not reach the PMOS strip")


def notch_layers(cfg=CFG):
    """The per-strip layer tables the notch predicate checks, from the config:
    activ on both strips, psd and the n-well on the PMOS strip only (the deck
    models no nsd space rule), each entry as (hang_nm, threshold_nm)."""
    R = cfg["layout"]["rules"]
    act = R["cont_nm"] // 2 + R["activ_enc_cont_nm"]
    return {
        "n": {"activ": (act, R["activ_space_nm"])},
        "p": {"activ": (act, R["activ_space_nm"]),
              "psd": (act + R["sd_enc_activ_nm"], R["psd_space_nm"]),
              "nwell": (act + R["nwell_enc_pactiv_nm"], R["nwell_space_nm"])},
    }


class NotchPredicate(unittest.TestCase):
    """A valley in a strip's height profile is a re-entrant notch whose
    legality is per run, per layer and per strip (issue #86): a short run of k
    columns leaves an opening of k * gate_pitch_nm - 2 * hang in each layer
    drawn over it, legal when the opening is <= 0 (the taller neighbours'
    shapes merge) or >= that layer's space minimum. The table below is the
    shipped rules' verdicts; the rows the generator admits or refuses are
    also measured, not just asserted -- see the controls in layout/drc/controls/.
    No cell reachable through design/gen_netlists.py produces a notched
    profile, so the predicate is asserted directly."""

    def hit(self, prof, pitch, strip):
        r = gl._notch_violation(prof, pitch, notch_layers()[strip])
        return None if r is None else r[:3]

    def valley(self, k):
        return [1000] + [500] * k + [1000]

    def test_band_table(self):
        # (pitch, k, NMOS verdict, PMOS verdict); None = admitted, otherwise
        # (layer, opening, threshold)
        table = [
            (420, 1, ("activ", 120, 210), ("activ", 120, 210)),  # the shipped refusal is correct
            (420, 2, None, ("psd", 180, 310)),                   # strip-asymmetric: same valley, one strip fine
            (420, 3, None, ("nwell", 340, 620)),
            (420, 4, None, None),
            (560, 1, None, None),                                # implant/well openings go negative: merged
            (600, 1, None, None),                                # the pitch notch-pmos-p600-merged was recorded at
            (840, 1, None, ("psd", 180, 310)),                   # an activ-only check would wrongly admit this
            (1000, 1, None, ("nwell", 80, 620)),                 # the n-well is the binding layer here
        ]
        for pitch, k, n, p in table:
            prof = self.valley(k)
            self.assertEqual(self.hit(prof, pitch, "n"), n, f"P={pitch} k={k} NMOS")
            self.assertEqual(self.hit(prof, pitch, "p"), p, f"P={pitch} k={k} PMOS")

    def test_band_edges(self):
        self.assertIsNone(self.hit(self.valley(1), 510, "n"))   # opening exactly 210 == activ_space_nm
        self.assertEqual(self.hit(self.valley(1), 500, "n"), ("activ", 200, 210))  # one below refuses
        self.assertIsNone(self.hit(self.valley(1), 660, "p"))   # psd opening exactly 0: shapes touch
        self.assertIsNone(self.hit(self.valley(1), 280, "p"))   # every opening <= 0: merged, no notch

    def test_no_valley_no_check(self):
        self.assertIsNone(self.hit([500], 420, "n"))              # single run
        self.assertIsNone(self.hit([500, 1000], 420, "n"))        # monotone up
        self.assertIsNone(self.hit([1000, 1000, 500], 420, "n"))  # monotone down
        self.assertIsNone(self.hit([500, 1000, 500], 420, "n"))   # a peak, not a notch
        self.assertIsNone(self.hit([500, 1000, 500], 420, "p"))   # ...on either strip

    def test_two_valleys(self):
        prof = [1000, 500, 1000, 500, 1000]
        self.assertEqual(self.hit(prof, 420, "n"), ("activ", 120, 210))  # the first valley refuses
        self.assertIsNone(self.hit(prof, 840, "n"))                      # both admitted at the wider pitch

    def test_wide_short_run_scales_the_opening(self):
        # k counts columns: a two-column valley at the shipped pitch leaves a
        # 540 nm activ opening where a one-column valley leaves 120 nm
        self.assertIsNone(self.hit(self.valley(2), 420, "n"))
        self.assertEqual(self.hit(self.valley(1), 420, "n"), ("activ", 120, 210))

    def test_unequal_tall_heights_either_side(self):
        # the notch is shallower on one side; the rule is depth-independent, so
        # the verdict depends only on the opening
        self.assertEqual(self.hit([1000, 500, 700], 420, "n"), ("activ", 120, 210))
        self.assertIsNone(self.hit([1000, 500, 700], 640, "n"))  # 640 - 300 = 340 >= 210


class ForcedNotch(unittest.TestCase):
    """End-to-end refusal and admission, with a strip's drawn profile forced
    the way issue #86's original measurement forced it (no reachable cell
    notches, so the profile cannot arise on its own). The forcing is the
    control generator's own `forced_strip_profile` -- the code the recorded
    controls in layout/drc/controls/ were produced with."""

    AND2 = {"name": "x_and2_1", "family": "and2", "drive": 1,
            "inputs": ["A", "B"], "outputs": {"X": "(A*B)"}}

    def forced_cfg(self, pitch=840):
        cfg = copy.deepcopy(CFG)
        cfg["layout"].update(row_height_nm=4200, gate_pitch_nm=pitch, channel_tracks=2)
        cfg["cells"] = [copy.deepcopy(self.AND2)]
        return cfg

    def force(self, strip, prof, notch_off=False):
        """The shared forcing (`gen_controls.forced_strip_profile`), entered
        for the rest of the test: `prof` handed back for `strip`'s devices --
        and, for drawing a refused notch (the DRC controls), the check itself."""
        self.enterContext(gc.forced_strip_profile(strip, prof, notch_off))

    def test_pmos_notch_refused_naming_cell_strip_layer_and_numbers(self):
        cfg = self.forced_cfg(pitch=840)
        self.force("p", [800, 500, 800])
        with self.assertRaises(gl.PlaceError) as cm:
            gl.generate(cfg)
        msg = str(cm.exception)
        self.assertIn("x_and2_1", msg)                                   # the cell
        self.assertIn("PMOS strip height profile [800, 500, 800]", msg)  # the strip and the profile
        self.assertIn("psd", msg)                                        # the offending layer
        self.assertIn("180 nm", msg)                                     # the opening: 840 - 2 * (150 + 180)
        self.assertIn("310 nm", msg)                                     # the threshold: psd_space_nm
        # the identical valley on the NMOS strip is fine -- psd/nwell do not
        # bind there and activ admits it; only the PMOS strip refuses the cell
        self.assertIsNone(gl._notch_violation([800, 500, 800], 840, notch_layers()["n"]))

    def test_admitted_nmos_notch_places_and_draws(self):
        cfg = self.forced_cfg(pitch=840)
        self.force("n", [1000, 500, 1000])
        S, W, H = gl.layout_cell(cfg["cells"][0], cfg["process"], cfg["layout"])
        self.assertEqual(W, 5 * 840)
        runs = [b for b in S.boxes if b[0] == "activ" and b[2] == cfg["layout"]["n_diff_y0_nm"]]
        self.assertEqual(sorted(b[4] - b[2] for b in runs), [500, 1000, 1000])  # the notch is really drawn

    def test_admitted_pmos_merged_valley_places_and_draws(self):
        """issue #114: the `opening <= 0` merged admit, measured as
        layout/drc/controls/notch-pmos-p600-merged. The shipped inv_4 device
        set at pitch 600 with the PMOS strip forced to [800, 500, 800, 800]:
        activ admits on the >= threshold arm (600 - 300 = 300 >= 210) while
        psd (600 - 660 = -60) and nwell (600 - 920 = -320) merge, so the
        predicate admits the row with the check live."""
        cfg = copy.deepcopy(CFG)
        cfg["layout"]["gate_pitch_nm"] = 600
        cell = next(c for c in cfg["cells"] if c["name"] == "sg13g2_inv_4")
        self.force("p", [800, 500, 800, 800])
        S, W, H = gl.layout_cell(cell, cfg["process"], cfg["layout"])
        self.assertEqual(W, 6 * 600)  # (N + 2) * pitch for N = 4 columns
        p_y1 = cfg["layout"]["row_height_nm"] - cfg["layout"]["p_diff_top_margin_nm"]
        R = cfg["layout"]["rules"]
        hang = R["cont_nm"] // 2 + R["activ_enc_cont_nm"]
        pitch = cfg["layout"]["gate_pitch_nm"]
        runs = [b for b in S.boxes if b[0] == "activ" and b[4] == p_y1]
        self.assertEqual(sorted(b[4] - b[2] for b in runs), [500, 800, 800])  # the merged valley is really drawn
        self.assertEqual(sorted(b[3] - b[1] for b in runs),                     # runs [800] [500] [800 800]:
                         [pitch + 2 * hang, pitch + 2 * hang, 2 * pitch + 2 * hang])  # the tall side is two columns
        self.assertIsNone(gl._notch_violation([800, 500, 800, 800], 600, notch_layers()["p"]))


class Failures(unittest.TestCase):
    def test_unplaceable_cell_named_and_nothing_written(self):
        cfg = copy.deepcopy(CFG)
        cfg["cells"].append({"name": "x_xor2_1", "family": "xor2", "drive": 1, "inputs": ["A", "B"], "outputs": {"X": "(A^B)"}})
        with self.assertRaises(gl.PlaceError) as cm:
            gl.generate(cfg)
        self.assertIn("x_xor2_1", str(cm.exception))
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "c.json"
            p.write_text(json.dumps(cfg))
            r = run("--config", str(p))
            self.assertEqual(r.returncode, 3)
            self.assertIn("x_xor2_1", r.stderr)
            self.assertFalse((pathlib.Path(d) / "gds").exists())

    def test_row_too_short(self):
        cfg = copy.deepcopy(CFG)
        cfg["layout"]["row_height_nm"] = 2000
        with self.assertRaises(gl.PlaceError):
            gl.generate(cfg)


class T1Fixture(unittest.TestCase):
    """Issue #171: the consumer shapes (buffer, folded nand2, folded nor2) on a
    3360 nm row at 420 nm pitch, margins 350/330, from a committed synthetic
    config so the consumer case is exercised here without reading another repo.

    None of the seven places in the Metal1-only single-row model; the point of
    these tests is that each one still exits 3 with the *measured* named limit,
    at every track count the config could allow, and writes no partial GDS. If
    a generator change places one of them, the matching row fails here and the
    README table (\"What still blocks buf / folded nand2 / folded nor2\") must
    be re-measured in the same change."""
    FIXTURE = json.loads((pathlib.Path(__file__).resolve().parent / "fixtures" / "t1_row3360.json").read_text())
    EXPECT = {
        1: {"buf": "need 2 channel tracks, config allows 1", "nand2": "need 2 channel tracks, config allows 1",
            "nor2": "need 2 channel tracks, config allows 1"},
        2: {"buf": "channel too short for track 2 of net X_i", "nand2": "Metal1 of Y overlaps n1",
            "nor2": "no Metal1-clean spot for the gate contact of A"},
        3: {"buf": "channel too short for track 2 of net X_i", "nand2": "Metal1 of Y overlaps n1",
            "nor2": "no Metal1-clean spot for the gate contact of A"},
    }

    def one(self, cell, tracks):
        cfg = copy.deepcopy(self.FIXTURE)
        cfg["layout"]["channel_tracks"] = tracks
        cfg["cells"] = [cell]
        return cfg

    def test_geometry_is_the_consumer_sizing(self):
        lay = self.FIXTURE["layout"]
        self.assertEqual((lay["row_height_nm"], lay["gate_pitch_nm"], lay["n_diff_y0_nm"], lay["p_diff_top_margin_nm"]),
                         (3360, 420, 350, 330))
        self.assertEqual([c["name"] for c in self.FIXTURE["cells"]],
                         ["fx_buf_1", "fx_buf_2", "fx_buf_4", "fx_nand2_1", "fx_nand2_2", "fx_nor2_1", "fx_nor2_2"])

    def test_each_shape_exits_3_with_its_measured_limit(self):
        for tracks, want in self.EXPECT.items():
            for cell in self.FIXTURE["cells"]:
                with self.subTest(cell=cell["name"], channel_tracks=tracks):
                    with self.assertRaises(gl.PlaceError) as cm:
                        gl.generate(self.one(cell, tracks))
                    self.assertIn(cell["name"], str(cm.exception))
                    self.assertIn(want[cell["family"]], str(cm.exception))

    def test_failure_is_deterministic_and_writes_no_gds(self):
        cell = self.FIXTURE["cells"][1]
        msgs = []
        for _ in range(2):
            with self.assertRaises(gl.PlaceError) as cm:
                gl.generate(self.one(cell, 2))
            msgs.append(str(cm.exception))
        self.assertEqual(msgs[0], msgs[1])
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "c.json"
            p.write_text(json.dumps(self.one(cell, 2)))
            r = run("--config", str(p))
            self.assertEqual(r.returncode, 3)
            self.assertEqual(list((pathlib.Path(d) / "gds").glob("*.gds")) if (pathlib.Path(d) / "gds").exists() else [], [])

    def test_demo_buf_and_and2_still_name_their_limit(self):
        design = json.loads((LAYOUT.parent / "design" / "example_config.json").read_text())
        for name in ("demo_buf_2", "demo_and2_1"):
            cfg = copy.deepcopy(CFG)
            cfg["process"] = copy.deepcopy(CFG["process"])
            cfg["layout"]["channel_tracks"] = 1
            cfg["cells"] = [c for c in design["cells"] if c["name"] == name]
            with self.subTest(cell=name):
                with self.assertRaises(gl.PlaceError) as cm:
                    gl.generate(cfg)
                self.assertIn("nets ['X', 'X_i'] need 2 channel tracks, config allows 1", str(cm.exception))


class FoldedSeriesInterleave(unittest.TestCase):
    """Issue #257, re-measured after the diffusion break (#169) merged: the
    break does not lift the folded nand2/nor2 rows of `t1_row3360.json`. A
    folded series device alternates its two terminals on successive
    boundaries (l r l ...), so the internal node `n1` and the output `Y`
    interleave *inside the series device's own columns* -- a break lands
    between devices, where neither net is, so no ordering separates them:
    whichever net takes the upper channel track, the other's far-side stubs
    cross its band inside that span. The measurement exhausts the model's
    own pairing search (`_pairings`: every ordering, orientation and break
    position) crossed with both track assignments -- the second reached by
    renaming `n1` ahead of `Y`, neither net being a gate, so the
    alphabetical track order is the only difference -- with `layout_cell`
    itself as the oracle. If a generator change places one of these cells,
    these tests failing are the signal to re-measure the README table
    ("What blocks buf, folded nand2 and folded nor2")."""

    FIXTURE = json.loads((pathlib.Path(__file__).resolve().parent / "fixtures" / "t1_row3360.json").read_text())
    CELLS = [c for c in FIXTURE["cells"] if c["family"] in ("nand2", "nor2")]

    def pairings(self, cell):
        """Every (n_order, n_breaks, p_order, p_breaks) the search space
        holds: `_pairings` at every break budget, deduplicated."""
        c = gl.gn.build(cell, self.FIXTURE["process"])
        devs = [(i,) + d for i, d in enumerate(c.devices)]
        nd = [d for d in devs if d[1] == "n"]
        pd = [d for d in devs if d[1] == "p"]
        out, seen = [], set()
        for budget in range(len(nd) + 1):
            cand = gl._pairings(nd, pd, budget, cap=300_000)
            if cand is None:
                break
            for p in cand:
                key = (tuple(p[0]), p[1], tuple(p[2]), p[3])
                if key not in seen:
                    seen.add(key)
                    out.append(p)
        return out

    def renamed_build(self):
        """A `gn.build` with `n1` renamed ahead of `Y`, swapping the two
        channel tracks: neither net is a gate net, so the alphabetical track
        order is the only thing the rename changes."""
        build = gl.gn.build

        def patched(cell, proc):
            c = gl.gn.Cell(cell["name"], proc)
            c.devices = [(k, "An" if d == "n1" else d, g, "An" if s == "n1" else s, w, ng)
                         for (k, d, g, s, w, ng) in build(cell, proc).devices]
            return c

        return patched

    def outcomes(self, cell, tracks, pitch=None, row=None):
        """Count layout_cell outcomes for each spelling of the internal net."""
        lay = copy.deepcopy(self.FIXTURE["layout"])
        lay["channel_tracks"] = tracks
        if pitch is not None:
            lay["gate_pitch_nm"] = pitch
        if row is not None:
            lay["row_height_nm"] = row
        proc = self.FIXTURE["process"]
        summary = {}
        for internal_net, build in (("n1", gl.gn.build), ("An", self.renamed_build())):
            counts = Counter()
            with patch.object(gl.gn, "build", build):
                # Each pairing embeds the terminal names from this build.
                pairings = self.pairings(cell)
                self.assertEqual(len(pairings), 32)
                for pairing in pairings:
                    with patch.object(gl, "order_strips", return_value=pairing):
                        try:
                            gl.layout_cell(cell, proc, lay)
                            verdict = "placed"
                        except gl.PlaceError as e:
                            verdict = str(e).partition(" (")[0]
                            if verdict.startswith("no Metal1-clean spot for the gate contact of "):
                                verdict = "gate-contact spot"
                    counts[verdict] += 1
            summary[internal_net] = counts
        return summary

    def test_exhausts_the_pairing_space_at_the_fixture_geometry(self):
        for cell in self.CELLS:
            for tracks in (2, 3):
                with self.subTest(cell=cell["name"], channel_tracks=tracks):
                    if cell["family"] == "nand2":
                        expected = {
                            "n1": {"Metal1 of Y overlaps n1": 8, "gate-contact spot": 24},
                            "An": {"Metal1 of An overlaps Y": 8, "gate-contact spot": 24},
                        }
                    else:
                        expected = {"n1": {"gate-contact spot": 32}, "An": {"gate-contact spot": 32}}
                    self.assertEqual(self.outcomes(cell, tracks), expected)

    def test_taller_rows_lift_nothing(self):
        for cell in self.CELLS:
            for row in (4200, 4620):
                with self.subTest(cell=cell["name"], row_height_nm=row):
                    for counts in self.outcomes(cell, 2, row=row).values():
                        self.assertNotIn("placed", counts)

    def test_a_pitch_that_fits_the_pads_leaves_only_the_crossing(self):
        """At a 1260 nm pitch the 300 nm gate pads fit beside the poly
        stripes, so the pad-crowding failure of the 420 nm fixture drops out
        and every candidate of all four cells dies on the Y/n1 Metal1
        crossing itself: the crossing, not the pad, is the pitch- and
        row-height-independent limit (the recorded README numbers)."""
        for cell in self.CELLS:
            with self.subTest(cell=cell["name"]):
                self.assertEqual(self.outcomes(cell, 2, pitch=1260),
                                 {"n1": {"Metal1 of Y overlaps n1": 32},
                                  "An": {"Metal1 of An overlaps Y": 32}})


class FakeProcess(unittest.TestCase):
    """A second process (different names, layers, geometry) needs no code change."""

    def test_fake_process(self):
        cfg = copy.deepcopy(CFG)
        cfg["process"].update(nmos_model="fake_n", pmos_model="fake_p", vdd_net="PWR", vss_net="GND", l_nm=200)
        lay = cfg["layout"]
        lay["row_height_nm"] = 4800
        lay["gate_pitch_nm"] = 600
        lay["layers"] = {k: [50 + i, 3] for i, k in enumerate(lay["layers"])}
        lay["rules"].update(m1_width_nm=200, m1_space_nm=220, rail_width_nm=200, poly_width_nm=200)
        base, fake = gl.generate(CFG), gl.generate(cfg)
        self.assertEqual(set(base), set(fake))
        self.assertNotEqual(base["sg13g2_inv_1.gds"], fake["sg13g2_inv_1.gds"])
        layers = {(l, d) for data in fake.values() for l, d, _, _ in read_gds_boxes(data)}
        self.assertTrue(all(l >= 50 and d == 3 for l, d in layers))
        S, W, H = gl.layout_cell(cfg["cells"][0], cfg["process"], lay)
        self.assertEqual((W, H), (3 * 600, 4800))


if __name__ == "__main__":
    unittest.main()
