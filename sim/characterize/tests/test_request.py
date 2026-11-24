import json
import tempfile
import unittest
from pathlib import Path

from sim.characterize import runner
from sim.harness.corners import CHAR_CORNER_PVT
from sim.harness.evidence import CharacterizationExtensions
from sim.characterize.request import (DEFAULT_CORNER, CellSpec, RequestError, build_library_request,
                                      cells_from_config, library_view_name)

INV = CellSpec("sg13g2_inv_1", inputs=("A",), outputs={"Y": "!A"}, netlist="/nl/sg13g2_inv_1.spice")


def fake_response(cell="sg13g2_inv_1", arcs=True):
    tbl = {"values": [[1.0]]}
    arc = {"related_pin": "A", "output_pin": "Y", "timing_sense": "negative_unate", "side_inputs": {},
           **{t: tbl for t in runner.TABLES}}
    return {"corner": {"name": "tt"}, "grid": {"input_transition_ns": [0.1], "output_load_pf": [0.01]},
            "cells": [{"cell": {"name": cell}, "arcs": [arc] if arcs else [], "leakage": None}],
            "provenance": {"klt_version": "x"}}


class RecordTests(unittest.TestCase):
    def test_missing_cell_or_arc_fails_loudly(self):
        with self.assertRaises(runner.CharacterizeFailed):
            runner.extract_arcs(fake_response(cell="other"), INV)
        with self.assertRaises(runner.CharacterizeFailed):
            runner.extract_arcs(fake_response(arcs=False), INV)

    def test_driver_record_validates(self):
        data = runner.build_record_data(fake_response(), INV, "local")
        exts = runner.evidence_for(data)
        self.assertEqual(len(exts), 1)  # 1 arc x 1 slew x 1 load
        self.assertIsInstance(exts[0], CharacterizationExtensions)
        exts[0].validate()
        self.assertEqual((exts[0].corner, exts[0].energy_pj), ("tt", 2.0))

    def test_non_characterization_corner_rejected(self):
        resp = fake_response()
        resp["corner"] = {"name": "tt_1p20v_25c"}
        with self.assertRaises(Exception):
            runner.evidence_for(runner.build_record_data(resp, INV, "local"))

    def test_rerun_appends(self):
        data = runner.build_record_data(fake_response(), INV, "local")
        with tempfile.TemporaryDirectory() as d:
            a = runner.record(data, Path(d))
            b = runner.record(data, Path(d))
            self.assertNotEqual(a, b)
            self.assertEqual(len(list(Path(d).glob("*.md"))), 2)
            self.assertIn("0.1", a.read_text())


if __name__ == "__main__":
    unittest.main()


REPO = Path(__file__).resolve().parents[3]
CONFIG = REPO / "layout" / "example_config.json"


