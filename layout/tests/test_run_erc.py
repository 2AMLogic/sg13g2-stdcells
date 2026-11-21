"""Tests for layout/run_erc.py and layout/toolchain_pin.py pure helpers, plus
the shape of the ERC evidence committed under layout/erc/."""
import json
import pathlib
import sys
import unittest

LAYOUT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAYOUT))
import run_erc  # noqa: E402
import toolchain_pin  # noqa: E402

HELP = """usage: klt
positional arguments:
  <command>
    layers              enumerate layers
    drc                 run a headless DRC deck
    lvs                 compare netlists
"""

HELP_WITH_ERC = """usage: klt
positional arguments:
  <command>
    layers              enumerate layers
    drc                 run a headless DRC deck
    erc                 supply/tie connectivity checks
    lvs                 compare netlists
"""


class ToolchainPin(unittest.TestCase):
    def test_pin_lists_erc(self):
        self.assertIn("erc", toolchain_pin.required_commands())

    def test_missing_names_erc_command(self):
        """The runner fails loudly when klt lacks `erc` (issue #179): the
        shared check names it, so a missing subcommand is never skipped."""
        self.assertEqual(toolchain_pin.missing_commands(["drc", "erc", "lvs"], HELP),
                         ["erc"])
        self.assertEqual(toolchain_pin.missing_commands(["drc", "erc", "lvs"], HELP_WITH_ERC),
                         [])


class Command(unittest.TestCase):
    def test_build_command_names_top_and_spec(self):
        cmd = run_erc.build_command("layout/gds/sg13g2_inv_1.gds",
                                    "layout/erc-spec.json", "sg13g2_inv_1")
        self.assertEqual(cmd, ["klt", "erc", "layout/gds/sg13g2_inv_1.gds",
                               "layout/erc-spec.json", "--deck", "sg13g2",
                               "--format", "json", "--top", "sg13g2_inv_1"])

    def test_build_command_without_top(self):
        """Negative-control streams carry one top cell, so no --top is passed."""
        cmd = run_erc.build_command("layout/erc/controls/missing-tie-nwell-inv1.gds",
                                    "layout/erc-spec.json", None)
        self.assertNotIn("--top", cmd)

    def test_cells_come_from_example_config(self):
        self.assertEqual(run_erc.cell_names(LAYOUT / "example_config.json"),
                         ["sg13g2_inv_1", "sg13g2_inv_2", "sg13g2_inv_4", "sg13g2_nand2_1"])


class Grading(unittest.TestCase):
    CLEAN = {"erc_status": "clean", "erc_finding_count": 0,
             "nets": [{"name": "VDD", "matched_islands": 1, "expected_islands": 1},
                      {"name": "VSS", "matched_islands": 1, "expected_islands": 1}],
             "erc_coverage": {"skipped": []}}
    MISSING_TIE = {"rule": "erc.missing_tie", "net": "VDD", "layer": "nwell_tap"}

    def test_cell_ok(self):
        self.assertTrue(run_erc.cell_ok(self.CLEAN))

    def test_cell_ok_rejects_each_failure_mode(self):
        def vary(**over):
            rep = json.loads(json.dumps(self.CLEAN))
            for k, v in over.items():
                if k.endswith(".*"):
                    rep[k[:-2]] = v
                else:
                    rep[k] = v
            return rep
        self.assertFalse(run_erc.cell_ok(vary(erc_status="clean_partial")))
        self.assertFalse(run_erc.cell_ok(vary(erc_finding_count=1,
                                              erc_findings=[self.MISSING_TIE])))
        self.assertFalse(run_erc.cell_ok(vary(**{"nets.*": [
            {"name": "VDD", "matched_islands": 2, "expected_islands": 1},
            {"name": "VSS", "matched_islands": 1, "expected_islands": 1}]})))
        self.assertFalse(run_erc.cell_ok(vary(**{"erc_coverage.*": {"skipped": [
            {"id": "erc.missing_tie", "reason": "degenerate_tap_declaration"}]}})))

    def test_control_ok_requires_missing_tie(self):
        self.assertFalse(run_erc.control_ok({"erc_findings": []}))
        self.assertTrue(run_erc.control_ok({"erc_findings": [self.MISSING_TIE]}))
        self.assertTrue(run_erc.control_ok(
            {"erc_findings": [{"rule": "erc.floating_gate"}, self.MISSING_TIE]}))


class Spec(unittest.TestCase):
    def test_spec_declares_supplies_and_both_ties(self):
        """T1 item 11 analog needs every supply kind:supply and the two tap
        ties the generator draws, or `klt signoff` renders the item
        supply_spec_incomplete."""
        spec = json.loads((LAYOUT / "erc-spec.json").read_text())
        self.assertEqual([n["name"] for n in spec["nets"] if n["kind"] == "supply"],
                         ["VDD", "VSS"])
        self.assertEqual([t["name"] for t in spec["ties"]],
                         ["nwell_tap", "substrate_tap"])
        self.assertEqual([t["net"] for t in spec["ties"]], ["VDD", "VSS"])
        # a bare activ tap_layer would match every source/drain diffusion and
        # grade degenerate; both ties narrow with the real implant boolean
        for tie in spec["ties"]:
            self.assertEqual(tie["tap_layer"], "1/0")
            self.assertTrue(tie["tap_requires"], tie["name"])
        self.assertEqual(spec["ties"][0]["well_layer"], "31/0")
        self.assertIsNone(spec["ties"][1]["well_layer"])


class RecordedEvidence(unittest.TestCase):
    """The committed reports are the claim; assert what they actually say."""

    def reports(self):
        for cell in run_erc.cell_names(LAYOUT / "example_config.json"):
            yield cell, json.loads((LAYOUT / "erc" / f"{cell}.json").read_text())

    def test_every_cell_clean_one_island_per_supply_no_skipped_tie(self):
        seen = 0
        for cell, rep in self.reports():
            self.assertTrue(run_erc.cell_ok(rep), cell)
            self.assertEqual(rep["erc_status"], "clean", cell)
            self.assertEqual(run_erc.supply_islands(rep),
                             [("VDD", 1, 1), ("VSS", 1, 1)], cell)
            self.assertEqual(run_erc.missing_ties(rep), [], cell)
            self.assertEqual(run_erc.degenerate_ties(rep), [], cell)
            # the spec committed beside the reports is the one they ran with
            import hashlib
            digest = hashlib.sha256((LAYOUT / "erc-spec.json").read_bytes()).hexdigest()
            self.assertEqual(rep["provenance"]["spec"]["content_hash"],
                             f"sha256:{digest}", cell)
            seen += 1
        self.assertEqual(seen, 4)

    def test_negative_control_shows_missing_tie(self):
        rep = json.loads((LAYOUT / "erc" / "controls" / "missing-tie-nwell-inv1.json").read_text())
        findings = run_erc.missing_ties(rep)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["net"], "VDD")
        self.assertEqual(findings[0]["layer"], "nwell_tap")

    def test_control_streams_present_for_the_runner(self):
        """run_erc fails loudly with no control streams; the committed recipe
        (layout/gen_controls.py) must keep exactly the tabulated set on disk."""
        import gen_controls as gc
        self.assertEqual([s for s, _ in run_erc.controls(LAYOUT / "erc")],
                         [r["stem"] for r in gc.ERC_TABLE])


if __name__ == "__main__":
    unittest.main()
