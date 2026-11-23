"""Tests for layout/run_lvs.py and layout/toolchain_pin.py pure helpers, plus
the shape of the LVS evidence committed under layout/lvs/."""
import json
import pathlib
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

LAYOUT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAYOUT))
import run_lvs  # noqa: E402
import toolchain_pin  # noqa: E402

CONFIG = LAYOUT / "example_config.json"

HELP = """usage: klt
positional arguments:
  <command>
    layers              enumerate layers
    drc                 run a headless DRC deck
    lvs                 compare netlists
"""


class ToolchainPin(unittest.TestCase):
    def test_advertised(self):
        self.assertEqual(toolchain_pin.advertised_commands(HELP), {"layers", "drc", "lvs"})

    def test_missing_names_command(self):
        self.assertEqual(toolchain_pin.missing_commands(["drc", "extract", "lvs"], HELP),
                         ["extract"])

    def test_pin_lists_lvs_and_extract(self):
        self.assertTrue({"drc", "extract", "lvs"} <= set(toolchain_pin.required_commands()))


class Request(unittest.TestCase):
    def test_build_request_multifinger_cell(self):
        q = run_lvs.build_request("sg13g2_inv_4", "layout/gds", "layout/lvs/netlists")
        self.assertEqual(q["layout"]["top"], "sg13g2_inv_4")
        self.assertTrue(q["layout"]["file"].endswith("layout/gds/sg13g2_inv_4.gds"))
        self.assertTrue(q["reference"]["netlist"].endswith("netlists/sg13g2_inv_4.spice"))
        self.assertEqual(q["reference"]["form"], "subckt-call")
        # the generator folds a device into F parallel fingers, so extraction
        # sees F transistors where the reference netlist carries one with ng=F
        self.assertIs(q["options"]["combine_devices"], True)

    def test_cells_come_from_example_config(self):
        self.assertEqual(run_lvs.cell_names(LAYOUT / "example_config.json"),
                         ["sg13g2_inv_1", "sg13g2_inv_2", "sg13g2_inv_4", "sg13g2_nand2_1"])

    def test_power_ok_and_summary(self):
        rep = {"status": "mismatch", "error_count": 3,
               "power_connectivity": {"status": "unchecked"}}
        self.assertTrue(run_lvs.power_ok(rep))
        self.assertFalse(run_lvs.power_ok({"power_connectivity": {"status": "mismatch"}}))
        self.assertIn("mismatch", run_lvs.summarize("c", rep))


class RecordedEvidence(unittest.TestCase):
    """The committed reports are the claim; assert what they actually say."""

    def reports(self):
        for cell in run_lvs.cell_names(LAYOUT / "example_config.json"):
            yield cell, json.loads((LAYOUT / "lvs" / f"{cell}.json").read_text())

    def test_every_cell_matches_with_its_bodies_verified(self):
        seen = 0
        for cell, rep in self.reports():
            self.assertEqual(rep["status"], "match", cell)
            self.assertEqual(rep["error_count"], 0, cell)
            # the discriminating evidence that the taps are real -- a tapless
            # layout DRCs clean too, but grades body_verification 'unverified'
            self.assertEqual(rep["body_verification"]["status"], "verified", cell)
            self.assertNotIn("device.body_unverified", rep.get("category_counts", {}), cell)
            self.assertIs(rep["options"]["combine_devices"], True, cell)
            seen += 1
        self.assertEqual(seen, 4)

    def test_device_and_net_counts_pair_up(self):
        for cell, rep in self.reports():
            for what in ("devices", "nets"):
                c = rep["counts"][what]
                self.assertEqual(c["layout"], c["reference"], f"{cell} {what}")
                self.assertEqual(c["matched"], c["reference"], f"{cell} {what}")


class DoCheckTest(unittest.TestCase):
    """--check against a scratch copy of the reference netlists.

    The netlist leg runs the real generator --check (stdlib Python, no klt);
    only the per-report `klt lvs --check` call (check_report) is patched, so
    every matrix case below exercises the same freshness check CI runs.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = pathlib.Path(self._tmp.name) / "lvs"
        self.netlists = self.out / "netlists"
        self.cells = run_lvs.cell_names(CONFIG)
        r = run_lvs.gen_netlists(CONFIG, self.netlists)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.out.mkdir(parents=True, exist_ok=True)
        for cell in self.cells:
            (self.out / f"{cell}.json").write_text("{}")

    def tearDown(self):
        self._tmp.cleanup()

    def snapshot(self):
        return {p.name: p.read_bytes()
                for d in (self.netlists, self.out) for p in sorted(d.iterdir()) if p.is_file()}

    def do_check(self, report_exit=0):
        fake = types.SimpleNamespace(returncode=report_exit, stdout="stale", stderr="")
        with mock.patch.object(run_lvs, "check_report", return_value=fake) as rep:
            rc = run_lvs.do_check(self.cells, self.out, self.netlists, str(CONFIG))
        present = [c for c in self.cells if (self.out / f"{c}.json").exists()]
        self.assertEqual(rep.call_count, len(present))  # every present report re-checked
        return rc

    def test_fresh_netlists_and_reports_pass(self):
        self.assertEqual(self.do_check(report_exit=0), 0)

    def test_crlf_netlist_rejected_and_left_intact(self):
        spice = self.netlists / f"{self.cells[0]}.spice"
        crlf = spice.read_bytes().replace(b"\n", b"\r\n")
        spice.write_bytes(crlf)
        before = self.snapshot()
        self.assertEqual(self.do_check(), 1)
        self.assertEqual(self.snapshot(), before)

    def test_missing_netlist_rejected(self):
        (self.netlists / f"{self.cells[0]}.spice").unlink()
        self.assertEqual(self.do_check(), 1)

    def test_edited_netlist_rejected(self):
        (self.netlists / f"{self.cells[0]}.spice").write_text("x\n")
        self.assertEqual(self.do_check(), 1)

    def test_stray_netlist_rejected(self):
        # a .spice from a retired cell must not outlive the freshness check
        (self.netlists / "sg13g2_retired_1.spice").write_text("x\n")
        self.assertEqual(self.do_check(), 1)

    def test_stale_report_with_fresh_netlists_rejected(self):
        self.assertEqual(self.do_check(report_exit=1), 1)

    def test_missing_report_rejected(self):
        (self.out / f"{self.cells[0]}.json").unlink()
        self.assertEqual(self.do_check(), 1)

    def test_stray_report_rejected(self):
        (self.out / "sg13g2_retired_1.json").write_text("{}")
        self.assertEqual(self.do_check(), 1)

    def test_netlist_and_report_drift_reported_in_one_run(self):
        (self.netlists / "sg13g2_retired_1.spice").write_text("x\n")
        (self.out / f"{self.cells[0]}.json").unlink()
        self.assertEqual(self.do_check(report_exit=1), 1)


if __name__ == "__main__":
    unittest.main()