class LibraryRequestTests(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads(CONFIG.read_text())
        self.cells = cells_from_config(CONFIG, "/nl")
        self.req = build_library_request(self.cells, DEFAULT_CORNER, "/pdk")

    def test_cells_exactly_the_config_and_not_demo(self):
        names = [c["name"] for c in self.req["cells"]]
        self.assertEqual(names, [c["name"] for c in self.cfg["cells"]])
        self.assertNotIn("cell", self.req)
        for c in self.req["cells"]:
            self.assertEqual(Path(c["netlist"]).parent, Path("/nl"))
            self.assertNotIn("demo", c["name"])

    def test_pins_and_functions_come_from_config(self):
        by = {c["name"]: c for c in self.req["cells"]}
        for cfg_cell in self.cfg["cells"]:
            pins = by[cfg_cell["name"]]["pins"]
            self.assertEqual([p["name"] for p in pins if p["direction"] == "input"], cfg_cell["inputs"])
            self.assertEqual({p["name"]: p["function"] for p in pins if p["direction"] == "output"},
                             cfg_cell["outputs"])
        nand = by["sg13g2_nand2_1"]["pins"]
        self.assertEqual([p["name"] for p in nand if p["direction"] == "input"], ["A", "B"])
        inv = by["sg13g2_inv_1"]["pins"]
        self.assertEqual([p["name"] for p in inv if p["direction"] == "input"], ["A"])

    def test_corner_models_and_library_name(self):
        self.assertEqual(self.req["corner"]["supply_v"], 1.2)
        self.assertEqual(self.req["corner"]["temperature_c"], 25.0)
        self.assertEqual(self.req["corner"]["process"], "mos_tt")
        self.assertTrue(self.req["models"]["lib"].endswith("cornerMOSlv.lib"))
        self.assertEqual(self.req["library"]["name"], "sg13g2_stdcells_tt_1p20v_25c")
        self.assertEqual(self.req["cells"][0]["power_pins"], {"vdd": "VDD", "gnd": "VSS"})
        json.dumps(self.req)

    def test_library_name_is_derived_from_the_corner(self):
        # The view name encodes PVT (a library is a generator, not a block), so
        # the default is derived from CHAR_CORNER_PVT -- the request's library
        # name follows the corner it was built for, at every corner.
        for name in CHAR_CORNER_PVT:
            req = build_library_request(self.cells, name, "/pdk")
            self.assertEqual(req["library"]["name"], library_view_name(name), name)
        # The tt derivation reproduces the committed view's name byte for byte.
        self.assertEqual(library_view_name("tt"), "sg13g2_stdcells_tt_1p20v_25c")
        self.assertEqual(library_view_name("ff"), "sg13g2_stdcells_ff_1p32v_m40c")
        self.assertEqual(library_view_name("ss"), "sg13g2_stdcells_ss_1p08v_125c")
        with self.assertRaises(RequestError):
            library_view_name("fs")

    def test_rejects_empty_and_duplicate(self):
        with self.assertRaises(RequestError):
            build_library_request([], DEFAULT_CORNER, "/pdk")
        with self.assertRaises(RequestError):
            build_library_request(self.cells[:1] * 2, DEFAULT_CORNER, "/pdk")

    def test_osdi_preload_is_the_module_the_models_declare(self):
        # The PDK's `.model ... psp103va` cards bind to psp103.osdi; psp103_nqs.osdi
        # registers a different module name and leaves them "unknown model type"
        # (ngspice_fatal on the first real run).
        self.assertEqual(self.req["options"]["osdi_preload"],
                         ["/pdk/libs.tech/ngspice/osdi/psp103.osdi"])
        self.assertIs(self.req["options"]["keep_artifacts"], False)

    def test_relative_netlist_resolves_against_pdk(self):
        rel = CellSpec("c", inputs=("A",), outputs={"Y": "!A"}, netlist="libs.ref/c.spice")
        entry = build_library_request([rel], DEFAULT_CORNER, "/pdk")["cells"][0]
        self.assertEqual(entry["netlist"], "/pdk/libs.ref/c.spice")

    def test_corner_comes_from_harness(self):
        for name, (process, vdd, temp) in CHAR_CORNER_PVT.items():
            c = build_library_request(self.cells, name, "/pdk")["corner"]
            self.assertEqual((c["process"], c["supply_v"], c["temperature_c"]),
                             (process, vdd, temp))
        with self.assertRaises(RequestError):
            build_library_request(self.cells, "fs", "/pdk")

    def test_bad_axes(self):
        with self.assertRaises(RequestError):
            build_library_request(self.cells, DEFAULT_CORNER, "/pdk", slews_ns=[0.1, 0.1])
        with self.assertRaises(RequestError):
            build_library_request(self.cells, DEFAULT_CORNER, "/pdk", loads_pf=[])


class LibraryRecordTests(unittest.TestCase):
    def test_multi_cell_record_validates_and_picks_each_cells_leakage(self):
        a = runner.build_record_data(fake_response("sg13g2_inv_1"), INV, "local")
        resp = fake_response("sg13g2_inv_1")
        resp["cells"].append({**fake_response("other")["cells"][0], "leakage": "x"})
        self.assertIsNone(runner.build_record_data(resp, INV, "local")["leakage"])
        with tempfile.TemporaryDirectory() as d:
            path = runner.record({**a, "cells": [a, a]}, records_dir=Path(d))
            self.assertIn('"cells"', path.read_text())
