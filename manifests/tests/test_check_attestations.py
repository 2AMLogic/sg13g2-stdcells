"""Tests for manifests/check_attestations.py (issues #103 and #116).

The checker walks every envelope under manifests/envelopes/, collects each
recorded (path, content_hash) pair -- from attestation.checks[] and from both
provenance.input shapes -- and fails if any committed file at that path hashes
differently (#103). With --manifest it instead compares every block-manifest
evidence pin against the provenance.input.content_hash of the envelope the
pin names -- the aggregate the per-file walk deliberately skips (#116).
These tests pin both contracts, including the negative controls: a gate that
cannot fail is not evidence.
"""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_attestations as ca


def sha(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def present_check(rel: str, content: bytes) -> dict:
    return {
        "check": "present",
        "role": "hygiene",
        "path": rel,
        "passed": True,
        "content_hash": sha(content),
    }


def single_shape_envelope(rel: str, content: bytes, checks=()) -> dict:
    return {
        "schema_version": 1,
        "kind": "generic",
        "status": "pass",
        "attestation": {"producer": "klt signoff --attest", "checks": list(checks)},
        "provenance": {
            "input": {
                "path": {"path": rel, "scope": "repo"},
                "content_hash": sha(content),
            }
        },
    }


def list_shape_envelope(entries: list, aggregate: str, checks=()) -> dict:
    return {
        "schema_version": 1,
        "kind": "generic",
        "status": "pass",
        "attestation": {"producer": "klt signoff --attest", "checks": list(checks)},
        "provenance": {"input": {"paths": entries, "content_hash": aggregate}},
    }


def list_entry(rel: str, content: bytes) -> dict:
    return {"path": {"path": rel, "scope": "repo"}, "content_hash": sha(content)}


def make_repo(tmp_path: Path, files: dict, envelopes: dict):
    """Write files and envelopes into a fake repo root; return (root, env_dir)."""
    root = tmp_path / "repo"
    env_dir = root / "envelopes"
    env_dir.mkdir(parents=True)
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
    for name, envelope in envelopes.items():
        (env_dir / name).write_text(json.dumps(envelope, indent=1) + "\n")
    return root, env_dir


def run(root: Path, env_dir: Path) -> int:
    return ca.main(["--repo-root", str(root), "--envelope-dir", str(env_dir)])


def test_matching_envelope_passes(tmp_path):
    root, env_dir = make_repo(
        tmp_path,
        {"docs/README.md": b"# hello\n"},
        {"item.attest.json": single_shape_envelope("docs/README.md", b"# hello\n")},
    )
    assert run(root, env_dir) == 0


def test_no_trailing_newline_bytes_hash_raw(tmp_path):
    content = b"raw bytes without a trailing newline"
    root, env_dir = make_repo(
        tmp_path,
        {"f.txt": content},
        {"item.attest.json": single_shape_envelope("f.txt", content)},
    )
    assert run(root, env_dir) == 0


def test_corrupted_hash_fails_negative_control(tmp_path, capsys):
    root, env_dir = make_repo(
        tmp_path,
        {"README.md": b"one byte will change\n"},
        {"item.attest.json": single_shape_envelope("README.md", b"one byte will CHANGE\n")},
    )
    assert run(root, env_dir) == 1
    assert "README.md" in capsys.readouterr().err


def test_missing_path_fails_not_crashes(tmp_path, capsys):
    root, env_dir = make_repo(
        tmp_path,
        {},
        {"item.attest.json": single_shape_envelope("gone/file.txt", b"x")},
    )
    assert run(root, env_dir) == 1
    assert "does not exist" in capsys.readouterr().err


def test_both_provenance_shapes_parsed(tmp_path):
    files = {"a.txt": b"a", "b.txt": b"b", "inv.json": b"{}"}
    envelopes = {
        "itemA.attest.json": single_shape_envelope("inv.json", b"{}"),
        "itemB.attest.json": list_shape_envelope(
            [list_entry("a.txt", b"a"), list_entry("b.txt", b"b")],
            aggregate="sha256:" + "ab" * 32,
        ),
    }
    root, env_dir = make_repo(tmp_path, files, envelopes)
    assert run(root, env_dir) == 0


def test_list_shape_aggregate_hash_is_not_a_file_hash(tmp_path):
    # The paths[] shape carries an aggregate provenance.input.content_hash over
    # the whole input set. It has no single path; treating it as one would make
    # every list-shape envelope fail. It must be skipped.
    files = {"a.txt": b"a"}
    envelopes = {
        "item.attest.json": list_shape_envelope(
            [list_entry("a.txt", b"a")], aggregate=sha(b"not any file")
        )
    }
    root, env_dir = make_repo(tmp_path, files, envelopes)
    assert run(root, env_dir) == 0


def test_unparseable_provenance_shape_fails(tmp_path):
    envelope = single_shape_envelope("f.txt", b"f")
    envelope["provenance"]["input"] = {}
    root, env_dir = make_repo(tmp_path, {"f.txt": b"f"}, {"item.attest.json": envelope})
    assert run(root, env_dir) == 2


def test_malformed_content_hash_fails(tmp_path):
    envelope = single_shape_envelope("f.txt", b"f")
    envelope["provenance"]["input"]["content_hash"] = "deadbeef"
    root, env_dir = make_repo(tmp_path, {"f.txt": b"f"}, {"item.attest.json": envelope})
    assert run(root, env_dir) == 2


def test_invalid_json_fails(tmp_path):
    root, env_dir = make_repo(tmp_path, {}, {})
    (env_dir / "broken.attest.json").write_text("{not json")
    assert run(root, env_dir) == 2


def test_zero_hash_envelope_fails_not_vacuously(tmp_path):
    envelope = list_shape_envelope(
        [],
        aggregate=sha(b""),
        checks=[
            {"check": "command", "role": "audit", "name": "c", "argv": ["true"], "passed": True}
        ],
    )
    root, env_dir = make_repo(tmp_path, {}, {"item.attest.json": envelope})
    assert run(root, env_dir) == 2


def test_duplicate_records_are_deduplicated(tmp_path):
    content = b"same"
    envelope = single_shape_envelope(
        "f.txt", content, checks=[present_check("f.txt", content)]
    )
    root, env_dir = make_repo(tmp_path, {"f.txt": content}, {"item.attest.json": envelope})
    records = ca.collect_records(envelope, "item.attest.json")
    assert len(records) == 2
    unique, mismatches = ca.verify_records(envelope, "item.attest.json", root)
    assert unique == 1
    assert mismatches == []


# -- --manifest mode (issue #116) --------------------------------------------
#
# The block manifest pins, per evidence key, the provenance.input.content_hash
# of the envelope it names. Issue #116: PR #112 re-minted item1.analog.attest
# .json and did not re-point the manifest's pin, so main published T1 11/22
# while its own grader computed 10/22 -- and no CI stage could see it, because
# the envelope walk skips exactly the aggregate field the pin names.

MANIFEST_NAME = "block.json"


def write_manifest(root: Path, manifest: dict) -> Path:
    path = root / MANIFEST_NAME
    path.write_text(json.dumps(manifest, indent=1) + "\n")
    return path


def run_manifest(root: Path, manifest: Path) -> int:
    return ca.main(["--manifest", str(manifest), "--repo-root", str(root)])


def run_evidence(root: Path, evidence: dict) -> int:
    manifest = write_manifest(root, {"block": "fake", "evidence": evidence})
    return run_manifest(root, manifest)


@pytest.fixture
def single_envelope_repo(tmp_path):
    root, _ = make_repo(
        tmp_path,
        {"f.txt": b"f"},
        {"item.attest.json": single_shape_envelope("f.txt", b"f")},
    )
    return root


@pytest.fixture
def empty_repo(tmp_path):
    return make_repo(tmp_path, {}, {})[0]


def test_real_committed_manifest_pins_match_envelopes():
    manifest = Path(__file__).resolve().parents[1] / "sg13g2-stdcells.json"
    repo_root = Path(__file__).resolve().parents[2]
    assert run_manifest(repo_root, manifest) == 0


def test_manifest_pin_match_passes_both_provenance_shapes(tmp_path):
    files = {"design/gen.py": b"gen", "a.txt": b"a", "b.txt": b"b"}
    envelopes = {
        "item1.attest.json": list_shape_envelope(
            [list_entry("a.txt", b"a"), list_entry("b.txt", b"b")],
            aggregate="sha256:" + "ab" * 32,
        ),
        "item9.attest.json": single_shape_envelope("design/gen.py", b"gen"),
    }
    root, _ = make_repo(tmp_path, files, envelopes)
    evidence = {
        "1.analog": {
            "file": "envelopes/item1.attest.json",
            "content_hash": "sha256:" + "ab" * 32,
        },
        "9.digital": {
            "file": "envelopes/item9.attest.json",
            "content_hash": sha(b"gen"),
        },
    }
    assert run_evidence(root, evidence) == 0


@pytest.fixture
def item6_documents(tmp_path):
    spec = b"Status: RATIFIED\r\n"
    statement = b'{"rows": []}\n'
    (tmp_path / "spec.md").write_bytes(spec)
    (tmp_path / "statement.json").write_bytes(statement)
    return {
        "spec": {
            "file": "spec.md",
            "content_hash": sha(spec),
            "format": "markdown-table",
            "id_column": "#",
        },
        "statement": {"file": "statement.json", "content_hash": sha(statement)},
    }


def run_item6_manifest(root, documents):
    return run_evidence(root, {"6.digital": {"not_applicable": documents}})


def test_not_applicable_document_pins_match(tmp_path, item6_documents, capsys):
    assert run_item6_manifest(tmp_path, item6_documents) == 0
    assert "2 evidence pins" in capsys.readouterr().out


@pytest.mark.parametrize("document", ["spec", "statement"])
def test_not_applicable_missing_file(tmp_path, item6_documents, document, capsys):
    rel = item6_documents[document]["file"]
    (tmp_path / rel).unlink()
    assert run_item6_manifest(tmp_path, item6_documents) == 2
    err = capsys.readouterr().err
    assert f'evidence["6.digital"].not_applicable.{document}' in err
    assert rel in err


@pytest.mark.parametrize("document", ["spec", "statement"])
def test_not_applicable_changed_document(tmp_path, item6_documents, document, capsys):
    pin = item6_documents[document]
    path = tmp_path / pin["file"]
    path.write_bytes(path.read_bytes() + b"\n")
    assert run_item6_manifest(tmp_path, item6_documents) == 1
    err = capsys.readouterr().err
    assert f'evidence["6.digital"].not_applicable.{document}' in err
    assert pin["content_hash"] in err
    assert sha(path.read_bytes()) in err


@pytest.mark.parametrize("document", ["spec", "statement"])
def test_not_applicable_requires_both_documents(
    tmp_path, item6_documents, document, capsys
):
    del item6_documents[document]
    assert run_item6_manifest(tmp_path, item6_documents) == 2
    assert f'evidence["6.digital"].not_applicable.{document}' in capsys.readouterr().err


@pytest.mark.parametrize("document", ["spec", "statement"])
def test_not_applicable_malformed_pin(tmp_path, item6_documents, document, capsys):
    item6_documents[document]["content_hash"] = "deadbeef"
    assert run_item6_manifest(tmp_path, item6_documents) == 2
    err = capsys.readouterr().err
    assert f'evidence["6.digital"].not_applicable.{document}' in err
    assert "content_hash" in err


def test_manifest_pin_mismatch_fails_naming_key_envelope_and_digests(tmp_path, capsys):
    # Negative control: the #116 defect itself -- pin points at a stale
    # aggregate while the envelope is fresh. The failure must name the
    # manifest key, the envelope path, and both digests.
    files = {"a.txt": b"a", "b.txt": b"b"}
    envelopes = {
        "item1.attest.json": list_shape_envelope(
            [list_entry("a.txt", b"a"), list_entry("b.txt", b"b")],
            aggregate="sha256:" + "ab" * 32,
        )
    }
    root, _ = make_repo(tmp_path, files, envelopes)
    evidence = {
        "1.analog": {
            "file": "envelopes/item1.attest.json",
            "content_hash": "sha256:" + "cd" * 32,
        },
    }
    assert run_evidence(root, evidence) == 1
    err = capsys.readouterr().err
    assert 'evidence["1.analog"]' in err
    assert "envelopes/item1.attest.json" in err
    assert "sha256:" + "cd" * 32 in err  # expected: the pin
    assert "sha256:" + "ab" * 32 in err  # actual: the envelope's aggregate
    assert "klt signoff --attest" in err  # the message names the repair


def test_manifest_single_input_envelope_pin_mismatch_fails(
    single_envelope_repo, capsys
):
    pin = {"file": "envelopes/item.attest.json", "content_hash": sha(b"not f")}
    assert run_evidence(single_envelope_repo, {"9.digital": pin}) == 1
    err = capsys.readouterr().err
    assert 'evidence["9.digital"]' in err


def test_manifest_bare_path_entries_are_skipped_not_errors(
    single_envelope_repo, capsys
):
    # Several evidence entries today are bare path strings or lists of them
    # (e.g. 4.digital); they record locations without a pin and must not
    # trip the check. One object pin rides along so the manifest is checkable
    # at all -- a manifest with no pins at all is the zero-pin error (#129).
    evidence = {
        "1.digital": "flow/records/r/synthesize.json",
        "3.analog": "layout/drc/cell.json",
        "4.analog": ["layout/lvs/cell_1.json", "layout/lvs/cell_2.json"],
        "11.digital": ["flow/records/r/erc.json"],
        "9.digital": {"file": "envelopes/item.attest.json", "content_hash": sha(b"f")},
    }
    assert run_evidence(single_envelope_repo, evidence) == 0
    assert capsys.readouterr().err == ""


def netlist_report_envelope(netlist_rel: str, content: bytes) -> dict:
    # The klt sim report shape item 5's analog citations name: a JSON
    # envelope whose provenance.input.content_hash pins the netlist the
    # run consumed (role: netlist).
    return {
        "schema_version": 3,
        "status": "pass",
        "provenance": {
            "input": {
                "content_hash": sha(content),
                "role": "netlist",
                "path": {"path": netlist_rel, "scope": "repo"},
            }
        },
    }


@pytest.fixture
def item5_reports(tmp_path):
    netlists = {"a": b"a netlist", "b": b"b netlist"}
    files = {f"sim/records/{name}.spice": content for name, content in netlists.items()}
    for name, content in netlists.items():
        report = netlist_report_envelope(f"sim/records/{name}.spice", content)
        files[f"sim/records/{name}.report.json"] = (json.dumps(report, indent=1) + "\n").encode()
    return make_repo(tmp_path, files, {})[0]


def run_item5_manifest(root, pins):
    return run_evidence(root, {"5.analog": pins})


def test_manifest_list_of_pinned_objects_checked_and_counted(item5_reports, capsys):
    # #220: item-5 analog evidence is a list of {file, content_hash, rows}
    # citations. Each element pins the provenance.input.content_hash of the
    # report envelope it names -- the same comparison a top-level object
    # pin gets -- and each must be checked and counted instead of the whole
    # list being skipped.
    assert run_item5_manifest(
        item5_reports,
        [
            {"file": "sim/records/a.report.json",
             "content_hash": sha(b"a netlist"), "rows": ["9"]},
            {"file": "sim/records/b.report.json",
             "content_hash": sha(b"b netlist"), "rows": ["9"]},
        ],
    ) == 0
    assert "2 evidence pins" in capsys.readouterr().out


def test_manifest_list_of_pinned_objects_wrong_pin_fails(item5_reports, capsys):
    assert run_item5_manifest(
        item5_reports,
        [
            {"file": "sim/records/a.report.json",
             "content_hash": sha(b"a netlist")},
            {"file": "sim/records/b.report.json",
             "content_hash": sha(b"tampered")},
        ],
    ) == 1
    err = capsys.readouterr().err
    assert 'evidence["5.analog"][1]' in err
    assert "sim/records/b.report.json" in err
    assert sha(b"tampered") in err
    assert sha(b"b netlist") in err


def test_manifest_list_pinned_object_naming_missing_report_fails(empty_repo, capsys):
    pins = [{"file": "sim/records/gone.report.json", "content_hash": sha(b"x")}]
    assert run_item5_manifest(empty_repo, pins) == 2
    err = capsys.readouterr().err
    assert 'evidence["5.analog"][0]' in err
    assert "does not exist" in err


def test_manifest_list_pinned_object_naming_non_json_report_fails(
    tmp_path, capsys
):
    root, _ = make_repo(tmp_path, {"sim/records/plain.report.json": b"not json"}, {})
    pins = [{"file": "sim/records/plain.report.json", "content_hash": sha(b"x")}]
    assert run_item5_manifest(root, pins) == 2
    err = capsys.readouterr().err
    assert 'evidence["5.analog"][0]' in err
    assert "not valid JSON" in err


def test_manifest_mixed_list_strings_and_pinned_objects(item5_reports, capsys):
    # A list may mix bare path strings with pinned objects: element by
    # element, strings are skipped as locations without a pin, objects are
    # checked (#220).
    assert run_item5_manifest(
        item5_reports,
        [
            "sim/records/old-run/a.report.json",
            {"file": "sim/records/a.report.json",
             "content_hash": sha(b"a netlist")},
        ],
    ) == 0
    assert "1 evidence pins" in capsys.readouterr().out


@pytest.mark.parametrize(
    "element",
    [
        {"file": "sim/records/a.report.json"},
        {"file": "sim/records/a.report.json", "content_hash": "deadbeef"},
        42,
        None,
        [["too deep"]],
    ],
)
def test_manifest_list_malformed_element_exits_2_not_traceback(
    item5_reports, capsys, element
):
    # A malformed list element -- an object missing its pin fields, a bad
    # hash format, or a non-string/non-object element -- is a structural
    # error (exit 2) naming the key and the element index, never a
    # traceback.
    assert run_item5_manifest(item5_reports, [element]) == 2
    assert 'evidence["5.analog"][0]' in capsys.readouterr().err


def test_manifest_nested_group_pins_checked_and_counted(item5_reports, capsys):
    # Item 11's analog evidence is a list of cited groups, each a list of a
    # pinned record plus bare paths. A group's pinned object is checked and
    # counted; its bare strings are locations without a pin.
    group = [
        {"file": "sim/records/a.report.json", "content_hash": sha(b"a netlist")},
        "sim/records/b.report.json",
    ]
    assert run_item5_manifest(item5_reports, [group]) == 0
    assert "1 evidence pins" in capsys.readouterr().out


def test_manifest_nested_group_wrong_pin_fails_naming_group(item5_reports, capsys):
    group = [{"file": "sim/records/a.report.json", "content_hash": sha(b"x")}]
    assert run_item5_manifest(item5_reports, [group]) == 1
    assert 'evidence["5.analog"][0][0]' in capsys.readouterr().err


def test_manifest_empty_or_string_only_list_still_pins_nothing(empty_repo, capsys):
    # Edge cases (#220 test plan): an empty list and a string-only list pin
    # nothing -- skipped element by element -- so a manifest with no other
    # pins still hits the zero-pin error (#129).
    evidence = {"5.analog": [], "11.digital": ["flow/records/r/erc.json"]}
    assert run_evidence(empty_repo, evidence) == 2
    assert "no evidence pins" in capsys.readouterr().err


def test_manifest_with_zero_pins_fails_not_vacuously(empty_repo, capsys):
    # Negative control (#129): a manifest whose evidence carries only bare
    # path strings and lists pins nothing, so the run verifies nothing -- the
    # sibling of an empty envelope dir in the default mode. It must exit 2
    # naming the manifest, never print the success line.
    evidence = {
        "1.digital": "flow/records/r/synthesize.json",
        "4.analog": ["layout/lvs/cell_1.json", "layout/lvs/cell_2.json"],
    }
    assert run_evidence(empty_repo, evidence) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert MANIFEST_NAME in captured.err
    assert "no evidence pins" in captured.err


def test_manifest_missing_file_exits_2_not_traceback(empty_repo, capsys):
    # #129 gap 2: a --manifest path that does not exist must report a
    # readable error and exit 2, not traceback with FileNotFoundError (exit 1).
    missing = empty_repo / "does-not-exist.json"
    assert run_manifest(empty_repo, missing) == 2
    err = capsys.readouterr().err
    assert err.strip()
    assert "cannot read" in err
    assert "does-not-exist.json" in err


def test_manifest_directory_path_exits_2_not_traceback(empty_repo, capsys):
    d = empty_repo / "a-directory"
    d.mkdir()
    assert run_manifest(empty_repo, d) == 2
    assert "cannot read" in capsys.readouterr().err


def test_manifest_non_utf8_file_exits_2_not_traceback(empty_repo, capsys):
    path = empty_repo / "binary.json"
    path.write_bytes(b"\x80\x81\xfe\xff")
    assert run_manifest(empty_repo, path) == 2
    assert "cannot read" in capsys.readouterr().err


def test_manifest_invalid_json_keeps_specific_message(empty_repo, capsys):
    # Regression: a readable file holding invalid JSON keeps the existing
    # "not valid JSON" message rather than the generic "cannot read" one.
    path = empty_repo / "broken.json"
    path.write_text("{not json")
    assert run_manifest(empty_repo, path) == 2
    err = capsys.readouterr().err
    assert "not valid JSON" in err
    assert "cannot read" not in err


def test_manifest_naming_missing_envelope_fails_loudly(empty_repo, capsys):
    pin = {"file": "envelopes/gone.attest.json", "content_hash": sha(b"x")}
    assert run_evidence(empty_repo, {"2.digital": pin}) == 2
    err = capsys.readouterr().err
    assert 'evidence["2.digital"]' in err
    assert "envelopes/gone.attest.json" in err
    assert "does not exist" in err


def test_manifest_object_entry_without_content_hash_fails_loudly(
    single_envelope_repo, capsys
):
    evidence = {"9.digital": {"file": "envelopes/item.attest.json"}}
    assert run_evidence(single_envelope_repo, evidence) == 2
    assert 'evidence["9.digital"]' in capsys.readouterr().err


def test_manifest_malformed_pin_fails_loudly(single_envelope_repo):
    pin = {"file": "envelopes/item.attest.json", "content_hash": "deadbeef"}
    assert run_evidence(single_envelope_repo, {"9.digital": pin}) == 2


def test_manifest_naming_unparseable_envelope_fails_loudly(empty_repo, capsys):
    (empty_repo / "envelopes" / "broken.attest.json").write_text("{not json")
    pin = {"file": "envelopes/broken.attest.json", "content_hash": sha(b"x")}
    assert run_evidence(empty_repo, {"1.analog": pin}) == 2
    assert "broken.attest.json" in capsys.readouterr().err


def test_manifest_without_evidence_object_fails_loudly(empty_repo, capsys):
    manifest = write_manifest(empty_repo, {"block": "fake"})
    assert run_manifest(empty_repo, manifest) == 2
    assert "no evidence object" in capsys.readouterr().err


@pytest.mark.parametrize("raw", ["[]\n", "null\n", '"s"\n', "42\n"])
def test_manifest_non_object_top_level_fails_loudly(empty_repo, capsys, raw):
    # #137 site 1: a readable manifest holding valid JSON whose top level
    # is not an object must report rc 2 with a clean message naming the
    # file, never an AttributeError traceback.
    path = empty_repo / "nonobject.json"
    path.write_text(raw)  # write_manifest() can't produce a non-object top level
    assert run_manifest(empty_repo, path) == 2
    err = capsys.readouterr().err
    assert "nonobject.json: top level is not a JSON object" in err
    assert "Traceback" not in err


def test_manifest_naming_non_object_envelope_fails_loudly(empty_repo, capsys):
    # #137 site 2: a pin naming an envelope whose top level is not an
    # object must report rc 2 with a clean message naming that envelope,
    # never a traceback.
    (empty_repo / "envelopes" / "list.attest.json").write_text("[]\n")
    pin = {"file": "envelopes/list.attest.json", "content_hash": sha(b"x")}
    assert run_evidence(empty_repo, {"1.analog": pin}) == 2
    err = capsys.readouterr().err
    assert "list.attest.json: top level is not a JSON object" in err
    assert "Traceback" not in err


def test_manifest_mode_does_not_walk_the_envelope_dir(tmp_path):
    # --manifest is its own CI stage; it checks pins only, so an unrelated
    # stale envelope in the envelope dir must not fail it (the attestations
    # stage owns envelope-vs-tree).
    files = {"f.txt": b"f"}
    stale = single_shape_envelope("f.txt", b"CHANGED")  # stale member hash
    root, env_dir = make_repo(tmp_path, files, {"stale.attest.json": stale})
    pin = {"file": "envelopes/stale.attest.json", "content_hash": sha(b"CHANGED")}
    assert run(root, env_dir) == 1  # envelope walk sees the staleness
    assert run_evidence(root, {"9.digital": pin}) == 0  # the pin matches the aggregate


def test_diverging_hashes_for_one_path_fail(tmp_path):
    content = b"same"
    envelope = single_shape_envelope(
        "f.txt", content, checks=[present_check("f.txt", b"other bytes")]
    )
    root, env_dir = make_repo(tmp_path, {"f.txt": content}, {"item.attest.json": envelope})
    assert run(root, env_dir) == 1


def test_parse_content_hash_rejects_bad_digests():
    with pytest.raises(ca.EnvelopeError):
        ca._parse_content_hash("sha256:xyz", "e", "w")
    with pytest.raises(ca.EnvelopeError):
        ca._parse_content_hash("sha256:" + "0" * 63, "e", "w")
    with pytest.raises(ca.EnvelopeError):
        ca._parse_content_hash("md5:" + "0" * 64, "e", "w")
    assert ca._parse_content_hash("sha256:" + "a" * 64, "e", "w") == "a" * 64


def test_real_repo_envelopes_all_match():
    # The committed tree must satisfy its own gate; this also proves the walker
    # finds a non-zero number of recorded hashes in the real envelopes.
    assert ca.main([]) == 0


# -- Focused item-9 PDK pin vs the measurement sidecar (issue #178) -----------
#
# The analog item-9 inventory pins the PDK its measurement consumed; the
# envelope records that pin resolved, and the measurement's own sidecar
# (views/*.lib.provenance) records the revision the runner captured. The
# focused check compares them, so an inventory edited (or re-attested) against
# a different PDK than the committed view was measured with fails CI even
# though every content_hash still matches.

PIN = {"name": "IHP-Open-PDK", "revision": "5" * 40}


def item9_envelope(pdk_value=None, include_pin_check=True, inventory=b'{"pins": {}}'):
    checks = []
    if include_pin_check:
        value = pdk_value if pdk_value is not None else dict(PIN)
        checks.append({"check": "pin", "role": "pdk", "passed": True, "value": value})
    envelope = single_shape_envelope("inv/item9.json", inventory, checks=checks)
    envelope["t1_item"] = 9
    return envelope


def run_item9(tmp_path, envelope, sidecar="default") -> int:
    files = {"inv/item9.json": b'{"pins": {}}'}
    if sidecar is not None:
        doc = {"pdk": dict(PIN)} if sidecar == "default" else sidecar
        files["views/sg13g2_stdcells_tt.lib.provenance"] = (json.dumps(doc) + "\n").encode()
    root, env_dir = make_repo(tmp_path, files, {"item9.attest.json": envelope})
    return run(root, env_dir)


def test_item9_pdk_pin_matching_sidecar_passes(tmp_path):
    assert run_item9(tmp_path, item9_envelope()) == 0


def test_item9_pdk_pin_disagreeing_with_sidecar_fails(tmp_path, capsys):
    # The inventory revision moved (re-attested against another PDK) while
    # the committed measurement still cites the old one: every content_hash
    # matches, only the focused check sees it.
    envelope = item9_envelope(pdk_value={"name": "IHP-Open-PDK", "revision": "b" * 40})
    assert run_item9(tmp_path, envelope) == 1
    err = capsys.readouterr().err
    assert "item9.attest.json" in err and "was not taken against" in err, err


def test_item9_pdk_pin_name_disagreement_fails(tmp_path):
    envelope = item9_envelope(pdk_value={"name": "other-pdk", "revision": PIN["revision"]})
    assert run_item9(tmp_path, envelope) == 1


def test_item9_pin_against_sidecar_without_pdk_pin_fails(tmp_path):
    # The measurement predates the PDK pin: the sidecar records none, so the
    # inventory pins a PDK the committed view was not measured against.
    assert run_item9(tmp_path, item9_envelope(), sidecar={}) == 1


def test_item9_none_pdk_form_skips_sidecar_comparison(tmp_path):
    # The digital partition's no-PDK form consumes no PDK; there is nothing
    # to compare and no sidecar is required.
    envelope = item9_envelope(pdk_value={"none": True, "reason": "behavioral RTL"})
    assert run_item9(tmp_path, envelope, sidecar=None) == 0


def test_item9_envelope_without_pdk_pin_check_is_an_error(tmp_path):
    # Silence never means "no PDK": an item-9 envelope recording no pdk pin
    # check is malformed, not vacuously passing.
    assert run_item9(tmp_path, item9_envelope(include_pin_check=False)) == 2


def test_item9_pdk_pin_with_no_sidecar_to_compare_is_an_error(tmp_path):
    assert run_item9(tmp_path, item9_envelope(), sidecar=None) == 2
