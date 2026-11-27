"""Tests for layout/run_erc.py and layout/toolchain_pin.py pure helpers, plus
the shape of the ERC evidence committed under layout/erc/."""
import contextlib
import io
import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

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

    def test_supplies_come_from_the_config_or_its_parsed_document(self):
        self.assertEqual(run_erc.supply_names(LAYOUT / "example_config.json"), ["VDD", "VSS"])
        config = json.loads((LAYOUT / "example_config.json").read_text())
        self.assertEqual(run_erc.supply_names(config), ["VDD", "VSS"])


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

    def test_negative_control_shows_missing_tie_substrate(self):
        """The substrate tie's region is a caller assertion (the n-well
        complement), the half the signoff grader flags as resting on the
        caller's word -- its control must falsify it anyway (issue #232)."""
        rep = json.loads((LAYOUT / "erc" / "controls" / "missing-tie-substrate-inv1.json").read_text())
        findings = run_erc.missing_ties(rep)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["net"], "VSS")
        self.assertEqual(findings[0]["layer"], "substrate_tap")

    def test_control_streams_present_for_the_runner(self):
        """run_erc fails loudly with no control streams; the committed recipe
        (layout/gen_controls.py) must keep exactly the tabulated set on disk."""
        import gen_controls as gc
        self.assertEqual([s for s, _ in run_erc.controls(LAYOUT / "erc")],
                         [r["stem"] for r in gc.ERC_TABLE])


