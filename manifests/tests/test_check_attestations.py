"""Tests for manifests/check_attestations.py (issue #103).

The checker walks every envelope under manifests/envelopes/, collects each
recorded (path, content_hash) pair -- from attestation.checks[] and from both
provenance.input shapes -- and fails if any committed file at that path hashes
differently. These tests pin that contract, including the negative controls:
a gate that cannot fail is not evidence.
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
