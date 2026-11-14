"""Liberty-view freshness check (issue #75).

The check backs T1 item 8's citation, so what matters is that it *fails* when
the evidence goes stale -- a freshness command that cannot fail is not
evidence. Every case below mutates one artifact and asserts the drift is
reported.

Run from the repo root:  python -m pytest sim/tests
"""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from sim.characterize import check_library

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REAL_LIB = REPO_ROOT / "views" / "sg13g2_stdcells_tt_1p20v_25c.lib"
REAL_SIDECAR = Path(str(REAL_LIB) + ".provenance")
REAL_RECORD = REPO_ROOT / "sim" / "characterize" / "records" / "20261107-222836-6ee1577.md"


@pytest.fixture
def tree(tmp_path):
    """A miniature repo whose Liberty view, sidecar, config and record agree.

    Built from the committed artifacts, with the config replaced by one whose
    SHA-256 the sidecar actually pins -- so the baseline is fresh and each test
    below isolates a single mutation. (The committed tree itself is *not*
    fresh; see test_committed_tree_config_pin_is_stale.)
    """
    root = tmp_path
    (root / "views").mkdir()
    (root / "layout").mkdir()
    records = root / "sim" / "characterize" / "records"
    records.mkdir(parents=True)

    lib = root / "views" / REAL_LIB.name
    shutil.copy(REAL_LIB, lib)
    shutil.copy(REAL_RECORD, records / REAL_RECORD.name)

    config = root / "layout" / "example_config.json"
    config.write_bytes((REPO_ROOT / "layout" / "example_config.json").read_bytes())

    prov = json.loads(REAL_SIDECAR.read_text())
    prov["config"] = "layout/example_config.json"
    prov["config_sha256"] = hashlib.sha256(config.read_bytes()).hexdigest()
    Path(str(lib) + ".provenance").write_text(json.dumps(prov, indent=2, sort_keys=True) + "\n")

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


def test_missing_evidence_record_is_drift(tree):
    _, _, records = tree
    (records / REAL_RECORD.name).unlink()
    assert any("evidence record" in p for p in run(tree))


def test_record_without_the_claimed_corner_is_drift(tree):
    _, lib, _ = tree
    edit_sidecar(lib, corner={"name": "ss", "process": "mos_ss",
                              "supply_v": 1.08, "temperature_c": 125.0})
    assert any("corner" in p for p in run(tree))


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


def test_committed_tree_config_pin_is_stale(tree):
    """The committed tree is deliberately NOT fresh, and this records why.

    `layout/example_config.json` gained two `layout.rules` keys for the well
    and substrate taps (issue #73) after the Liberty view was characterized, so
    the sidecar's whole-file `config_sha256` no longer matches. Nothing the
    characterization consumes changed -- `process` and `cells` are byte
    identical -- but the sidecar pins the whole file, so the pin is stale. This
    is why T1 item 8 is not cited yet; see the PR for issue #75.

    When the view is regenerated (or the pin narrowed), this test is the thing
    that should fail, and the item 8 envelope can then be minted.
    """
    problems = check_library.check(REAL_LIB)
    assert len(problems) == 1, problems
    assert "example_config.json" in problems[0] and "sha256" in problems[0]
