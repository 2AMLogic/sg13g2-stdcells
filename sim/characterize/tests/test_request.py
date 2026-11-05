import json
import tempfile
import unittest
from pathlib import Path

from sim.characterize import runner
from sim.harness.corners import CHAR_CORNER_PVT
from sim.harness.evidence import CharacterizationExtensions
from sim.characterize.request import DEFAULT_CORNER, SG13G2_INV_1, RequestError, build_request


class RequestTests(unittest.TestCase):
    def test_shape(self):
        r = build_request(SG13G2_INV_1, DEFAULT_CORNER, "/pdk")
        self.assertEqual(r["cell"]["pins"][1], {"name": "Y", "direction": "output", "function": "!A"})
        self.assertEqual(r["corner"]["supply_v"], 1.2)
        self.assertEqual(r["corner"]["process"], "mos_tt")
        self.assertTrue(r["cell"]["netlist"].startswith("/pdk/libs.ref"))
        self.assertTrue(r["options"]["osdi_preload"][0].startswith("/pdk/"))
        json.dumps(r)

    def test_corner_comes_from_harness(self):
        for name, (vdd, temp) in CHAR_CORNER_PVT.items():
            c = build_request(SG13G2_INV_1, name, "/pdk")["corner"]
            self.assertEqual((c["supply_v"], c["temperature_c"]), (vdd, temp))
        with self.assertRaises(RequestError):
            build_request(SG13G2_INV_1, "fs", "/pdk")

    def test_bad_axes(self):
        with self.assertRaises(RequestError):
            build_request(SG13G2_INV_1, DEFAULT_CORNER, "/pdk", slews_ns=[0.1, 0.1])
        with self.assertRaises(RequestError):
            build_request(SG13G2_INV_1, DEFAULT_CORNER, "/pdk", loads_pf=[])


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
            runner.extract_arcs(fake_response(cell="other"), SG13G2_INV_1)
        with self.assertRaises(runner.CharacterizeFailed):
            runner.extract_arcs(fake_response(arcs=False), SG13G2_INV_1)

    def test_driver_record_validates(self):
        data = runner.build_record_data(fake_response(), SG13G2_INV_1, "local")
        exts = runner.evidence_for(data)
        self.assertEqual(len(exts), 1)  # 1 arc x 1 slew x 1 load
        self.assertIsInstance(exts[0], CharacterizationExtensions)
        exts[0].validate()
        self.assertEqual((exts[0].corner, exts[0].energy_pj), ("tt", 2.0))

    def test_non_characterization_corner_rejected(self):
        resp = fake_response()
        resp["corner"] = {"name": "tt_1p20v_25c"}
        with self.assertRaises(Exception):
            runner.evidence_for(runner.build_record_data(resp, SG13G2_INV_1, "local"))

    def test_rerun_appends(self):
        data = runner.build_record_data(fake_response(), SG13G2_INV_1, "local")
        with tempfile.TemporaryDirectory() as d:
            a = runner.record(data, Path(d))
            b = runner.record(data, Path(d))
            self.assertNotEqual(a, b)
            self.assertEqual(len(list(Path(d).glob("*.md"))), 2)
            self.assertIn("0.1", a.read_text())


if __name__ == "__main__":
    unittest.main()
