"""Tests for layout/gen_controls.py: the control table reproduces the
committed notch DRC controls byte-exactly (each matching its own report's
pinned content_hash), the --check exit codes, and restoration of the
patched generator attributes after a failed row (issue #120)."""
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

LAYOUT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAYOUT))
import gen_controls as gc  # noqa: E402
import gen_layouts as gl  # noqa: E402

CONFIG = LAYOUT / "example_config.json"
CONTROLS = LAYOUT / "drc" / "controls"
SCRIPT = LAYOUT / "gen_controls.py"
CFG = json.loads(CONFIG.read_text())


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


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
        prof0, hit0, order0 = gl._strip_profile, gl._notch_violation, gl.order_strips
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
        self.assertIs(gl._strip_profile, prof0)
        self.assertIs(gl._notch_violation, hit0)
        self.assertIs(gl.order_strips, order0)


class CheckMode(unittest.TestCase):
    def test_check_clean_tree_exits_0(self):
        r = run("--check")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("fresh", r.stdout)

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
            r = run("--out", str(out), "--check")
            self.assertEqual(r.returncode, 1)
            self.assertIn(victim.name, r.stderr)

    def test_check_reports_stray_and_missing(self):
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d) / "controls"
            out.mkdir()
            (out / "stray.gds").write_bytes(b"")  # matches the glob, absent from the table
            r = run("--out", str(out), "--check")
            self.assertEqual(r.returncode, 1)
            self.assertIn("stray", r.stderr)
            for row in gc.TABLE:
                self.assertIn(f"{row['stem']}.gds", r.stderr)  # every table file reported missing


class WriteMode(unittest.TestCase):
    def test_write_to_temp_dir_matches_committed_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d) / "controls"
            r = run("--out", str(out))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(
                {p.name for p in out.glob("*.gds")},
                {p.name for p in CONTROLS.glob("*.gds")},
            )
            for p in CONTROLS.glob("*.gds"):
                self.assertEqual((out / p.name).read_bytes(), p.read_bytes())


class PatchRestoration(unittest.TestCase):
    def test_attributes_restored_after_a_failed_row(self):
        """The p420 forcing with the notch check left live is exactly the
        refusal the recorded row stubbed off -- a failed row must not leave
        the generator patched for the next one."""
        prof0, hit0, order0 = gl._strip_profile, gl._notch_violation, gl.order_strips
        row = dict(gc.TABLE[0], notch_off=False)
        with self.assertRaises(gl.PlaceError):
            gc.regenerate(row, CFG)
        self.assertIs(gl._strip_profile, prof0)
        self.assertIs(gl._notch_violation, hit0)
        self.assertIs(gl.order_strips, order0)

    def test_failed_break_row_restores_order_strips(self):
        """A break row that fails to place inside `forced_break` must not
        leave `order_strips` patched for the next one."""
        order0 = gl.order_strips
        row = next(r for r in gc.TABLE if "breaks" in r)
        broken = dict(row, layout=dict(row["layout"], row_height_nm=1))
        with self.assertRaises(gl.PlaceError):
            gc.regenerate(broken, CFG)
        self.assertIs(gl.order_strips, order0)

    def test_generate_controls_restores_attributes_when_a_row_fails(self):
        prof0, hit0, order0 = gl._strip_profile, gl._notch_violation, gl.order_strips
        broken = dict(gc.TABLE[1], layout=dict(gc.TABLE[1]["layout"], row_height_nm=1))
        with self.assertRaises(gl.PlaceError):
            gc.generate_controls(CFG, [gc.TABLE[0], broken, gc.TABLE[2]])
        self.assertIs(gl._strip_profile, prof0)
        self.assertIs(gl._notch_violation, hit0)
        self.assertIs(gl.order_strips, order0)


if __name__ == "__main__":
    unittest.main()
