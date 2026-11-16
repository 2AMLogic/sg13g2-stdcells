"""Liberty-view freshness check (issue #75).

The check backs T1 item 8's citation, so what matters is that it *fails* when
the evidence goes stale -- a freshness command that cannot fail is not
evidence. Every case below mutates one artifact and asserts the drift is
reported.

Run from the repo root:  python -m pytest sim/tests
"""

import json
import shutil
from pathlib import Path

import pytest

from sim.characterize import check_library

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REAL_LIB = REPO_ROOT / "views" / "sg13g2_stdcells_tt_1p20v_25c.lib"
REAL_SIDECAR = Path(str(REAL_LIB) + ".provenance")


def _committed_record() -> Path:
    """The record the committed sidecar names, so the fixture cannot drift from it."""
    prov = json.loads(REAL_SIDECAR.read_text())
    return REPO_ROOT / "sim" / "characterize" / "records" / f"{prov['evidence_record']}.md"


REAL_RECORD = _committed_record()


@pytest.fixture
def tree(tmp_path):
    """A miniature repo copied from the committed artifacts, which are fresh.

    The committed Liberty view, sidecar, config and record agree -- the view
    was regenerated for issue #82, so the sidecar's pin matches the committed
    config and no swap is needed. The baseline is fresh and each test below
    isolates a single mutation.
    """
    root = tmp_path
    (root / "views").mkdir()
    (root / "layout").mkdir()
    records = root / "sim" / "characterize" / "records"
    records.mkdir(parents=True)

    lib = root / "views" / REAL_LIB.name
    shutil.copy(REAL_LIB, lib)
    shutil.copy(REAL_RECORD, records / REAL_RECORD.name)
    shutil.copy(REPO_ROOT / "layout" / "example_config.json",
                root / "layout" / "example_config.json")
    shutil.copy(REAL_SIDECAR, Path(str(lib) + ".provenance"))

    return root, lib, records


def run(tree):
    root, lib, records = tree
    return check_library.check(lib, repo_root=root, records_dir=records)


def edit_sidecar(lib, **changes):
    path = Path(str(lib) + ".provenance")
    prov = json.loads(path.read_text())
    prov.update(changes)
    path.write_text(json.dumps(prov, indent=2, sort_keys=True) + "\n")


def test_baseline_is_fresh(tree):
    assert run(tree) == []


def test_config_edit_is_drift(tree):
    # The characterization pins the config's bytes; an edit invalidates the pin.
    root, lib, _ = tree
    config = root / "layout" / "example_config.json"
    config.write_text(config.read_text().replace('"l_nm": 130', '"l_nm": 150'))
    problems = run(tree)
    assert any("example_config.json" in p and "sha256" in p for p in problems), problems


def test_missing_config_is_drift(tree):
    root, _, _ = tree
    (root / "layout" / "example_config.json").unlink()
    assert any("missing" in p for p in run(tree))


def test_hand_edited_lib_losing_a_cell_is_drift(tree):
    # A view that no longer holds a cell the sidecar claims was characterized.
    _, lib, _ = tree
    text = lib.read_text().replace("cell (sg13g2_nand2_1)", "cell (sg13g2_nand2_XX)")
    lib.write_text(text)
    assert any("sg13g2_nand2_1" in p for p in run(tree))


def test_renamed_library_is_drift(tree):
    _, lib, _ = tree
    edit_sidecar(lib, library="some_other_library")
    assert any("some_other_library" in p for p in run(tree))


def test_hand_edited_lib_voltage_is_drift(tree):
    # An attribute tampered in the view itself, library name and cell set
    # untouched: the corner comparison is what catches it (issue #119).
    _, lib, _ = tree
    text = lib.read_text().replace("nom_voltage : 1.2;", "nom_voltage : 3.3;")
    lib.write_text(text)
    problems = run(tree)
    assert any("nom_voltage" in p and "3.3" in p for p in problems), problems


def test_hand_edited_lib_temperature_is_drift(tree):
    _, lib, _ = tree
    text = lib.read_text().replace("nom_temperature : 25;", "nom_temperature : 125;")
    lib.write_text(text)
    assert any("125" in p for p in run(tree))


def test_hand_edited_lib_operating_conditions_name_is_drift(tree):
    _, lib, _ = tree
    text = lib.read_text().replace("operating_conditions (tt) {",
                                   "operating_conditions (ff) {")
    lib.write_text(text)
    assert any("ff" in p for p in run(tree))


