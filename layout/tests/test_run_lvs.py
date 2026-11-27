"""Tests for layout/run_lvs.py and layout/toolchain_pin.py pure helpers, plus
the shape of the LVS evidence committed under layout/lvs/."""
import contextlib
import io
import json
import pathlib
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

HELP_WITH_ERC = """usage: klt
positional arguments:
  <command>
    layers              enumerate layers
    drc                 run a headless DRC deck
    erc                 supply/tie connectivity checks
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

    def test_pin_lists_erc(self):
        self.assertIn("erc", toolchain_pin.required_commands())

    def test_missing_names_erc_command(self):
        """The runner fails loudly when klt lacks `erc` (issue #179): the
        shared check names it, so a missing subcommand is never skipped."""
        self.assertEqual(toolchain_pin.missing_commands(["drc", "erc", "lvs"], HELP),
                         ["erc"])
        self.assertEqual(toolchain_pin.missing_commands(["drc", "erc", "lvs"], HELP_WITH_ERC),
                         [])


class SharedRunner(unittest.TestCase):
    """The runner plumbing every layout/ runner imports from toolchain_pin:
    one CLI skeleton, one preflight diagnostic, one --check bookkeeping."""

    def test_load_json_accepts_a_path_or_an_already_parsed_document(self):
        doc = toolchain_pin.load_json(CONFIG)
        self.assertEqual(doc["process"]["vdd_net"], "VDD")
        self.assertIs(toolchain_pin.load_json(doc), doc)
        self.assertEqual(toolchain_pin.cell_names(doc), toolchain_pin.cell_names(CONFIG))

    def test_parse_runner_args_defaults_beside_the_config(self):
        a, cfgdir, gds, out = toolchain_pin.parse_runner_args(
            "Doc.\n", "lvs", ["--config", str(CONFIG)])
        self.assertEqual((cfgdir, gds, out), (LAYOUT, LAYOUT / "gds", LAYOUT / "lvs"))
        self.assertEqual((a.config, a.check), (str(CONFIG), False))

    def test_parse_runner_args_keeps_explicit_paths_and_extra_flags(self):
        argv = ["--config", str(CONFIG), "--spec", "s", "--gds", "g", "--out", "o", "--check"]
        a, cfgdir, gds, out = toolchain_pin.parse_runner_args(
            "Doc.\n", "erc", argv, extra_flags=("--spec",))
        self.assertEqual((cfgdir, a.spec, gds, out, a.check),
                         (LAYOUT, "s", pathlib.Path("g"), pathlib.Path("o"), True))

    def test_ensure_commands_is_one_preflight_diagnostic(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), \
                mock.patch.object(toolchain_pin, "check_commands", return_value=[]):
            self.assertEqual(toolchain_pin.ensure_commands("run_x"), 0)
        with contextlib.redirect_stderr(err), \
                mock.patch.object(toolchain_pin, "check_commands", return_value=["drc", "erc"]):
            self.assertEqual(toolchain_pin.ensure_commands("run_x"), 1)
            self.assertEqual(toolchain_pin.ensure_commands("run_x", "install the build"), 1)
        with contextlib.redirect_stderr(err), \
                mock.patch.object(toolchain_pin, "check_commands", side_effect=OSError("no klt")):
            self.assertEqual(toolchain_pin.ensure_commands("run_x"), 1)
        hint = toolchain_pin.install_hint()
        self.assertEqual(err.getvalue(),
                         f"run_x: klt lacks ['drc', 'erc']; install: {hint}\n"
                         "run_x: klt lacks ['drc', 'erc']; install the build\n"
                         "run_x: cannot run klt: no klt\n")

    def test_check_report_fresh_names_a_missing_or_stale_report(self):
        calls = []

        def stale(rep):
            calls.append(rep)
            return types.SimpleNamespace(returncode=1, stdout="x" * 250, stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            rep = pathlib.Path(tmp) / "c.json"
            self.assertEqual(toolchain_pin.check_report_fresh("c", rep, "lvs", stale),
                             [f"c: report {rep} missing"])
            self.assertEqual(calls, [])
            rep.write_text("{}")
            self.assertEqual(toolchain_pin.check_report_fresh("c", rep, "lvs", stale),
                             [f"c: klt lvs --check exit 1: {'x' * 200}"])
            self.assertEqual(calls, [rep])
            self.assertEqual(toolchain_pin.check_report_fresh("control c", rep, "erc", stale),
                             [f"control c: klt erc --check exit 1: {'x' * 200}"])

    def test_stray_reports_are_sorted_and_labelled(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            for name in ("c.json", "a.json", "b.json"):
                (d / name).write_text("{}")
            self.assertEqual(toolchain_pin.stray_reports(d, ["c"]),
                             ["stray report a.json", "stray report b.json"])
            self.assertEqual(toolchain_pin.stray_reports(d, ["a", "b", "c"]), [])
            self.assertEqual(toolchain_pin.stray_reports(d / "controls", set()), [])
            (d / "controls").mkdir()
            (d / "controls" / "z.json").write_text("{}")
            strays = toolchain_pin.stray_reports(d / "controls", set(), "stray control report")
            self.assertEqual(strays, ["stray control report z.json"])

    def test_emit_check_errors_is_the_exit_tail(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(toolchain_pin.emit_check_errors([]), 0)
            self.assertEqual(toolchain_pin.emit_check_errors(["first", "second"]), 1)
        self.assertEqual(err.getvalue(), "first\nsecond\n")


class RunnerCli(unittest.TestCase):
    """run_lvs.main with klt stubbed: the flags it takes, and the exit code
    and stderr of its capability preflight."""

    def preflight(self, **behaviour):
        err = io.StringIO()
        with mock.patch.object(run_lvs.toolchain_pin, "check_commands", **behaviour), \
                contextlib.redirect_stderr(err):
            rc = run_lvs.main(["--config", str(CONFIG), "--check"])
        return rc, err.getvalue()

    def test_help_lists_the_flags(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as stop:
            run_lvs.main(["--help"])
        self.assertEqual(stop.exception.code, 0)
        text = " ".join(out.getvalue().split())
        self.assertIn("[-h] --config CONFIG [--gds GDS] [--out OUT] [--check]", text)
        self.assertIn("Run `klt lvs` on every generated cell against its generator netlist.",
                      text)

    def test_missing_command_exits_1_naming_it_and_the_install_hint(self):
        hint = toolchain_pin.install_hint()
        self.assertEqual(self.preflight(return_value=["lvs"]),
                         (1, f"run_lvs: klt lacks ['lvs']; install: {hint}\n"))

    def test_unrunnable_klt_exits_1(self):
        self.assertEqual(self.preflight(side_effect=OSError("no klt")),
                         (1, "run_lvs: cannot run klt: no klt\n"))


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
