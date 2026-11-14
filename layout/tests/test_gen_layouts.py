"""Tests for layout/gen_layouts.py: config validation, determinism, --check
exit codes, named placement failures, and a second (fake) process config."""
import copy
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

LAYOUT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAYOUT))
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

    def test_bad_layer(self):
        self.bad(lambda c: c["layout"]["layers"].update(metal1=[8]))

    def test_odd_pitch(self):
        self.bad(lambda c: c["layout"].update(gate_pitch_nm=421))

    def test_netlist_side_validation_still_applies(self):
        self.bad(lambda c: c["process"].pop("l_nm"))

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
        self.assertEqual((W, H), (3 * 420, 3360))


def cell_named(name):
    return next(c for c in CFG["cells"] if c["name"] == name)


def layout_of(cell, cfg=CFG):
    return gl.layout_cell(cell, cfg["process"], cfg["layout"])


class MultiFinger(unittest.TestCase):
    def test_two_finger_inverter_places(self):
        S, W, H = layout_of(cell_named("sg13g2_inv_2"))
        self.assertEqual((W, H), (3 * 420, 3360))
        cols = [b for b in S.boxes if b[0] == "gatpoly" and b[4] - b[2] > 1000]  # full-height stripes
        self.assertEqual(sorted((b[1] + b[3]) // 2 for b in cols), [420, 840])

    def test_width_grows_with_finger_count(self):
        w = {n: layout_of(cell_named(n))[1] for n in ("sg13g2_inv_1", "sg13g2_inv_2", "sg13g2_inv_4")}
        self.assertEqual(w, {"sg13g2_inv_1": 2 * 420, "sg13g2_inv_2": 3 * 420, "sg13g2_inv_4": 5 * 420})

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

    def test_even_finger_series_chain_needs_diffusion_break(self):
        cfg = copy.deepcopy(CFG)
        cfg["cells"] = [{"name": "x_nand4_1", "family": "nand4", "drive": 1, "inputs": ["A", "B", "C", "D"], "outputs": {"Y": "!(A*B*C*D)"}}]
        with self.assertRaises(gl.PlaceError) as cm:
            gl.generate(cfg)
        self.assertIn("x_nand4_1", str(cm.exception))
        self.assertIn("diffusion", str(cm.exception))

    def test_no_rule_value_loosened(self):
        self.assertEqual(CFG["layout"]["rules"], {
            "poly_width_nm": 130, "poly_space_nm": 180, "poly_endcap_nm": 180, "poly_to_activ_nm": 70, "cont_nm": 160,
            "cont_space_nm": 180, "activ_enc_cont_nm": 70, "poly_enc_cont_nm": 70, "m1_width_nm": 160, "m1_space_nm": 180,
            "rail_width_nm": 160, "nwell_enc_pactiv_nm": 310, "nwell_enc_nactiv_nm": 240, "activ_space_nm": 210,
            "sd_enc_activ_nm": 180})
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
                self.assertEqual(len(conts), W // CFG["layout"]["gate_pitch_nm"], cell["name"])
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
        cfg = copy.deepcopy(CFG)
        cfg["layout"]["layers"].pop("nsd")
        with self.assertRaises(gl.PlaceError) as cm:
            gl.generate(cfg)
        self.assertIn("nsd", str(cm.exception))
        self.assertIn("sg13g2_inv_1", str(cm.exception))

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
                             W // lay["gate_pitch_nm"], name)


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
        self.assertEqual((W, H), (2 * 600, 4800))


if __name__ == "__main__":
    unittest.main()
