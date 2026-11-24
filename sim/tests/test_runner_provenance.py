"""One git-provenance snapshot stamps both the record and its sidecar.

Regression for the false-provenance bug fixed in issue #82: ``characterize_library``
used to snapshot ``git_provenance`` *after* writing the ``.lib`` and the record,
so the sidecar's ``repo_commit`` carried a ``(dirty)`` suffix from the run's own
outputs while the record stamped clean -- two stamps naming different tree states
for one run. The fix captures provenance once, before anything is written, and
threads it through ``record()`` and ``provenance_for()``. These tests pin both
halves of that fix: ``test_characterize_library_snapshots_once_before_writing``
enters ``characterize_library`` and pins the capture-before-write ordering itself
(one snapshot, taken before the record and sidecar writes), and the remaining
tests pin that both stamps agree on an injected snapshot -- all PDK-free.

Issue #178 adds the PDK pin and gives it the same discipline: one
``pdk_provenance()`` snapshot, captured before klt runs or anything is written,
threaded into both the record header and the sidecar. The ``pdk_provenance``
tests below build real throwaway git checkouts, because what they pin is git
behaviour (subdirectory resolution, dirtiness, the foreign-repository refusal)
a mock would merely restate.

Run from the repo root:  python -m pytest sim/tests
"""

import subprocess
from pathlib import Path
import json
import tempfile

import pytest

from sim.characterize import runner
from sim.harness.report import commit_stamp

GIT = {"commit": "a" * 40, "short": "aaaaaaa", "branch": "main", "dirty": False}
GIT_DIRTY = {**GIT, "dirty": True}
PDK = {"name": "IHP-Open-PDK", "revision": "5" * 40}


