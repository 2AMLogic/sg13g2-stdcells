"""Tests for layout/gen_controls.py: the control table reproduces the
committed notch DRC controls byte-exactly (each matching its own report's
pinned content_hash), the --check exit codes, and restoration of the
patched generator attributes after a failed row (issue #120)."""
import contextlib
import hashlib
import io
import json
import pathlib
import shutil
import sys
import tempfile
import unittest

LAYOUT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAYOUT))
import gen_controls as gc  # noqa: E402
import gen_layouts as gl  # noqa: E402

CONFIG = LAYOUT / "example_config.json"
CONTROLS = LAYOUT / "drc" / "controls"
CFG = json.loads(CONFIG.read_text())
CONTROL_NAMES = {p.name for p in CONTROLS.glob("*.gds")}


def run(*args):
    """The CLI in-process: (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = gc.main(list(args))
    return rc, out.getvalue(), err.getvalue()


@contextlib.contextmanager
def assert_generator_restored(tc):
    """Assert the generator attributes the forcing patches are the same objects on exit."""
    prof0, hit0, order0 = gl._strip_profile, gl._notch_violation, gl.order_strips
    yield
    tc.assertIs(gl._strip_profile, prof0)
    tc.assertIs(gl._notch_violation, hit0)
    tc.assertIs(gl.order_strips, order0)


class Table(unittest.TestCase):
    """The table must enumerate every control on disk: `--check` reports an
    untabulated stream as stray, and a non-check run would delete it."""

    def test_table_enumerates_every_committed_control(self):
        committed = {p.stem for p in CONTROLS.glob("*.gds")}
        self.assertTrue(committed, "no controls on disk?")
        self.assertEqual({r["stem"] for r in gc.TABLE}, committed)

    def test_generated_streams_carry_the_naming_rule(self):
        """The naming rule the README never stated: the config cell name is
        the stream's GDS structure name (`notch_<strip>_p<pitch>` for a
        profile forcing, `break_<strip>_p<pitch>` for a break forcing), with
        `_lib` appended for the library name."""
        for row in gc.TABLE:
            with self.subTest(control=row["stem"]):
                pitch = row["layout"].get("gate_pitch_nm", CFG["layout"]["gate_pitch_nm"])
                stem = f"break_{row['breaks'][0]}" if "breaks" in row else f"notch_{row['force'][0]}"
                cell_name = f"{stem}_p{pitch}"
                data = gc.regenerate(row, CFG)[f"{row['stem']}.gds"]
                self.assertIn(cell_name.encode(), data)
                self.assertIn((cell_name + "_lib").encode(), data)


class Regeneration(unittest.TestCase):
    def test_each_control_matches_its_committed_stream_and_pinned_hash(self):
        with assert_generator_restored(self):
            files = gc.generate_controls(CFG)
        self.assertEqual(set(files), {f"{r['stem']}.gds" for r in gc.TABLE})
        for stem, data in files.items():
            with self.subTest(control=stem):
                self.assertEqual(data, (CONTROLS / stem).read_bytes(), "regenerated stream differs from the committed control")
                report = json.loads((CONTROLS / stem.replace(".gds", ".json")).read_text())
                self.assertEqual(
                    "sha256:" + hashlib.sha256(data).hexdigest(),
                    report["provenance"]["input"]["content_hash"],
                    "regenerated stream does not match the hash its own report pinned",
                )


class CheckMode(unittest.TestCase):
    def test_check_clean_tree_exits_0(self):
        rc, out, err = run("--check")
        self.assertEqual(rc, 0, err)
        self.assertIn("fresh", out)

    def test_check_tampered_copy_exits_1_naming_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d) / "controls"
            out.mkdir()
            for p in CONTROLS.glob("*.gds"):
                shutil.copy(p, out / p.name)
            victim = out / f"{gc.TABLE[0]['stem']}.gds"
            data = bytearray(victim.read_bytes())
            data[-10] ^= 0xFF
            victim.write_bytes(bytes(data))
            rc, _, err = run("--out", str(out), "--check")
            self.assertEqual(rc, 1)
            self.assertIn(victim.name, err)

    def test_check_reports_stray_and_missing(self):
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d) / "controls"
            out.mkdir()
            (out / "stray.gds").write_bytes(b"")  # matches the glob, absent from the table
            rc, _, err = run("--out", str(out), "--check")
            self.assertEqual(rc, 1)
            self.assertIn("stray", err)
            for row in gc.TABLE:
                self.assertIn(f"{row['stem']}.gds", err)  # every table file reported missing


class WriteMode(unittest.TestCase):
    def test_write_to_temp_dir_matches_committed_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d) / "controls"
            rc, _, err = run("--out", str(out))
            self.assertEqual(rc, 0, err)
            self.assertEqual({p.name for p in out.glob("*.gds")}, CONTROL_NAMES)
            for name in CONTROL_NAMES:
                self.assertEqual((out / name).read_bytes(), (CONTROLS / name).read_bytes())


class OutputIsolation(unittest.TestCase):
    """`--out` alone is a single-output scratch run: it must not touch the
    tracked ERC controls or need the ERC rows, and coincident output
    directories are rejected before anything is generated, written or pruned."""

    ERC = LAYOUT / "erc" / "controls"

    def _erc_snapshot(self):
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.ERC.glob("*.gds")}

    def test_out_only_leaves_tracked_erc_controls_alone(self):
        before = self._erc_snapshot()
        self.assertTrue(before)
        with tempfile.TemporaryDirectory() as d:
            cfg = json.loads(CONFIG.read_text())
            cfg["process"]["vdd_net"] = "VDD_TEST"
            cfgp = pathlib.Path(d) / "other.json"
            cfgp.write_text(json.dumps(cfg))
            out = pathlib.Path(d) / "drc"
            rc, _, err = run("--config", str(cfgp), "--out", str(out))
            self.assertEqual(rc, 0, err)
            self.assertEqual({p.name for p in out.glob("*.gds")}, CONTROL_NAMES)
        self.assertEqual(self._erc_snapshot(), before)

    def test_single_output_run_needs_only_its_own_rows(self):
        """A bare `--out` (or `--erc-out`) generates only its own set: a config
        that cannot feed the other set's rows still writes the requested one."""
        for flag, table in (("--out", gc.TABLE), ("--erc-out", gc.ERC_TABLE)):
            needed = {r["cell"] for r in table if isinstance(r["cell"], str)}
            cfg = {**CFG, "cells": [c for c in CFG["cells"] if c["name"] in needed]}
            with self.subTest(flag=flag), tempfile.TemporaryDirectory() as d:
                cfgp = pathlib.Path(d) / "cfg.json"
                cfgp.write_text(json.dumps(cfg))
                out = pathlib.Path(d) / "out"
                rc, _, err = run("--config", str(cfgp), flag, str(out))
                self.assertEqual(rc, 0, err)
                self.assertEqual({p.name for p in out.glob("*.gds")}, {f"{r['stem']}.gds" for r in table})

    def test_failed_set_leaves_both_directories_untouched(self):
        """Every selected set is generated before any is written: when the ERC
        rows cannot be fed, the notch set is not written either."""
        erc_cells = {r["cell"] for r in gc.ERC_TABLE}
        cfg = {**CFG, "cells": [c for c in CFG["cells"] if c["name"] not in erc_cells]}
        with tempfile.TemporaryDirectory() as d:
            cfgp = pathlib.Path(d) / "cfg.json"
            cfgp.write_text(json.dumps(cfg))
            rc, _, err = run("--config", str(cfgp), "--out", str(pathlib.Path(d) / "a"), "--erc-out", str(pathlib.Path(d) / "b"))
            self.assertEqual(rc, 2, err)
            self.assertEqual([p.name for p in pathlib.Path(d).iterdir()], ["cfg.json"])

    def test_coincident_out_dirs_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as d:
            marker = pathlib.Path(d) / "keep.gds"
            marker.write_bytes(b"x")
            rc, _, err = run("--out", d, "--erc-out", d)
            self.assertEqual(rc, 2, err)
            self.assertIn("same directory", err)
            # Settled before a stream is generated: an unplaceable config would be exit 3.
            cfgp = pathlib.Path(d) / "unplaceable.json"
            cfgp.write_text(json.dumps({**CFG, "layout": {**CFG["layout"], "row_height_nm": 1}}))
            rc, _, err = run("--config", str(cfgp), "--out", d, "--erc-out", d)
            self.assertEqual(rc, 2, err)
            self.assertIn("same directory", err)
            self.assertEqual(marker.read_bytes(), b"x")
            self.assertEqual([p.name for p in pathlib.Path(d).glob("*.gds")], ["keep.gds"])

    def test_distinct_out_dirs_write_both_sets(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = pathlib.Path(d) / "a", pathlib.Path(d) / "b"
            rc, _, err = run("--out", str(a), "--erc-out", str(b))
            self.assertEqual(rc, 0, err)
            self.assertEqual({p.name for p in a.glob("*.gds")}, CONTROL_NAMES)
            self.assertEqual({p.name for p in b.glob("*.gds")}, set(self._erc_snapshot()))


class Validation(unittest.TestCase):
    """Each set validates the config itself: a bare `--erc-out` run does not
    borrow the notch generator's check, and neither does a direct call."""

    def test_erc_controls_reject_an_invalid_config_on_their_own(self):
        bad = {**CFG, "schema_version": 99}
        with self.assertRaises(ValueError):
            gc.generate_erc_controls(bad)
        with tempfile.TemporaryDirectory() as d:
            cfgp = pathlib.Path(d) / "bad.json"
            cfgp.write_text(json.dumps(bad))
            out = pathlib.Path(d) / "erc"
            rc, _, err = run("--config", str(cfgp), "--erc-out", str(out))
            self.assertFalse(out.exists(), "a refused config must write nothing")
        self.assertEqual(rc, 2, err)
        self.assertIn("invalid config", err)


class PatchRestoration(unittest.TestCase):
    def test_attributes_restored_after_a_failed_row(self):
        """The p420 forcing with the notch check left live is exactly the
        refusal the recorded row stubbed off -- a failed row must not leave
        the generator patched for the next one."""
        row = dict(gc.TABLE[0], notch_off=False)
        with assert_generator_restored(self), self.assertRaises(gl.PlaceError):
            gc.regenerate(row, CFG)

    def test_failed_break_row_restores_order_strips(self):
        """A break row that fails to place inside `forced_break` must not
        leave `order_strips` patched for the next one."""
        row = next(r for r in gc.TABLE if "breaks" in r)
        broken = dict(row, layout=dict(row["layout"], row_height_nm=1))
        with assert_generator_restored(self), self.assertRaises(gl.PlaceError):
            gc.regenerate(broken, CFG)

    def test_generate_controls_restores_attributes_when_a_row_fails(self):
        broken = dict(gc.TABLE[1], layout=dict(gc.TABLE[1]["layout"], row_height_nm=1))
        with assert_generator_restored(self), self.assertRaises(gl.PlaceError):
            gc.generate_controls(CFG, [gc.TABLE[0], broken, gc.TABLE[2]])


if __name__ == "__main__":
    unittest.main()
