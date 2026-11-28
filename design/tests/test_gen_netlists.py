"""Tests for design/gen_netlists.py against the demo config.

The generated netlists are parsed independently of the generator and checked
with a switch-level truth-table simulation. Models are the demo config's
placeholder names, not any PDK.
"""
import contextlib
import copy
import io
import itertools
import json
import pathlib
import sys
import tempfile
import types
import unittest

DESIGN = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESIGN))
import gen_netlists as gn  # noqa: E402

CONFIG = DESIGN / "example_config.json"
CFG = json.loads(CONFIG.read_text())
PROC = CFG["process"]
FILES = gn.generate(CFG, CONFIG.name)


def one_cell_cfg(inputs, outputs, **proc):
    cfg = copy.deepcopy(CFG)
    cfg["process"].update(proc)
    cfg["cells"] = [{"name": "t", "family": "t", "drive": 1, "inputs": inputs, "outputs": outputs}]
    return cfg


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
        for cell in CFG["cells"]:
            ports, devs = parse_netlist(FILES[f"{cell['name']}.spice"])
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
        _, devs = parse_netlist(FILES["demo_buf_2.spice"])
        self.assertEqual(len(devs), 4)  # stage inverter + output inverter

    def test_xor_shares_complement_literals(self):
        _, devs = parse_netlist(FILES["demo_xor2_1.spice"])
        inverters = [d for d in devs if d[2] in ("A", "B") and d[1].endswith("_b")]
        self.assertEqual(len(inverters), 4)  # one n+p unit inverter each for A and B, not per use

    def test_four_input_stack_compensation(self):
        _, devs = parse_netlist(FILES["demo_nand4_1.spice"])
        nw = {int(p["w"][:-1]) for m, *_, p in devs if m == PROC["nmos_model"]}
        self.assertEqual(nw, {PROC["unit_n_nm"] * 4})

    def test_finger_caps_respected(self):
        for text in FILES.values():
            for model, _, _, _, prm in parse_netlist(text)[1]:
                w, ng = int(prm["w"][:-1]), int(prm["ng"])
                cap = PROC["finger_max_n"] if model == PROC["nmos_model"] else PROC["finger_max_p"]
                self.assertLessEqual(w / ng, cap)
                self.assertEqual(w % ng, 0)

    def test_gate_shared_devices_share_finger_count(self):
        # a layout gate column crosses both pull networks, so every device on
        # one gate net is drawn with the same finger count (the larger); the
        # netlist must state that same decomposition, or resimulating it
        # against the extracted layout compares a different device than the
        # layout drew and folds the representation into the parasitic delta
        _, devs = parse_netlist(FILES["demo_inv_2.spice"])
        per_gate = {}
        for model, _, gate, _, prm in devs:
            per_gate.setdefault(gate, set()).add(int(prm["ng"]))
        self.assertEqual(per_gate, {"A": {2}})

    def test_gate_shared_fold_keeps_total_width(self):
        _, devs = parse_netlist(FILES["demo_inv_2.spice"])
        widths = {(m, int(p["w"][:-1])) for m, _, _, _, p in devs}
        self.assertEqual(widths, {(PROC["nmos_model"], 2 * PROC["unit_n_nm"]),
                                  (PROC["pmos_model"], 2 * PROC["unit_p_nm"])})

    def test_gate_shared_unfoldable_width_rejected(self):
        # 510 nm has no equal 2-finger split on the 10 nm grid, so a gate
        # whose other device folds to 2 fingers is impossible to draw, not
        # silently misstated
        cfg = one_cell_cfg(["A"], {"Y": "!A"}, unit_n_nm=510, unit_p_nm=1300)
        with self.assertRaises(ValueError) as cm:
            gn.generate(cfg)
        self.assertIn("2-finger", str(cm.exception))

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
        self.assertEqual(len(gn.generate(one_cell_cfg(["A"], {"Y": "!A"}))), 1)

    def bad(self, mutate):
        cfg = copy.deepcopy(CFG)
        mutate(cfg)
        with self.assertRaises(ValueError):
            gn.generate(cfg)

    def test_invalid_config_rejected(self):
        self.bad(lambda c: c["cells"][0].update(outputs={"Y": "!Z"}))
        self.bad(lambda c: c["process"].pop("unit_n_nm"))
        self.bad(lambda c: c["cells"][0].update(outputs={"Y": ""}))

    def test_schema_version_must_be_1(self):
        self.bad(lambda c: c.update(schema_version=99))
        self.bad(lambda c: c.pop("schema_version"))
        self.bad(lambda c: c.update(schema_version=True))


