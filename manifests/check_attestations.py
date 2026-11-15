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
    it is skipped here.

Every attestation.checks[] entry that carries a path is checked too; command
checks record no hash and are skipped.

With --manifest FILE the script instead checks a block manifest's evidence
pins (issue #116): every evidence entry that is a {file, content_hash} object
pins the provenance.input.content_hash of the envelope it names -- the
single-file digest for the path shape, the input-set aggregate for the paths
shape (exactly the field the per-file walk above skips). Bare path strings
and lists of them record locations without a pin and are skipped. The
envelope directory is not walked in this mode; envelope-vs-tree checking is
the default run. Issue #116's defect was a re-minted envelope whose manifest
pin was never re-pointed, so the committed signoff count disagreed with what
the grader computed, and no CI stage could see it.

An envelope that cannot be parsed, or that records no comparable hash at all,
is an error, never a silent pass. The same holds in --manifest mode: a
manifest whose evidence yields zero comparable pins (every entry a bare path
with no pin) verifies nothing and is an error, the sibling of an empty
envelope directory in the default run, as is a manifest file that cannot be
read. Exits 0 when everything matches, 1 on drift or a path missing from the
tree, 2 on an unparseable envelope or manifest -- including one that cannot
be read, or that pins nothing. Tool-free: stdlib Python only (see
.github/workflows/ci.yml).
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


MANIFEST_FIX_HINT = (
    "re-mint the envelope with `klt signoff --attest <item> --inventory "
    "<inventory> -o <envelope>` (CI has no klt), or re-point the manifest pin"
)


def envelope_input_hash(envelope, envelope_name):
    """Return the envelope's provenance.input.content_hash digest -- the
    single-file digest for the path shape, the input-set aggregate for the
    paths shape. This is the field a block manifest's evidence pin names."""
    provenance = envelope.get("provenance")
    if not isinstance(provenance, dict):
        raise EnvelopeError(f"{envelope_name}: no provenance object")
    inp = provenance.get("input")
    if not isinstance(inp, dict):
        raise EnvelopeError(f"{envelope_name}: provenance.input is not an object")
    if "content_hash" not in inp:
        raise EnvelopeError(
            f"{envelope_name}: provenance.input records no content_hash"
        )
    return _parse_content_hash(inp["content_hash"], envelope_name, "provenance.input")


def manifest_pin_findings(manifest, manifest_name, repo_root):
    """Return (checked, errors, failures) for the manifest's evidence pins.

    checked counts the pins compared; an error is a structural problem
    (missing/unparseable envelope, malformed pin) and exits 2; a failure is
    a pin that disagrees with the envelope it names and exits 1.
    """
    errors = []
    failures = []
    checked = 0
    evidence = manifest.get("evidence")
    if not isinstance(evidence, dict):
        errors.append(f"{manifest_name}: no evidence object")
        return checked, errors, failures
    for key, entry in evidence.items():
        where = f'evidence["{key}"]'
        if isinstance(entry, str) or isinstance(entry, list):
            # A bare evidence path, or a list of them: a location recorded
            # without a pin, nothing to compare.
            continue
        if not isinstance(entry, dict):
            errors.append(
                f"{manifest_name}: {where}: expected a path string, a list of "
                f"paths, or a {{file, content_hash}} object, got {type(entry).__name__}"
            )
            continue
        if "file" not in entry or "content_hash" not in entry:
            errors.append(
                f"{manifest_name}: {where}: object entries must carry both "
                "'file' and 'content_hash'"
            )
            continue
        rel = entry["file"]
        if not isinstance(rel, str) or not rel:
            errors.append(f"{manifest_name}: {where}: 'file' is not a path string")
            continue
        try:
            pin = _parse_content_hash(entry["content_hash"], manifest_name, where)
        except EnvelopeError as exc:
            errors.append(str(exc))
            continue
        env_path = repo_root / rel
        if not env_path.is_file():
            errors.append(
                f"{manifest_name}: {where}: envelope {rel} does not exist"
            )
            continue
        try:
            envelope = json.loads(env_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(
                f"{manifest_name}: {where}: envelope {rel} is not valid JSON ({exc})"
            )
            continue
        try:
            aggregate = envelope_input_hash(envelope, rel)
        except EnvelopeError as exc:
            errors.append(f"{manifest_name}: {where}: {exc}")
            continue
        checked += 1
        if pin != aggregate:
            failures.append(
                f"{manifest_name}: {where} pins sha256:{pin} but envelope {rel} "
                f"carries provenance.input.content_hash sha256:{aggregate}; "
                f"{MANIFEST_FIX_HINT}"
            )
    return checked, errors, failures


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Verify envelope content_hash values against the committed files."
    )
    parser.add_argument("--envelope-dir", type=Path, default=DEFAULT_ENVELOPE_DIR,
                        help="directory of *.json envelopes (default: manifests/envelopes)")
    parser.add_argument("--manifest", type=Path, default=None,
                        help="check the evidence pins of this block manifest "
                             "against the envelopes they name, instead of "
                             "walking the envelope directory (envelope-vs-tree "
                             "checking is skipped in this mode)")
    parser.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT,
                        help="root the recorded paths resolve against (default: repo root)")
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()

    if args.manifest is not None:
        try:
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"check_attestations: {args.manifest.name}: not valid JSON ({exc})",
                  file=sys.stderr)
            return 2
        except (OSError, UnicodeDecodeError) as exc:
            print(f"check_attestations: {args.manifest}: cannot read ({exc})",
                  file=sys.stderr)
            return 2
        checked, errors, failures = manifest_pin_findings(
            manifest, args.manifest.name, repo_root
        )
        for error in errors:
            print(f"check_attestations: {error}", file=sys.stderr)
        for failure in failures:
            print(f"check_attestations: {failure}", file=sys.stderr)
        if errors:
            return 2
        if failures:
            return 1
        if not checked:
            print(f"check_attestations: no evidence pins found in "
                  f"{args.manifest.name}: every evidence entry records a "
                  f"bare path with no pin, so nothing was verified",
                  file=sys.stderr)
            return 2
        print(f"check_attestations: {checked} evidence pins in {args.manifest.name} "
              f"match the envelopes they name")
        return 0

    envelopes = sorted(args.envelope_dir.glob("*.json"))
    if not envelopes:
        print(f"check_attestations: no envelope files found in {args.envelope_dir}",
              file=sys.stderr)
        return 2

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