class CheckMode(unittest.TestCase):
    """Runner-level `--check` regressions: `klt erc --check` is stubbed to
    pass (it only rehashes what each report embeds), so every failure below is
    the runner's own binding/grading of the requested inputs."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        for sub in ("gds", "erc"):
            shutil.copytree(LAYOUT / sub, pathlib.Path(self.tmp, "layout", sub))
        for f in ("erc-spec.json", "example_config.json"):
            shutil.copy(LAYOUT / f, pathlib.Path(self.tmp, "layout", f))
        self.old = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, self.old)

    def run_check(self, *extra):
        argv = ["--config", "layout/example_config.json", "--check", *extra]
        ok = mock.Mock(returncode=0, stdout="", stderr="")
        err = io.StringIO()
        with mock.patch.object(run_erc.toolchain_pin, "check_commands", return_value=[]), \
                mock.patch.object(run_erc.subprocess, "run", return_value=ok), \
                contextlib.redirect_stderr(err):
            rc = run_erc.main(argv)
        return rc, err.getvalue()

    def edit(self, rel, fn):
        p = pathlib.Path(self.tmp, rel)
        doc = json.loads(p.read_text())
        fn(doc)
        p.write_text(json.dumps(doc))

    def test_pristine_passes(self):
        self.assertEqual(self.run_check(), (0, ""))

    def test_check_parses_the_config_and_spec_once(self):
        real = pathlib.Path.read_text
        reads = []

        def counting(path, *args, **kwargs):
            reads.append(path.name)
            return real(path, *args, **kwargs)

        with mock.patch.object(pathlib.Path, "read_text", counting):
            rc, _ = self.run_check()
        self.assertEqual(rc, 0)
        self.assertEqual(reads.count("example_config.json"), 1)
        self.assertEqual(reads.count("erc-spec.json"), 1)

    def test_report_copied_over_another_cell_fails(self):
        shutil.copy("layout/erc/sg13g2_inv_2.json", "layout/erc/sg13g2_inv_1.json")
        rc, err = self.run_check()
        self.assertEqual(rc, 1)
        self.assertIn("sg13g2_inv_1: report names layout", err)

    def test_wrong_gds_dir_fails(self):
        rc, err = self.run_check("--gds", "/nonexistent")
        self.assertEqual(rc, 1)
        self.assertIn("missing", err)

    def test_other_spec_fails(self):
        shutil.copy("layout/erc-spec.json", "layout/other-spec.json")
        rc, err = self.run_check("--spec", "layout/other-spec.json")
        self.assertEqual(rc, 1)
        self.assertIn("report names spec", err)

    def test_edited_gds_fails(self):
        with open("layout/gds/sg13g2_inv_1.gds", "ab") as f:
            f.write(b"\0")
        rc, err = self.run_check()
        self.assertEqual(rc, 1)
        self.assertIn("layout hash does not match", err)

    def test_stray_control_report_fails(self):
        shutil.copy("layout/erc/controls/missing-tie-nwell-inv1.json",
                    "layout/erc/controls/retired.json")
        rc, err = self.run_check()
        self.assertEqual(rc, 1)
        self.assertIn("stray control report retired.json", err)

    def test_ordinary_cell_with_violation_fails_check(self):
        def breakit(d):
            d["erc_status"] = "violations"
            d["erc_finding_count"] = 1
            d["erc_findings"] = [Grading.MISSING_TIE]
        self.edit("layout/erc/sg13g2_inv_1.json", breakit)
        rc, err = self.run_check()
        self.assertEqual(rc, 1)
        self.assertIn("not a clean supply/tie verdict", err)

    def test_vdd_only_spec_is_invalid(self):
        def vdd_only(d):
            d["nets"] = [n for n in d["nets"] if n["name"] == "VDD"]
            d["ties"] = [t for t in d["ties"] if t["net"] == "VDD"]
        self.edit("layout/erc-spec.json", vdd_only)
        rc, err = self.run_check()
        self.assertEqual(rc, 2)
        self.assertIn("invalid spec", err)

    def test_report_missing_a_tie_or_rail_fails(self):
        self.edit("layout/erc/sg13g2_inv_1.json", lambda d: d["nets"].pop())
        rc, err = self.run_check()
        self.assertEqual(rc, 1)

    def test_cell_ok_requires_configured_rails_and_ties(self):
        rep = json.loads((LAYOUT / "erc" / "sg13g2_inv_1.json").read_text())
        spec = json.loads((LAYOUT / "erc-spec.json").read_text())
        self.assertTrue(run_erc.cell_ok(rep, ["VDD", "VSS"], spec))
        self.assertFalse(run_erc.cell_ok(rep, ["VDD", "GND"], spec))
        rep["erc_coverage"]["checked"].remove('erc.missing_tie:["substrate_tap"]')
        self.assertFalse(run_erc.cell_ok(rep, ["VDD", "VSS"], spec))


class RunnerCli(unittest.TestCase):
    """run_erc.main with klt stubbed: the flags it takes, and the exit code
    and stderr of its config rejection and capability preflight."""

    def test_help_lists_the_flags(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as stop:
            run_erc.main(["--help"])
        self.assertEqual(stop.exception.code, 0)
        text = " ".join(out.getvalue().split())
        self.assertIn("[-h] --config CONFIG [--spec SPEC] [--gds GDS] [--out OUT] [--check]",
                      text)
        self.assertIn("Run `klt erc` (supply + well/substrate-tie checks) on every generated "
                      "cell.", text)

    def test_invalid_config_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = pathlib.Path(tmp, "missing.json")
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(run_erc.main(["--config", str(missing), "--check"]), 2)
            self.assertTrue(err.getvalue().startswith("run_erc: invalid config: [Errno 2]"),
                            err.getvalue())
            no_process = pathlib.Path(tmp, "no-process.json")
            no_process.write_text('{"cells": [{"name": "c"}]}')
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(run_erc.main(["--config", str(no_process), "--check"]), 2)
        self.assertEqual(err.getvalue(), "run_erc: invalid config: 'process'\n")

    def test_missing_erc_exits_1_naming_the_report_producing_build(self):
        err = io.StringIO()
        check = mock.patch.object(run_erc.toolchain_pin, "check_commands", return_value=["erc"])
        with check, contextlib.redirect_stderr(err):
            rc = run_erc.main(["--config", str(LAYOUT / "example_config.json"), "--check"])
        expected = ("run_erc: klt lacks ['erc']; install a build with `erc` and "
                    "the tie schema erc-spec.json uses: "
                    f"{run_erc.ERC_INSTALL}\n")
        self.assertEqual((rc, err.getvalue()), (1, expected))


class Install(unittest.TestCase):
    def test_install_command_is_the_report_producing_build(self):
        rep = json.loads((LAYOUT / "erc" / "sg13g2_inv_1.json").read_text())
        self.assertEqual(rep["provenance"]["klt_reinstall_spec"],
                         "klayout-tools @ " + run_erc.ERC_INSTALL)
        self.assertIn("well_complement_of", run_erc.SCHEMA_HINT)

    def test_well_boxes_failure_names_the_schema_requirement(self):
        bad = mock.Mock(returncode=1, stdout="", stderr="ties[1].well_boxes required")
        err = io.StringIO()
        with mock.patch.object(run_erc.subprocess, "run", return_value=bad), \
                contextlib.redirect_stderr(err):
            self.assertIsNone(run_erc.run_klt_erc(["klt"], pathlib.Path("x")))
        self.assertIn(run_erc.ERC_INSTALL, err.getvalue())


if __name__ == "__main__":
    unittest.main()