def test_hand_edited_lib_operating_conditions_voltage_is_drift(tree):
    # The group's voltage is compared as well as the nom_* attribute, so a
    # tamper that touches only the group is still caught.
    _, lib, _ = tree
    text = lib.read_text().replace("\n    voltage : 1.2;", "\n    voltage : 3.3;")
    lib.write_text(text)
    problems = run(tree)
    assert any("operating_conditions(tt) voltage" in p and "3.3" in p
               for p in problems), problems


def test_view_process_factor_is_deliberately_unchecked(tree):
    # The sidecar's corner.process is a process-corner *name* (mos_tt) while
    # the view's process attributes are numeric process factors -- not
    # comparable, so process is deliberately not pinned (issue #119).
    _, lib, _ = tree
    text = lib.read_text().replace("nom_process : 1;", "nom_process : 0.9;")
    lib.write_text(text)
    assert run(tree) == []


def test_missing_evidence_record_is_drift(tree):
    _, _, records = tree
    (records / REAL_RECORD.name).unlink()
    assert any("evidence record" in p for p in run(tree))


def test_record_without_the_claimed_corner_is_drift(tree):
    _, lib, _ = tree
    edit_sidecar(lib, corner={"name": "ss", "process": "mos_ss",
                              "supply_v": 1.08, "temperature_c": 125.0})
    assert any("corner" in p for p in run(tree))


def test_record_measured_only_at_another_corner_is_drift(tree):
    # Every block was measured at ss, but one stray line elsewhere in the record
    # mentions the claimed corner -- cell and corner must match inside one block.
    _, _, records = tree
    record = records / REAL_RECORD.name
    text = record.read_text().replace("- **Corner**: tt", "- **Corner**: ss")
    record.write_text(text + "\nCorner note: **Corner**: tt\n")
    assert any("corner" in p for p in run(tree))


def test_cell_present_only_in_a_provenance_path_is_drift(tree):
    # The name survives only inside a **Netlist provenance** path line -- that is
    # not a measurement, so the record does not speak for the cell.
    _, _, records = tree
    record = records / REAL_RECORD.name
    record.write_text(record.read_text().replace("- **Cell**: sg13g2_inv_4\n", ""))
    assert any("sg13g2_inv_4" in p for p in run(tree))


def test_record_measured_on_the_pdk_baseline_netlist_is_drift(tree):
    # The PDK-baseline record measures a *different* netlist's sg13g2_inv_1
    # (the benchmark denominator, characterized from sg13g2_stdcell.spice).
    # A sidecar pointing at it must not pass the cell test on the shared name.
    _, lib, records = tree
    shutil.copy(REPO_ROOT / "sim" / "characterize" / "records"
                / "20261105-042154-1376b8f.md", records / "20261105-042154-1376b8f.md")
    edit_sidecar(lib, evidence_record="20261105-042154-1376b8f")
    assert any("sg13g2_stdcell.spice" in p for p in run(tree))


def test_provenance_without_a_netlist_path_is_not_a_stand_in(tree):
    # A provenance that names no .spice file at all (e.g. layout-extracted
    # measurements) cannot be compared against <cell>.spice -- the checker
    # stays silent rather than rejecting evidence shapes it cannot judge.
    _, lib, records = tree
    record = records / REAL_RECORD.name
    text = record.read_text().replace(
        "- **Netlist provenance**: netlist supplied to klt characterize:",
        "- **Netlist provenance**: extracted from layout")
    record.write_text(text)
    assert not any(".spice" in p for p in run(tree))


def test_record_missing_a_cell_is_drift(tree):
    _, _, records = tree
    record = records / REAL_RECORD.name
    record.write_text(record.read_text().replace("sg13g2_inv_4", "sg13g2_inv_X"))
    assert any("sg13g2_inv_4" in p for p in run(tree))


def test_missing_sidecar_is_drift(tree):
    _, lib, _ = tree
    Path(str(lib) + ".provenance").unlink()
    assert any("sidecar is missing" in p for p in run(tree))


def test_unparseable_sidecar_is_drift(tree):
    _, lib, _ = tree
    Path(str(lib) + ".provenance").write_text("{not json")
    assert any("not parseable JSON" in p for p in run(tree))


def test_truncated_sidecar_is_drift(tree):
    _, lib, _ = tree
    Path(str(lib) + ".provenance").write_text(json.dumps({"library": "x"}) + "\n")
    assert any("lacks" in p for p in run(tree))


def test_dirty_sidecar_stamp_is_drift(tree):
    # A (dirty) repo_commit is not reproducible from any commit (issue #134).
    _, lib, _ = tree
    edit_sidecar(lib, repo_commit=f"{'a' * 40} (dirty)")
    problems = run(tree)
    assert any("repo_commit" in p and "(dirty)" in p for p in problems), problems


