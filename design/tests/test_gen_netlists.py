"""Tests for design/gen_netlists.py against the demo config.

The generated netlists are parsed independently of the generator and checked
with a switch-level truth-table simulation. Models are the demo config's
placeholder names, not any PDK.
"""
import copy
import itertools
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

DESIGN = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESIGN))
import gen_netlists as gn  # noqa: E402

CONFIG = DESIGN / "example_config.json"
CFG = json.loads(CONFIG.read_text())
PROC = CFG["process"]


def parse_netlist(text):
    devs, ports = [], None
    for line in text.splitlines():
        if line.startswith(".subckt"):
            ports = line.split()[2:]
        elif line.startswith("X"):
            t = line.split()
            params = dict(p.split("=") for p in t[6:])
            devs.append((t[5], t[1], t[2], t[3], params))
    return ports, devs


def switch_level(devs, vec):
    vdd, vss = PROC["vdd_net"], PROC["vss_net"]
    val = dict(vec, **{vdd: 1, vss: 0})
    for _ in range(len(devs) + 2):
        parent = {}

        def find(x):
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for model, d, g, s, _ in devs:
            gv = val.get(g)
            if gv is None:
                continue
            if (model == PROC["nmos_model"] and gv == 1) or (model == PROC["pmos_model"] and gv == 0):
                parent[find(d)] = find(s)
        new = dict(vec, **{vdd: 1, vss: 0})
        for n in {n for _, d, _, s, _ in devs for n in (d, s)}:
            hi, lo = find(n) == find(vdd), find(n) == find(vss)
            if hi and lo:
                raise AssertionError(f"short between rails via {n}")
            if hi or lo:
                new[n] = int(hi)
        if new == val:
            return val
        val = new
    return val


class TopologyTest(unittest.TestCase):
    def test_truth_tables_switch_level_all_cells(self):
        files = gn.generate(CFG, CONFIG.name)
        for cell in CFG["cells"]:
            ports, devs = parse_netlist(files[f"{cell['name']}.spice"])
            self.assertEqual(ports, cell["inputs"] + sorted(cell["outputs"]) + [PROC["vdd_net"], PROC["vss_net"]])
            for bits in itertools.product((0, 1), repeat=len(cell["inputs"])):
                vec = dict(zip(cell["inputs"], bits))
                got = switch_level(devs, vec)
                for pin, fn in cell["outputs"].items():
                    self.assertEqual(got.get(pin), gn.evaluate(gn.parse(fn), vec), f"{cell['name']} {vec} {pin}")

    def test_demo_covers_required_topologies(self):
        fams = {c["family"] for c in CFG["cells"]}
        for f in ("inv", "nand2", "a21oi", "buf", "a21o", "xor2", "xnor2", "mux2", "mux2i"):
            self.assertIn(f, fams)

    def test_non_inverting_has_output_inverter(self):
        files = gn.generate(CFG, CONFIG.name)
        _, devs = parse_netlist(files["demo_buf_2.spice"])
        self.assertEqual(len(devs), 4)  # stage inverter + output inverter

    def test_xor_shares_complement_literals(self):
        files = gn.generate(CFG, CONFIG.name)
        _, devs = parse_netlist(files["demo_xor2_1.spice"])
        inverters = [d for d in devs if d[2] in ("A", "B") and d[1].endswith("_b")]
        self.assertEqual(len(inverters), 4)  # one n+p unit inverter each for A and B, not per use

    def test_four_input_stack_compensation(self):
        files = gn.generate(CFG, CONFIG.name)
        _, devs = parse_netlist(files["demo_nand4_1.spice"])
        nw = {int(p["w"][:-1]) for m, *_, p in devs if m == PROC["nmos_model"]}
        self.assertEqual(nw, {PROC["unit_n_nm"] * 4})

    def test_finger_caps_respected(self):
        for text in gn.generate(CFG, CONFIG.name).values():
            for model, _, _, _, prm in parse_netlist(text)[1]:
                w, ng = int(prm["w"][:-1]), int(prm["ng"])
                cap = PROC["finger_max_n"] if model == PROC["nmos_model"] else PROC["finger_max_p"]
                self.assertLessEqual(w / ng, cap)
                self.assertEqual(w % ng, 0)

    def test_config_injection_changes_output(self):
        cfg = copy.deepcopy(CFG)
        cfg["process"].update(nmos_model="other_n", nmos_prefix="MN")
        text = gn.generate(cfg, CONFIG.name)["demo_inv_1.spice"]
        self.assertIn("other_n", text)
        self.assertIn("\nMN0 ", text)
        self.assertNotIn("demo_nmos", text)


