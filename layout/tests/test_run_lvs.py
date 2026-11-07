"""Tests for layout/run_lvs.py and layout/toolchain_pin.py pure helpers."""
import pathlib
import sys
import unittest

LAYOUT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAYOUT))
import run_lvs  # noqa: E402
import toolchain_pin  # noqa: E402

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

    def test_cells_come_from_example_config(self):
        self.assertEqual(run_lvs.cell_names(LAYOUT / "example_config.json"),
                         ["sg13g2_inv_1", "sg13g2_inv_2", "sg13g2_inv_4", "sg13g2_nand2_1"])

    def test_power_ok_and_summary(self):
        rep = {"status": "mismatch", "error_count": 3,
               "power_connectivity": {"status": "unchecked"}}
        self.assertTrue(run_lvs.power_ok(rep))
        self.assertFalse(run_lvs.power_ok({"power_connectivity": {"status": "mismatch"}}))
        self.assertIn("mismatch", run_lvs.summarize("c", rep))


if __name__ == "__main__":
    unittest.main()
