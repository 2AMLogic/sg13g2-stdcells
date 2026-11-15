#!/usr/bin/env python3
"""Check every content_hash recorded under manifests/envelopes/ against the
committed file at its recorded path (issue #103).

An envelope written by `klt signoff --attest` records, per attested file, the
sha256 of the file's raw bytes. Nothing used to compare those hashes to the
tree, so an edit to an attested file left the envelope silently describing
bytes that no longer exist. This script re-hashes the committed files and
fails on any disagreement.

Covers both provenance shapes klt emits:

  - single input: provenance.input.path = {"path": ..., "scope": ...} and
    provenance.input.content_hash = the hash of that one file;
  - input list:   provenance.input.paths = [ {"path": {...},
    "content_hash": ...}, ... ], whose sibling provenance.input.content_hash
    is an aggregate over the whole input set -- it names no single file, so
    it is skipped.

Every attestation.checks[] entry that carries a path is checked too; command
checks record no hash and are skipped.

An envelope that cannot be parsed, or that records no comparable hash at all,
is an error, never a silent pass. Exits 0 when every recorded hash matches
the tree, 1 on drift or a path missing from the tree, 2 on an unparseable
envelope. Tool-free: stdlib Python only (see .github/workflows/ci.yml).
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

DEFAULT_ENVELOPE_DIR = Path(__file__).resolve().parent / "envelopes"
DEFAULT_REPO_ROOT = DEFAULT_ENVELOPE_DIR.parent.parent

HEX = set("0123456789abcdef")


class EnvelopeError(Exception):
    """The envelope cannot be parsed or records no comparable hash."""


def _parse_content_hash(value, envelope_name, where):
    prefix = "sha256:"
    if not isinstance(value, str) or not value.startswith(prefix):
        raise EnvelopeError(
            f"{envelope_name}: {where}: content_hash {value!r} is not a 'sha256:<hex>' string"
        )
    digest = value[len(prefix):]
    if len(digest) != 64 or not set(digest) <= HEX:
        raise EnvelopeError(
            f"{envelope_name}: {where}: content_hash is not 64 hex digits"
        )
    return digest


def _path_of(value, envelope_name, where):
    if not isinstance(value, dict) or "path" not in value:
        raise EnvelopeError(
            f"{envelope_name}: {where}: expected an object with a 'path' key"
        )
    return value["path"]


def collect_records(envelope, envelope_name):
    """Return [(where, relpath, digest)] for every recorded content_hash that
    names a file."""
    if not isinstance(envelope, dict):
        raise EnvelopeError(f"{envelope_name}: top level is not a JSON object")
    records = []

    attestation = envelope.get("attestation")
    if not isinstance(attestation, dict):
        raise EnvelopeError(f"{envelope_name}: no attestation object")
    checks = attestation.get("checks")
    if not isinstance(checks, list):
        raise EnvelopeError(f"{envelope_name}: attestation.checks is not an array")
    for i, check in enumerate(checks):
        if not isinstance(check, dict):
            raise EnvelopeError(f"{envelope_name}: attestation.checks[{i}] is not an object")
        if "content_hash" in check and "path" not in check:
            raise EnvelopeError(
                f"{envelope_name}: attestation.checks[{i}] records a content_hash but no path"
            )
        if "path" not in check or "content_hash" not in check:
            # A check may name a path it examined without recording a hash
            # (klt's top_cell_non_empty / dbu_on_grid do); only pairs with both
            # fields name bytes to compare.
            continue
        digest = _parse_content_hash(
            check["content_hash"], envelope_name, f"attestation.checks[{i}]"
        )
        records.append((f"attestation.checks[{i}]", check["path"], digest))

    provenance = envelope.get("provenance")
    if not isinstance(provenance, dict):
        raise EnvelopeError(f"{envelope_name}: no provenance object")
    inp = provenance.get("input")
    if not isinstance(inp, dict):
        raise EnvelopeError(f"{envelope_name}: provenance.input is not an object")

    if "path" in inp:
        rel = _path_of(inp["path"], envelope_name, "provenance.input.path")
        digest = _parse_content_hash(inp.get("content_hash"), envelope_name, "provenance.input")
        records.append(("provenance.input", rel, digest))
    elif "paths" in inp:
        entries = inp["paths"]
        if not isinstance(entries, list):
            raise EnvelopeError(f"{envelope_name}: provenance.input.paths is not an array")
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise EnvelopeError(
                    f"{envelope_name}: provenance.input.paths[{i}] is not an object"
                )
            if "path" not in entry or "content_hash" not in entry:
                raise EnvelopeError(
                    f"{envelope_name}: provenance.input.paths[{i}] lacks 'path' or 'content_hash'"
                )
            rel = _path_of(
                entry["path"], envelope_name, f"provenance.input.paths[{i}].path"
            )
            digest = _parse_content_hash(
                entry["content_hash"], envelope_name, f"provenance.input.paths[{i}]"
            )
            records.append((f"provenance.input.paths[{i}]", rel, digest))
        # inp["content_hash"] in this shape aggregates the whole input set; it
        # names no single file and has nothing to compare against.
    else:
        raise EnvelopeError(
            f"{envelope_name}: provenance.input has neither 'path' nor 'paths'"
        )

    return records


def verify_records(envelope, envelope_name, repo_root):
    """Return (unique_hashes_checked, mismatches); a mismatch is
    (where, relpath, expected_digest, actual_digest_or_None)."""
    records = collect_records(envelope, envelope_name)
    if not records:
        raise EnvelopeError(f"{envelope_name}: records no content_hash entries")
    seen = set()
    unique = 0
    mismatches = []
    for where, relpath, digest in records:
        key = (relpath, digest)
        if key in seen:
            continue
        seen.add(key)
        unique += 1
        f = repo_root / relpath
        if not f.is_file():
            mismatches.append((where, relpath, digest, None))
            continue
        actual = hashlib.sha256(f.read_bytes()).hexdigest()
        if actual != digest:
            mismatches.append((where, relpath, digest, actual))
    return unique, mismatches


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Verify envelope content_hash values against the committed files."
    )
    parser.add_argument("--envelope-dir", type=Path, default=DEFAULT_ENVELOPE_DIR,
                        help="directory of *.json envelopes (default: manifests/envelopes)")
    parser.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT,
                        help="root the recorded paths resolve against (default: repo root)")
    args = parser.parse_args(argv)

    envelopes = sorted(args.envelope_dir.glob("*.json"))
    if not envelopes:
        print(f"check_attestations: no envelope files found in {args.envelope_dir}",
              file=sys.stderr)
        return 2

    repo_root = args.repo_root.resolve()
    errors = []
    failures = []
    total = 0
    for path in envelopes:
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{path.name}: not valid JSON ({exc})")
            continue
        try:
            unique, mismatches = verify_records(envelope, path.name, repo_root)
        except EnvelopeError as exc:
            errors.append(str(exc))
            continue
        total += unique
        for where, relpath, expected, actual in mismatches:
            if actual is None:
                failures.append(
                    f"{path.name}: {where}: {relpath} does not exist in the tree"
                )
            else:
                failures.append(
                    f"{path.name}: {where}: {relpath} recorded sha256:{expected} "
                    f"but the tree has sha256:{actual}"
                )

    for error in errors:
        print(f"check_attestations: {error}", file=sys.stderr)
    for failure in failures:
        print(f"check_attestations: {failure}", file=sys.stderr)
    if errors:
        return 2
    if failures:
        return 1
    print(f"check_attestations: {total} recorded hashes across {len(envelopes)} "
          f"envelopes all match the tree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