class PinNameAndGridTest(unittest.TestCase):
    def test_reserved_pin_names_rejected(self):
        bad = [(["n1"], {"Y": "!n1"}), (["A_b"], {"Y": "!A_b"}), (["A"], {"Y_i": "!A"}),
               (["A"], {"Y_b": "!A"}), (["VDD"], {"Y": "!VDD"}), (["A"], {"VSS": "!A"}),
               (["A", "B"], {"A": "!B"}), (["n12"], {"Y": "!n12"})]
        for ins, outs in bad:
            with self.assertRaises(ValueError, msg=(ins, outs)) as cm:
                gn.generate(one_cell_cfg(ins, outs))
            self.assertIn("'t'", str(cm.exception))

    def test_legal_pin_names_accepted(self):
        for ins, outs in [(["n"], {"Y": "!n"}), (["nA"], {"Y": "!nA"}), (["A_B"], {"Y": "!A_B"}),
                          (["A1", "S"], {"X": "A1*S"})]:
            gn.generate(one_cell_cfg(ins, outs))

    def test_grid_nm(self):
        with self.assertRaises(ValueError):
            gn.generate(one_cell_cfg(["A"], {"Y": "!A"}, unit_n_nm=505))
        gn.generate(one_cell_cfg(["A"], {"Y": "!A"}, unit_n_nm=505, grid_nm=5))
        for bad in (0, -5, 2.5, True, "5"):
            with self.assertRaises(ValueError, msg=bad):
                gn.generate(one_cell_cfg(["A"], {"Y": "!A"}, grid_nm=bad))

    def test_grid_drives_finger_split(self):
        c = gn.Cell("t", dict(PROC, grid_nm=5, finger_max_n=300))
        c.add("n", "a", "b", "c", 505)  # only 101 fingers of 5 nm fit the 5 nm grid under the cap
        self.assertEqual(c.devices[0][5], 101)
        with self.assertRaises(ValueError):
            gn.Cell("t", dict(PROC, finger_max_n=300)).add("n", "a", "b", "c", 505)


class DeterminismAndCheckTest(unittest.TestCase):
    def run_cli(self, *args):
        """The CLI in-process: a .returncode / .stdout / .stderr result."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = gn.main(list(args))
        return types.SimpleNamespace(returncode=rc, stdout=out.getvalue(), stderr=err.getvalue())

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

    def test_check_rejects_crlf_rewrite_and_leaves_input_intact(self):
        # a CRLF rewrite changes no line content, so the check must compare
        # the exact bytes the generator writes, not normalized text (#196)
        with tempfile.TemporaryDirectory() as td:
            out = pathlib.Path(td)
            self.assertEqual(self.run_cli("--config", str(CONFIG), "--out", td).returncode, 0)
            spice = out / "demo_inv_1.spice"
            crlf = spice.read_bytes().replace(b"\n", b"\r\n")
            spice.write_bytes(crlf)
            r = self.run_cli("--config", str(CONFIG), "--out", td, "--check")
            self.assertEqual(r.returncode, 1)
            self.assertIn("stale", r.stderr)
            self.assertEqual(spice.read_bytes(), crlf)  # --check writes nothing

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
            return self.run_cli("--config", str(c), "--out", td)

    def test_off_grid_unit_width_exit_2(self):
        self.assertEqual(self._run_bad(unit_n_nm=505).returncode, 2)
        self.assertEqual(self._run_bad(unit_p_nm=805).returncode, 2)

    def test_finger_cap_below_grid_exit_2(self):
        self.assertEqual(self._run_bad(finger_max_n=5).returncode, 2)


if __name__ == "__main__":
    unittest.main()