def record_data():
    """Minimal single-arc payload, the shape ``build_record_data()`` returns."""
    return {
        "cell": "sg13g2_inv_1",
        "netlist_provenance": "netlist supplied to klt characterize: /tmp/sg13g2_inv_1.spice",
        "corner": {"name": "tt"},
        "backend": "local",
        "klt": {"version": "klt 0.9.2.dev1029", "provenance_version": "0.9.2",
                "provenance": {}},
        "pdk": PDK,
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


def pdk_line(path):
    return next(line for line in path.read_text().splitlines()
                if line.startswith("**PDK**"))


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


def test_record_and_sidecar_stamp_one_pdk(tmp_path):
    # Issue #178: one pdk_provenance() snapshot threads through both writers,
    # exactly as the git snapshot does -- the record header carries the same
    # name and full SHA the sidecar's pdk object pins.
    path = write_record(tmp_path, GIT)
    prov = sidecar(tmp_path, path, GIT)
    assert pdk_line(path) == f"**PDK**: {PDK['name']} @ {PDK['revision']}"
    assert prov["pdk"] == PDK
    assert pdk_line(path) == f"**PDK**: {prov['pdk']['name']} @ {prov['pdk']['revision']}"


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


def repo_status() -> str:
    return subprocess.run(["git", "status", "--porcelain"], cwd=runner.REPO_ROOT,
                          capture_output=True, text=True, check=False).stdout


def library_response():
    """One-cell library-shaped ``klt characterize`` response (1x1 grid, one arc)."""
    return {
        "corner": {"name": "tt"},
        "grid": {"input_transition_ns": [0.01], "output_load_pf": [0.01]},
        "units": {},
        "provenance": {"klt_version": "0.9.2"},
        "cells": [{"cell": {"name": "sg13g2_inv_1"},
                   "arcs": [{"related_pin": "A", "output_pin": "Y",
                             "timing_sense": "positive_unate", "side_inputs": {},
                             "cell_rise": {"values": [[0.05]]},
                             "cell_fall": {"values": [[0.06]]},
                             "rise_transition": {"values": [[0.02]]},
                             "fall_transition": {"values": [[0.03]]},
                             "rise_power": {"values": [[0.001]]},
                             "fall_power": {"values": [[0.002]]}}],
                   "simulation": {"engine": "ngspice", "engine_version": "47"},
                   "leakage": 1e-3}],
    }


def test_characterize_library_snapshots_once_before_writing(tmp_path, monkeypatch):
    """``characterize_library`` captures git provenance once, before any write.

    The first consultation sees a clean ``a``-commit tree; every later one sees a
    dirty ``b``-commit tree. A regression to the pre-#82 shape -- snapshotting
    after the writes via ``record()``/``provenance_for()``'s fallbacks -- flips
    both stamps to the dirty ``b`` commit and the consultation count past one.

    The PDK snapshot (#178) is pinned the same way: captured before anything
    else, once, and threaded into both the record header and the sidecar.
    """
    calls = []
    pdk_calls = []

    def snapshot(root):
        calls.append(root)
        if len(calls) == 1:
            return GIT
        return {**GIT, "commit": "b" * 40, "short": "bbbbbbb", "dirty": True}

    def pdk_snapshot(pdk_dir):
        pdk_calls.append(pdk_dir)
        return PDK

    config = tmp_path / "layout" / "example_config.json"
    config.parent.mkdir()
    config.write_text(json.dumps(
        {"process": {}, "cells": [{"name": "sg13g2_inv_1", "inputs": ["A"],
                                   "outputs": {"Y": "!A"}}]}) + "\n")

    monkeypatch.setattr(runner, "git_provenance", snapshot)
    monkeypatch.setattr(runner, "pdk_provenance", pdk_snapshot)
    monkeypatch.setattr(runner, "generate_netlists", lambda config, out: None)
    monkeypatch.setattr(runner, "run_klt", lambda request, *, workdir,
                        backend="local", lib_path=None: library_response())
    status_before = repo_status()

    path = runner.characterize_library(config, "tt", tmp_path / "pdk",
                                       lib_path=tmp_path / "out.lib",
                                       records_dir=tmp_path / "records")

    assert repo_commit_line(path) == f"**Repo commit**: {GIT['commit']}"
    prov = json.loads((tmp_path / "out.lib.provenance").read_text())
    assert prov["repo_commit"] == GIT["commit"]  # no spurious "(dirty)" suffix
    assert repo_commit_line(path) == f"**Repo commit**: {prov['repo_commit']}"
    assert calls == [runner.REPO_ROOT]  # consulted exactly once, before the writes
    assert pdk_line(path) == f"**PDK**: {PDK['name']} @ {PDK['revision']}"
    assert prov["pdk"] == PDK  # one snapshot, both writers
    assert pdk_calls == [tmp_path / "pdk"]  # captured before anything ran
    assert repo_status() == status_before  # nothing written inside the repository


# --- PDK revision capture (issue #178) ---------------------------------------


def make_pdk_checkout(root: Path, origin: str | None, commit: bool = True) -> str:
    """A throwaway IHP-Open-PDK-shaped git checkout; returns its HEAD SHA.

    The variant lives in an ``ihp-sg13g2`` subdirectory, the layout a real
    clone has, so the subdirectory-resolution path is the one exercised.
    """
    repo = root / "IHP-Open-PDK"
    variant = repo / "ihp-sg13g2" / "libs.tech" / "ngspice" / "models"
    variant.mkdir(parents=True)
    (variant / "cornerMOSlv.lib").write_text("* corner models\n")

    def git(*args: str) -> str:
        proc = subprocess.run(
            ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
            cwd=repo, capture_output=True, text=True, check=True)
        return proc.stdout.strip()

    git("init", "-q", "-b", "main")
    if origin is not None:
        git("remote", "add", "origin", origin)
    if commit:
        git("add", "-A")
        git("commit", "-q", "-m", "pdk fixture")
        return git("rev-parse", "HEAD")
    return ""


def test_pdk_provenance_reads_variant_subdirectory_commit(tmp_path):
    sha = make_pdk_checkout(tmp_path, "https://github.com/IHP-GmbH/IHP-Open-PDK.git")
    variant = tmp_path / "IHP-Open-PDK" / "ihp-sg13g2"
    assert runner.pdk_provenance(variant) == {"name": "IHP-Open-PDK", "revision": sha}
    assert runner.pdk_provenance(variant / "libs.tech")["revision"] == sha  # any depth


def test_pdk_provenance_rejects_dirty_checkout(tmp_path):
    make_pdk_checkout(tmp_path, "https://github.com/IHP-GmbH/IHP-Open-PDK.git")
    variant = tmp_path / "IHP-Open-PDK" / "ihp-sg13g2"
    (variant / "libs.tech" / "ngspice" / "models" / "cornerMOSlv.lib").write_text(
        "* tampered\n")
    with pytest.raises(runner.CharacterizeFailed, match="dirty"):
        runner.pdk_provenance(variant)
    (variant / "libs.tech" / "ngspice" / "models" / "stray.lib").write_text("extra\n")
    with pytest.raises(runner.CharacterizeFailed, match="dirty"):
        runner.pdk_provenance(variant)


def test_pdk_provenance_rejects_missing_revision(tmp_path):
    make_pdk_checkout(tmp_path, "https://github.com/IHP-GmbH/IHP-Open-PDK.git",
                      commit=False)
    variant = tmp_path / "IHP-Open-PDK" / "ihp-sg13g2"
    with pytest.raises(runner.CharacterizeFailed, match="cannot determine"):
        runner.pdk_provenance(variant)


def test_pdk_provenance_rejects_directory_outside_any_git_tree(tmp_path):
    plain = tmp_path / "just-a-directory" / "ihp-sg13g2"
    plain.mkdir(parents=True)
    with pytest.raises(runner.CharacterizeFailed, match="cannot determine"):
        runner.pdk_provenance(plain)


def test_pdk_provenance_rejects_foreign_git_tree(tmp_path):
    # A PDK copied inside an unrelated repository (this repo's shape) must
    # never acquire the enclosing project's SHA: clean and committed does not
    # help when the repository is not IHP-Open-PDK's own.
    sha = make_pdk_checkout(tmp_path, "https://github.com/2AMLogic/sg13g2-stdcells.git")
    variant = tmp_path / "IHP-Open-PDK" / "ihp-sg13g2"
    with pytest.raises(runner.CharacterizeFailed, match="not an IHP-Open-PDK"):
        runner.pdk_provenance(variant)
    assert sha  # the refusal is about identity, not a missing commit


def test_characterize_library_refuses_unpinnable_pdk_before_any_write(tmp_path, monkeypatch):
    """A PDK the runner cannot pin refuses the run before klt or any write.

    ``run_klt`` and ``generate_netlists`` set flags when called; both must
    stay clear, and no view, sidecar or record may exist afterwards.
    """
    ran = []

    def refuse(pdk_dir):
        ran.append("pdk_provenance")
        raise runner.CharacterizeFailed("cannot determine the PDK revision")

    monkeypatch.setattr(runner, "pdk_provenance", refuse)
    monkeypatch.setattr(runner, "generate_netlists",
                        lambda config, out: ran.append("gen_netlists"))
    monkeypatch.setattr(runner, "run_klt",
                        lambda request, *, workdir, backend="local",
                        lib_path=None: ran.append("klt") or {})

    config = tmp_path / "layout" / "example_config.json"
    config.parent.mkdir()
    config.write_text(json.dumps(
        {"process": {}, "cells": [{"name": "sg13g2_inv_1", "inputs": ["A"],
                                   "outputs": {"Y": "!A"}}]}) + "\n")
    lib = tmp_path / "out.lib"

    with pytest.raises(runner.CharacterizeFailed, match="cannot determine"):
        runner.characterize_library(config, "tt", tmp_path / "pdk", lib_path=lib,
                                    records_dir=tmp_path / "records")
    assert ran == ["pdk_provenance"]
    assert not lib.exists()
    assert not Path(str(lib) + ".provenance").exists()
    assert not (tmp_path / "records").exists()


# --- Scratch-dir hygiene of characterize_library (issue #149) ---------------

def write_config(tmp_path):
    config = tmp_path / "layout" / "example_config.json"
    config.parent.mkdir(exist_ok=True)
    config.write_text(json.dumps(
        {"process": {}, "cells": [{"name": "sg13g2_inv_1", "inputs": ["A"],
                                   "outputs": {"Y": "!A"}}]}) + "\n")
    return config


def fake_klt_ok(cmd, capture_output=True, text=True, check=False):
    if "--version" in cmd:
        return subprocess.CompletedProcess(cmd, 0, stdout="klt 9.9.9-test", stderr="")
    return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(library_response()), stderr="")