class ParserTest(unittest.TestCase):
    def test_rejects_mixed_operators(self):
        for bad in ("A^B*C", "A+B^C", "A*B+C", "!(A*B+C)"):
            with self.assertRaises(ValueError, msg=bad):
                gn.parse(bad)
        self.assertEqual(gn.evaluate(gn.parse("A^B^C"), {"A": 1, "B": 1, "C": 1}), 1)

    def test_rejects_empty_and_malformed(self):
        for bad in ("", "   ", "A*", "(A*B", "A B", "*A"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                gn.parse(bad)

    def test_single_input_cell(self):
        cfg = copy.deepcopy(CFG)
        cfg["cells"] = [c for c in cfg["cells"] if c["name"] == "demo_inv_1"]
        self.assertEqual(len(gn.generate(cfg)), 1)

    def test_invalid_config_rejected(self):
        cfg = copy.deepcopy(CFG)
        cfg["cells"][0]["outputs"] = {"Y": "!Z"}
        with self.assertRaises(ValueError):
            gn.generate(cfg)
        cfg = copy.deepcopy(CFG)
        del cfg["process"]["unit_n_nm"]
        with self.assertRaises(ValueError):
            gn.generate(cfg)
        cfg = copy.deepcopy(CFG)
        cfg["cells"][0]["outputs"] = {"Y": ""}
        with self.assertRaises(ValueError):
            gn.generate(cfg)


class PinNameAndGridTest(unittest.TestCase):
    def _cfg(self, inputs, outputs, **proc):
        cfg = copy.deepcopy(CFG)
        cfg["process"].update(proc)
        cfg["cells"] = [{"name": "t", "family": "t", "drive": 1, "inputs": inputs, "outputs": outputs}]
        return cfg

    def test_reserved_pin_names_rejected(self):
        bad = [(["n1"], {"Y": "!n1"}), (["A_b"], {"Y": "!A_b"}), (["A"], {"Y_i": "!A"}),
               (["A"], {"Y_b": "!A"}), (["VDD"], {"Y": "!VDD"}), (["A"], {"VSS": "!A"}),
               (["A", "B"], {"A": "!B"}), (["n12"], {"Y": "!n12"})]
        for ins, outs in bad:
            with self.assertRaises(ValueError, msg=(ins, outs)) as cm:
                gn.generate(self._cfg(ins, outs))
            self.assertIn("'t'", str(cm.exception))

    def test_legal_pin_names_accepted(self):
        for ins, outs in [(["n"], {"Y": "!n"}), (["nA"], {"Y": "!nA"}), (["A_B"], {"Y": "!A_B"}),
                          (["A1", "S"], {"X": "A1*S"})]:
            gn.generate(self._cfg(ins, outs))

    def test_grid_nm(self):
        with self.assertRaises(ValueError):
            gn.generate(self._cfg(["A"], {"Y": "!A"}, unit_n_nm=505))
        gn.generate(self._cfg(["A"], {"Y": "!A"}, unit_n_nm=505, grid_nm=5))
        for bad in (0, -5, 2.5, True, "5"):
            with self.assertRaises(ValueError, msg=bad):
                gn.generate(self._cfg(["A"], {"Y": "!A"}, grid_nm=bad))

    def test_grid_drives_finger_split(self):
        c = gn.Cell("t", dict(PROC, grid_nm=5, finger_max_n=300))
        c.add("n", "a", "b", "c", 505)  # only 101 fingers of 5 nm fit the 5 nm grid under the cap
        self.assertEqual(c.devices[0][5], 101)
        with self.assertRaises(ValueError):
            gn.Cell("t", dict(PROC, finger_max_n=300)).add("n", "a", "b", "c", 505)


class DeterminismAndCheckTest(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(DESIGN / "gen_netlists.py"), *args], capture_output=True, text=True)

    def test_two_runs_identical(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            self.assertEqual(self.run_cli("--config", str(CONFIG), "--out", a).returncode, 0)
            self.assertEqual(self.run_cli("--config", str(CONFIG), "--out", b).returncode, 0)
            fa = {p.name: p.read_bytes() for p in pathlib.Path(a).glob("*.spice")}
            fb = {p.name: p.read_bytes() for p in pathlib.Path(b).glob("*.spice")}
            self.assertEqual(fa, fb)
            self.assertEqual(len(fa), len(CFG["cells"]))

    def test_check_detects_stale_missing_and_stray(self):
        with tempfile.TemporaryDirectory() as td:
            out = pathlib.Path(td)
            self.assertEqual(self.run_cli("--config", str(CONFIG), "--out", td).returncode, 0)
            self.assertEqual(self.run_cli("--config", str(CONFIG), "--out", td, "--check").returncode, 0)
            (out / "demo_inv_1.spice").write_text("x\n")
            (out / "demo_inv_2.spice").unlink()
            (out / "demo_extra_1.spice").write_text("x\n")
            r = self.run_cli("--config", str(CONFIG), "--out", td, "--check")
            self.assertEqual(r.returncode, 1)
            for word in ("stale", "missing", "stray"):
                self.assertIn(word, r.stderr)

    def test_check_fails_on_empty_dir(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(self.run_cli("--config", str(CONFIG), "--out", td, "--check").returncode, 1)

    def test_bad_config_exit_2(self):
        with tempfile.TemporaryDirectory() as td:
            bad = pathlib.Path(td) / "bad.json"
            bad.write_text("{}")
            self.assertEqual(self.run_cli("--config", str(bad), "--out", td).returncode, 2)

    def _run_bad(self, **proc_over):
        cfg = copy.deepcopy(CFG)
        cfg["process"].update(proc_over)
        with tempfile.TemporaryDirectory() as td:
            c = pathlib.Path(td) / "c.json"
            c.write_text(json.dumps(cfg))
            return subprocess.run([sys.executable, str(DESIGN / "gen_netlists.py"), "--config", str(c), "--out", td],
                                  capture_output=True, text=True, timeout=30)

    def test_off_grid_unit_width_exit_2(self):
        self.assertEqual(self._run_bad(unit_n_nm=505).returncode, 2)
        self.assertEqual(self._run_bad(unit_p_nm=805).returncode, 2)

    def test_finger_cap_below_grid_exit_2(self):
        self.assertEqual(self._run_bad(finger_max_n=5).returncode, 2)


if __name__ == "__main__":
    unittest.main()
