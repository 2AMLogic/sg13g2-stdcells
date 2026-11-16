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


def list_shape_envelope(entries: list, aggregate: str) -> dict:
    return {
        "schema_version": 1,
        "kind": "generic",
        "status": "pass",
        "attestation": {"producer": "klt signoff --attest", "checks": []},
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
    root = tmp_path / "repo"
    env_dir = root / "envelopes"
    env_dir.mkdir(parents=True)
    (env_dir / "broken.attest.json").write_text("{not json")
    assert run(root, env_dir) == 2


def test_zero_hash_envelope_fails_not_vacuously(tmp_path):
    envelope = {
        "schema_version": 1,
        "kind": "generic",
        "status": "pass",
        "attestation": {
            "producer": "klt signoff --attest",
            "checks": [
                {"check": "command", "role": "audit", "name": "c", "argv": ["true"], "passed": True}
            ],
        },
        "provenance": {"input": {"paths": [], "content_hash": sha(b"")}},
    }
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


def test_real_committed_manifest_pins_match_envelopes():
    manifest = Path(__file__).resolve().parents[1] / "sg13g2-stdcells.json"
    repo_root = Path(__file__).resolve().parents[2]
    assert ca.main(["--manifest", str(manifest), "--repo-root", str(repo_root)]) == 0


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
    manifest = write_manifest(
        root,
        {
            "block": "fake",
            "evidence": {
                "1.analog": {
                    "file": "envelopes/item1.attest.json",
                    "content_hash": "sha256:" + "ab" * 32,
                },
                "9.digital": {
                    "file": "envelopes/item9.attest.json",
                    "content_hash": sha(b"gen"),
                },
            },
        },
    )
    assert run_manifest(root, manifest) == 0


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
    manifest = write_manifest(
        root,
        {
            "block": "fake",
            "evidence": {
                "1.analog": {
                    "file": "envelopes/item1.attest.json",
                    "content_hash": "sha256:" + "cd" * 32,
                }
            },
        },
    )
    assert run_manifest(root, manifest) == 1
    err = capsys.readouterr().err
    assert 'evidence["1.analog"]' in err
    assert "envelopes/item1.attest.json" in err
    assert "sha256:" + "cd" * 32 in err  # expected: the pin
    assert "sha256:" + "ab" * 32 in err  # actual: the envelope's aggregate
    assert "klt signoff --attest" in err  # the message names the repair


def test_manifest_single_input_envelope_pin_mismatch_fails(tmp_path, capsys):
    files = {"f.txt": b"f"}
    envelopes = {"item.attest.json": single_shape_envelope("f.txt", b"f")}
    root, _ = make_repo(tmp_path, files, envelopes)
    manifest = write_manifest(
        root,
        {
            "block": "fake",
            "evidence": {
                "9.digital": {
                    "file": "envelopes/item.attest.json",
                    "content_hash": sha(b"not f"),
                }
            },
        },
    )
    assert run_manifest(root, manifest) == 1
    err = capsys.readouterr().err
    assert 'evidence["9.digital"]' in err


def test_manifest_bare_path_entries_are_skipped_not_errors(tmp_path, capsys):
    # Several evidence entries today are bare path strings or lists of them
    # (e.g. 4.digital); they record locations without a pin and must not
    # trip the check. One object pin rides along so the manifest is checkable
    # at all -- a manifest with no pins at all is the zero-pin error (#129).
    files = {"f.txt": b"f"}
    envelopes = {"item.attest.json": single_shape_envelope("f.txt", b"f")}
    root, _ = make_repo(tmp_path, files, envelopes)
    manifest = write_manifest(
        root,
        {
            "block": "fake",
            "evidence": {
                "1.digital": "flow/records/r/synthesize.json",
                "3.analog": "layout/drc/cell.json",
                "4.analog": ["layout/lvs/cell_1.json", "layout/lvs/cell_2.json"],
                "11.digital": ["flow/records/r/erc.json"],
                "9.digital": {
                    "file": "envelopes/item.attest.json",
                    "content_hash": sha(b"f"),
                },
            },
        },
    )
    assert run_manifest(root, manifest) == 0
    assert capsys.readouterr().err == ""


def test_manifest_with_zero_pins_fails_not_vacuously(tmp_path, capsys):
    # Negative control (#129): a manifest whose evidence carries only bare
    # path strings and lists pins nothing, so the run verifies nothing -- the
    # sibling of an empty envelope dir in the default mode. It must exit 2
    # naming the manifest, never print the success line.
    root, _ = make_repo(tmp_path, {}, {})
    manifest = write_manifest(
        root,
        {
            "block": "fake",
            "evidence": {
                "1.digital": "flow/records/r/synthesize.json",
                "4.analog": ["layout/lvs/cell_1.json", "layout/lvs/cell_2.json"],
            },
        },
    )
    assert run_manifest(root, manifest) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert MANIFEST_NAME in captured.err
    assert "no evidence pins" in captured.err


def test_manifest_missing_file_exits_2_not_traceback(tmp_path, capsys):
    # #129 gap 2: a --manifest path that does not exist must report a
    # readable error and exit 2, not traceback with FileNotFoundError (exit 1).
    missing = tmp_path / "repo" / "does-not-exist.json"
    assert ca.main(["--manifest", str(missing), "--repo-root", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert err.strip()
    assert "cannot read" in err
    assert "does-not-exist.json" in err


def test_manifest_directory_path_exits_2_not_traceback(tmp_path, capsys):
    d = tmp_path / "repo" / "a-directory"
    d.mkdir(parents=True)
    assert ca.main(["--manifest", str(d), "--repo-root", str(tmp_path)]) == 2
    assert "cannot read" in capsys.readouterr().err


def test_manifest_non_utf8_file_exits_2_not_traceback(tmp_path, capsys):
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    path = root / "binary.json"
    path.write_bytes(b"\x80\x81\xfe\xff")
    assert ca.main(["--manifest", str(path), "--repo-root", str(root)]) == 2
    assert "cannot read" in capsys.readouterr().err


def test_manifest_invalid_json_keeps_specific_message(tmp_path, capsys):
    # Regression: a readable file holding invalid JSON keeps the existing
    # "not valid JSON" message rather than the generic "cannot read" one.
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    path = root / "broken.json"
    path.write_text("{not json")
    assert ca.main(["--manifest", str(path), "--repo-root", str(root)]) == 2
    err = capsys.readouterr().err
    assert "not valid JSON" in err
    assert "cannot read" not in err


def test_manifest_naming_missing_envelope_fails_loudly(tmp_path, capsys):
    root, _ = make_repo(tmp_path, {}, {})
    manifest = write_manifest(
        root,
        {
            "block": "fake",
            "evidence": {
                "2.digital": {
                    "file": "envelopes/gone.attest.json",
                    "content_hash": sha(b"x"),
                }
            },
        },
    )
    assert run_manifest(root, manifest) == 2
    err = capsys.readouterr().err
    assert 'evidence["2.digital"]' in err
    assert "envelopes/gone.attest.json" in err
    assert "does not exist" in err


def test_manifest_object_entry_without_content_hash_fails_loudly(tmp_path, capsys):
    files = {"f.txt": b"f"}
    envelopes = {"item.attest.json": single_shape_envelope("f.txt", b"f")}
    root, _ = make_repo(tmp_path, files, envelopes)
    manifest = write_manifest(
        root,
        {"block": "fake",
         "evidence": {"9.digital": {"file": "envelopes/item.attest.json"}}},
    )
    assert run_manifest(root, manifest) == 2
    assert 'evidence["9.digital"]' in capsys.readouterr().err


def test_manifest_malformed_pin_fails_loudly(tmp_path):
    files = {"f.txt": b"f"}
    envelopes = {"item.attest.json": single_shape_envelope("f.txt", b"f")}
    root, _ = make_repo(tmp_path, files, envelopes)
    manifest = write_manifest(
        root,
        {"block": "fake",
         "evidence": {"9.digital": {"file": "envelopes/item.attest.json",
                                    "content_hash": "deadbeef"}}},
    )
    assert run_manifest(root, manifest) == 2


def test_manifest_naming_unparseable_envelope_fails_loudly(tmp_path, capsys):
    root, _ = make_repo(tmp_path, {}, {})
    env_path = root / "envelopes" / "broken.attest.json"
    env_path.write_text("{not json")
    manifest = write_manifest(
        root,
        {"block": "fake",
         "evidence": {"1.analog": {"file": "envelopes/broken.attest.json",
                                   "content_hash": sha(b"x")}}},
    )
    assert run_manifest(root, manifest) == 2
    assert "broken.attest.json" in capsys.readouterr().err


def test_manifest_without_evidence_object_fails_loudly(tmp_path, capsys):
    root, _ = make_repo(tmp_path, {}, {})
    manifest = write_manifest(root, {"block": "fake"})
    assert run_manifest(root, manifest) == 2
    assert "no evidence object" in capsys.readouterr().err


@pytest.mark.parametrize("raw", ["[]\n", "null\n", '"s"\n', "42\n"])
def test_manifest_non_object_top_level_fails_loudly(tmp_path, capsys, raw):
    # #137 site 1: a readable manifest holding valid JSON whose top level
    # is not an object must report rc 2 with a clean message naming the
    # file, never an AttributeError traceback.
    root, _ = make_repo(tmp_path, {}, {})
    path = root / "nonobject.json"
    path.write_text(raw)  # write_manifest() can't produce a non-object top level
    assert ca.main(["--manifest", str(path), "--repo-root", str(root)]) == 2
    err = capsys.readouterr().err
    assert "nonobject.json: top level is not a JSON object" in err
    assert "Traceback" not in err


def test_manifest_naming_non_object_envelope_fails_loudly(tmp_path, capsys):
    # #137 site 2: a pin naming an envelope whose top level is not an
    # object must report rc 2 with a clean message naming that envelope,
    # never a traceback.
    root, _ = make_repo(tmp_path, {}, {})
    (root / "envelopes" / "list.attest.json").write_text("[]\n")
    manifest = write_manifest(
        root,
        {"block": "fake",
         "evidence": {"1.analog": {"file": "envelopes/list.attest.json",
                                   "content_hash": sha(b"x")}}},
    )
    assert run_manifest(root, manifest) == 2
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
    manifest = write_manifest(
        root,
        {"block": "fake",
         "evidence": {"9.digital": {"file": "envelopes/stale.attest.json",
                                    "content_hash": sha(b"CHANGED")}}},
    )
    assert run(root, env_dir) == 1  # envelope walk sees the staleness
    assert run_manifest(root, manifest) == 0  # the pin matches the aggregate


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