def scratch_names():
    """Every scratch dir of either prefix under the (hermetic) temp root."""
    root = Path(tempfile.gettempdir())
    return sorted(p.name for pat in ("klt-characterize-*", "sg13g2-char-*", "sg13g2-lib-*")
                  for p in root.glob(pat))


def hermetic_tempdir(tmp_path, monkeypatch):
    """Point tempfile at ``tmp_path`` so scratch-dir census is hermetic."""
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))


def test_characterize_library_leaves_no_scratch_dir(tmp_path, monkeypatch):
    """Regression (issue #149): ``run_klt``'s ``workdir=None`` fallback leaked
    one ``/tmp/klt-characterize-*`` dir per call; the caller now owns a
    TemporaryDirectory and passes ``workdir=``."""
    config = write_config(tmp_path)
    hermetic_tempdir(tmp_path, monkeypatch)
    monkeypatch.setattr(runner, "pdk_provenance", lambda pdk_dir: PDK)
    monkeypatch.setattr(runner, "generate_netlists", lambda config, out: None)
    monkeypatch.setattr(runner.subprocess, "run", fake_klt_ok)
    monkeypatch.setattr(runner, "git_provenance", lambda repo_root: GIT)
    records_dir = tmp_path / "records"

    before = scratch_names()
    path = runner.characterize_library(config, "tt", "/nonexistent-pdk",
                                       lib_path=tmp_path / "out.lib",
                                       records_dir=records_dir)

    assert scratch_names() == before
    assert list(records_dir.glob("*.md")) == [path]  # not vacuously green


def test_characterize_library_failure_cleans_scratch_and_reports(tmp_path, monkeypatch):
    """The CharacterizeFailed path must also reap the scratch dir and keep
    carrying klt's output in the exception message."""
    config = write_config(tmp_path)
    hermetic_tempdir(tmp_path, monkeypatch)

    def failing(cmd, capture_output=True, text=True, check=False):
        if "--version" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="klt 9.9.9-test", stderr="")
        return subprocess.CompletedProcess(cmd, 1, stdout="",
                                           stderr="boom: missing cell arc")

    monkeypatch.setattr(runner.subprocess, "run", failing)
    monkeypatch.setattr(runner, "pdk_provenance", lambda pdk_dir: PDK)
    monkeypatch.setattr(runner, "generate_netlists", lambda config, out: None)
    monkeypatch.setattr(runner, "git_provenance", lambda repo_root: GIT)

    before = scratch_names()
    with pytest.raises(runner.CharacterizeFailed) as excinfo:
        runner.characterize_library(config, "tt", "/nonexistent-pdk",
                                    lib_path=tmp_path / "out.lib",
                                    records_dir=tmp_path / "records")

    assert "boom: missing cell arc" in str(excinfo.value)
    assert scratch_names() == before
