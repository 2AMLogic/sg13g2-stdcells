"""One git-provenance snapshot stamps both the record and its sidecar.

Regression for the false-provenance bug fixed in issue #82: ``characterize_library``
used to snapshot ``git_provenance`` *after* writing the ``.lib`` and the record,
so the sidecar's ``repo_commit`` carried a ``(dirty)`` suffix from the run's own
outputs while the record stamped clean -- two stamps naming different tree states
for one run. The fix captures provenance once, before anything is written, and
threads it through ``record()`` and ``provenance_for()``; these tests pin that
both stamps agree on an injected snapshot, PDK-free.

Run from the repo root:  python -m pytest sim/tests
"""

from pathlib import Path
import json
import subprocess
import tempfile

import pytest

from sim.characterize import runner
from sim.characterize.request import DEFAULT_CORNER, SG13G2_INV_1
from sim.harness.report import commit_stamp

GIT = {"commit": "a" * 40, "short": "aaaaaaa", "branch": "main", "dirty": False}
GIT_DIRTY = {**GIT, "dirty": True}


def record_data():
    """Minimal single-arc payload, the shape ``build_record_data()`` returns."""
    return {
        "cell": "sg13g2_inv_1",
        "netlist_provenance": "netlist supplied to klt characterize: /tmp/sg13g2_inv_1.spice",
        "corner": {"name": "tt"},
        "backend": "local",
        "klt": {"version": "klt 0.9.2.dev1029", "provenance_version": "0.9.2",
                "provenance": {}},
        "axes": {"input_transition_ns": [0.01], "output_load_pf": [0.01]},
        "units": {},
        "arcs": [{"related_pin": "A", "output_pin": "Y", "timing_sense": "positive_unate",
                  "side_inputs": {},
                  "cell_rise": [[0.05]], "cell_fall": [[0.06]],
                  "rise_transition": [[0.02]], "fall_transition": [[0.03]],
                  "rise_power": [[0.001]], "fall_power": [[0.002]]}],
        "leakage": 1e-3,
    }


def write_record(tmp_path, git):
    return runner.record(record_data(), records_dir=tmp_path / "records",
                         repo_root=tmp_path, git=git)


def repo_commit_line(path):
    return next(line for line in path.read_text().splitlines()
                if line.startswith("**Repo commit**"))


def sidecar(tmp_path, path, git):
    config = tmp_path / "layout" / "example_config.json"
    config.parent.mkdir()
    config.write_text("{}\n")
    library_data = {**record_data(), "cells": [record_data()], "record_id": path.stem}
    return runner.provenance_for(config, {"name": "tt"}, library_data, git=git)


def test_record_and_sidecar_stamp_one_tree_state(tmp_path):
    path = write_record(tmp_path, GIT)
    prov = sidecar(tmp_path, path, GIT)
    assert repo_commit_line(path) == f"**Repo commit**: {GIT['commit']}"
    assert prov["repo_commit"] == GIT["commit"]  # no spurious "(dirty)" suffix
    assert repo_commit_line(path) == f"**Repo commit**: {prov['repo_commit']}"


def test_dirty_snapshot_marks_both_stamps(tmp_path):
    path = write_record(tmp_path, GIT_DIRTY)
    prov = sidecar(tmp_path, path, GIT_DIRTY)
    assert repo_commit_line(path) == f"**Repo commit**: {commit_stamp(GIT_DIRTY)}"
    assert prov["repo_commit"] == commit_stamp(GIT_DIRTY)


def test_notes_line_names_klt_once(tmp_path):
    path = write_record(tmp_path, GIT)
    notes = next(line for line in path.read_text().splitlines()
                 if line.startswith("**Notes**"))
    assert "klt 0.9.2.dev1029," in notes
    assert "klt klt" not in notes


# --- Scratch-dir hygiene of characterize_and_record (issue #149) ------------

def klt_response():
    """``klt characterize`` stdout shape (raw arc tables are ``{"values": ...}``)."""
    d = record_data()
    arcs = [{**a, **{t: {"values": a[t]} for t in runner.TABLES if t in a}}
            for a in d["arcs"]]
    return {
        "corner": d["corner"],
        "grid": d["axes"],
        "units": d["units"],
        "cells": [{"cell": {"name": d["cell"]}, "arcs": arcs,
                   "leakage": d["leakage"],
                   "simulation": {"engine": "ngspice", "engine_version": "47"}}],
    }


def fake_klt_ok(cmd, capture_output=True, text=True, check=False):
    if "--version" in cmd:
        return subprocess.CompletedProcess(cmd, 0, stdout="klt 9.9.9-test", stderr="")
    return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(klt_response()), stderr="")


def scratch_names():
    """Every scratch dir of either prefix under the (hermetic) temp root."""
    root = Path(tempfile.gettempdir())
    return sorted(p.name for pat in ("klt-characterize-*", "sg13g2-char-*")
                  for p in root.glob(pat))


def hermetic_tempdir(tmp_path, monkeypatch):
    """Point tempfile at ``tmp_path`` so scratch-dir census is hermetic."""
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))


def test_characterize_and_record_leaves_no_scratch_dir(tmp_path, monkeypatch):
    """Regression (issue #149): ``run_klt``'s ``workdir=None`` fallback leaked
    one ``/tmp/klt-characterize-*`` dir per call; the caller now owns a
    TemporaryDirectory and passes ``workdir=``."""
    hermetic_tempdir(tmp_path, monkeypatch)
    monkeypatch.setattr(runner.subprocess, "run", fake_klt_ok)
    monkeypatch.setattr(runner, "git_provenance", lambda repo_root: GIT)
    records_dir = tmp_path / "records"

    before = scratch_names()
    path = runner.characterize_and_record(SG13G2_INV_1, DEFAULT_CORNER,
                                          "/nonexistent-pdk", records_dir=records_dir)

    assert scratch_names() == before
    assert list(records_dir.glob("*.md")) == [path]  # not vacuously green


def test_characterize_and_record_failure_cleans_scratch_and_reports(tmp_path, monkeypatch):
    """The CharacterizeFailed path must also reap the scratch dir and keep
    carrying klt's output in the exception message."""
    hermetic_tempdir(tmp_path, monkeypatch)

    def failing(cmd, capture_output=True, text=True, check=False):
        if "--version" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="klt 9.9.9-test", stderr="")
        return subprocess.CompletedProcess(cmd, 1, stdout="",
                                           stderr="boom: missing cell arc")

    monkeypatch.setattr(runner.subprocess, "run", failing)
    monkeypatch.setattr(runner, "git_provenance", lambda repo_root: GIT)

    before = scratch_names()
    with pytest.raises(runner.CharacterizeFailed) as excinfo:
        runner.characterize_and_record(SG13G2_INV_1, DEFAULT_CORNER,
                                       "/nonexistent-pdk", records_dir=tmp_path / "records")

    assert "boom: missing cell arc" in str(excinfo.value)
    assert scratch_names() == before