def test_dirty_record_stamp_is_drift(tree):
    # The measurement the sidecar cites itself stamps a dirty tree (issue #134).
    _, _, records = tree
    record = records / REAL_RECORD.name
    record.write_text("".join(
        line.rstrip("\n") + " (dirty)\n" if line.startswith("**Repo commit**") else line
        for line in record.read_text().splitlines(keepends=True)))
    problems = run(tree)
    assert any(REAL_RECORD.name in p and "(dirty)" in p for p in problems), problems


def test_sidecar_without_repo_commit_is_drift(tree):
    # Decided explicitly (issue #134): repo_commit is a REQUIRED_KEY, so
    # provenance without a stamp cannot pass unstated.
    _, lib, _ = tree
    prov = json.loads(Path(str(lib) + ".provenance").read_text())
    del prov["repo_commit"]
    Path(str(lib) + ".provenance").write_text(
        json.dumps(prov, indent=2, sort_keys=True) + "\n")
    assert any("repo_commit" in p for p in run(tree))


def test_dirty_stamp_with_trailing_whitespace_is_drift(tree):
    _, lib, _ = tree
    edit_sidecar(lib, repo_commit=f"{'a' * 40} (dirty)   ")
    assert any("(dirty)" in p for p in run(tree))


def test_commit_with_dirty_substring_outside_the_suffix_is_not_flagged(tree):
    # The predicate is anchored on the exact " (dirty)" suffix: a commit string
    # that merely contains "dirty" elsewhere is a clean stamp (issue #134).
    _, lib, _ = tree
    edit_sidecar(lib, repo_commit=f"dirty-{'a' * 40}")
    assert run(tree) == []


def test_record_without_a_commit_stamp_is_drift(tree):
    # The cited measurement's stamp is its reproducibility claim; a record
    # without the line names no tree it is reproducible from (issue #134).
    _, _, records = tree
    record = records / REAL_RECORD.name
    record.write_text("".join(
        line for line in record.read_text().splitlines(keepends=True)
        if not line.startswith("**Repo commit**")))
    assert any("Repo commit" in p for p in run(tree))


def test_writer_stamp_format_is_what_the_checker_rejects(tree):
    """The stamp the runner writes is the stamp the checker rejects (issue #134).

    In the spirit of `test_default_paths_match_runner`: writer and checker
    must read the one stamp definition in `harness.report`, so the `(dirty)`
    suffix cannot drift apart between the stamps `runner.py` emits (record
    line, sidecar `repo_commit`) and the predicate `check_library.py` applies.
    """
    from sim.characterize import runner

    root, _, _ = tree
    git = {"commit": "a" * 40, "short": "aaaaaaa", "branch": "main", "dirty": False}
    dirty = {**git, "dirty": True}

    record_text = runner.render("r", dirty, {"klt": {"version": "klt 0"},
                                            "backend": "local"}, [])
    line = next(l for l in record_text.splitlines() if l.startswith("**Repo commit**"))
    stamp = line.removeprefix("**Repo commit**: ")
    assert check_library.is_dirty_stamp(stamp)
    assert not check_library.is_dirty_stamp(runner.commit_stamp(git))

    lib_data = {"klt": {"version": "klt 0"}, "backend": "local",
                "cells": [{"cell": "c"}], "record_id": "r"}
    prov = runner.provenance_for(root / "layout" / "example_config.json",
                                 {"name": "tt"}, lib_data, git=dirty)
    assert check_library.is_dirty_stamp(prov["repo_commit"])


def test_committed_tree_is_fresh():
    """The committed tree IS fresh as of this issue-82 regeneration lap.

    The sidecar pins the committed ``example_config.json`` by whole-file
    SHA-256, so each merge from main that touches the pinned files re-stales
    the pin and each lap re-characterizes on the merged tree before any
    bookkeeping edit (record below, minted from the merge commit, clean).
    The refresh cleared the stale pin, so the assertion holds and CI fails
    on any future edit that re-stales the committed artifacts.
    """
    assert check_library.check(REAL_LIB) == []


def test_default_paths_match_runner():
    """The checker and the writer derive the same view and records paths.

    `runner.py` writes the view and records; `check_library.py` checks them.
    Both must resolve their defaults from the same single sources --
    `request.LIBRARY_NAME` and this package's own directory -- so a rename in
    the writer cannot leave the checker reporting on a path nobody produces.
    """
    from sim.characterize import runner

    assert check_library.DEFAULT_LIB == runner.DEFAULT_LIB
    assert check_library.RECORDS_DIR == runner.RECORDS_DIR
