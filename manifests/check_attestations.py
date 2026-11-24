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

The walk also carries a focused item-9 check (issue #178): an item-9
envelope's PDK pin (the resolved pins.pdk of its inventory) must agree with
the PDK pin of every committed measurement sidecar under views/*.lib.provenance
-- the analog characterization inventory pins the PDK its measurement
consumed, and the sidecar is where the run recorded it. A disagreement means
the inventory pins a PDK the committed view was not measured against, and
exits 1 like any other drift; an unreadable pin or sidecar is an error (2).

With --manifest FILE the script instead checks a block manifest's evidence
pins (issue #116): every evidence entry that is a {file, content_hash} object
pins the provenance.input.content_hash of the envelope it names -- the
single-file digest for the path shape, the input-set aggregate for the paths
shape (exactly the field the per-file walk above skips). For item 6's
not_applicable form, the spec and statement pins each hash the raw bytes
of the named document. Bare path strings record locations without a pin
and are skipped. A list entry is handled element by element (#220): bare
strings are skipped as locations, and {file, content_hash, ...} elements
are envelope pins compared exactly like a top-level object pin -- item 5's
analog citations are klt sim reports whose provenance.input.content_hash
names the netlist the run consumed, and each is checked and counted on
its own. The default run walks the envelope directory
and checks the envelopes against the tree. Issue #116's defect was a
re-minted envelope whose manifest pin was never re-pointed, so the committed
signoff count disagreed with what the grader computed, and no CI stage could
see it.

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
    if not isinstance(envelope, dict):
        raise EnvelopeError(f"{envelope_name}: top level is not a JSON object")
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


# --- Focused item-9 PDK-pin check (issue #178) --------------------------------
#
# An item-9 testbench inventory pins the PDK its partition's measurement
# consumed (`pins.pdk`); `klt signoff --attest 9` records that pin, resolved,
# as the envelope's `role: "pdk"` check. The measurement's own provenance is
# the committed Liberty sidecar (`views/*.lib.provenance`), whose `pdk`
# object the characterize runner captured from the --pdk-dir checkout before
# anything was written. The two must agree: the envelope is minted from the
# inventory, the sidecar from the run, so committed bytes naming different
# revisions mean the inventory pins a PDK the committed view was not measured
# against -- exactly the disagreement `check_library` catches between sidecar
# and record, extended one link up the chain. This is tool-free, so CI (which
# has no klt to re-attest) sees it too.

SIDECAR_GLOB = "views/*.lib.provenance"


def _item9_pdk_pin(envelope, envelope_name):
    """The item-9 inventory's resolved PDK pin from its envelope.

    None when the envelope is not an item-9 one, or the partition's cold
    start consumes no PDK (the explicit ``{"none": true}`` form). Raises on
    an item-9 envelope whose recorded pin check is missing or unreadable:
    silence never means "no PDK".
    """
    if envelope.get("t1_item") != 9:
        return None
    checks = (envelope.get("attestation") or {}).get("checks")
    if not isinstance(checks, list):
        raise EnvelopeError(f"{envelope_name}: attestation.checks is not an array")
    pins = [c for c in checks if isinstance(c, dict) and c.get("role") == "pdk"]
    if len(pins) != 1:
        raise EnvelopeError(
            f"{envelope_name}: an item-9 envelope records {len(pins)} pdk pin "
            f"checks (expected exactly one) -- the PDK pin is missing or ambiguous"
        )
    value = pins[0].get("value")
    if not isinstance(value, dict):
        raise EnvelopeError(
            f"{envelope_name}: the pdk pin check records no value object"
        )
    if value.get("none"):
        return None
    name, revision = value.get("name"), value.get("revision")
    if (not isinstance(name, str) or not name.strip()
            or not isinstance(revision, str) or not revision.strip()):
        raise EnvelopeError(
            f"{envelope_name}: the pdk pin check names no PDK and no revision "
            f"(value {value!r})"
        )
    return name.strip(), revision.strip()


def pdk_pin_findings(envelope, envelope_name, repo_root):
    """Return mismatch findings for the inventory PDK pin vs the committed
    measurement sidecars; empty means they agree (or the item has no PDK)."""
    pin = _item9_pdk_pin(envelope, envelope_name)
    if pin is None:
        return []
    name, revision = pin
    sidecars = sorted(repo_root.glob(SIDECAR_GLOB))
    if not sidecars:
        raise EnvelopeError(
            f"{envelope_name}: pins PDK {name!r} @ {revision} but the repo "
            f"carries no {SIDECAR_GLOB} provenance sidecar to compare against"
        )
    findings = []
    for sidecar in sidecars:
        try:
            prov = json.loads(sidecar.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            raise EnvelopeError(
                f"{envelope_name}: cannot read the measurement sidecar "
                f"{sidecar.name} ({exc})"
            ) from exc
        pdk = prov.get("pdk") if isinstance(prov, dict) else None
        pdk = pdk if isinstance(pdk, dict) else {}
        pinned_name = pdk.get("name")
        pinned_revision = pdk.get("revision")
        where = f"{envelope_name}: pdk pin vs {sidecar.name}"
        if (not isinstance(pinned_name, str) or not pinned_name.strip()
                or not isinstance(pinned_revision, str) or not pinned_revision.strip()):
            findings.append(
                f"{where}: the inventory pins {name!r} @ {revision} but the "
                f"sidecar records no PDK pin -- the committed measurement was "
                f"taken against an unpinned PDK; re-characterize and re-attest"
            )
        elif (pinned_name.strip(), pinned_revision.strip()) != (name, revision):
            findings.append(
                f"{where}: the inventory pins {name!r} @ {revision} but the "
                f"sidecar records {pinned_name!r} @ {pinned_revision!r} -- the "
                f"inventory pins a PDK the committed measurement was not "
                f"taken against; re-characterize and re-attest"
            )
    return findings


def _parse_file_pin(entry, manifest_name, where):
    if (
        not isinstance(entry, dict)
        or "file" not in entry
        or "content_hash" not in entry
    ):
        raise EnvelopeError(
            f"{manifest_name}: {where}: object entries must carry both 'file' and 'content_hash'"
        )
    rel = entry["file"]
    if not isinstance(rel, str) or not rel:
        raise EnvelopeError(f"{manifest_name}: {where}: 'file' is not a path string")
    return rel, _parse_content_hash(entry["content_hash"], manifest_name, where)


def _document_pin_mismatch(entry, manifest_name, where, repo_root):
    rel, pin = _parse_file_pin(entry, manifest_name, where)
    try:
        content = (repo_root / rel).read_bytes()
    except (OSError, ValueError) as exc:
        raise EnvelopeError(
            f"{manifest_name}: {where}: cannot read {rel} ({exc})"
        ) from exc
    actual = hashlib.sha256(content).hexdigest()
    if actual != pin:
        return f"{manifest_name}: {where} pins sha256:{pin} but {rel} hashes to sha256:{actual}"
    return None


def _envelope_pin_mismatch(entry, manifest_name, where, repo_root):
    """Compare a {file, content_hash} pin against the envelope it names.

    The envelope's provenance.input.content_hash is the single-file digest
    for the path shape, the input-set aggregate for the paths shape -- the
    field the pin names. Returns a failure string on disagreement, None on
    a match; raises EnvelopeError on a structural problem (malformed pin,
    missing or unparseable envelope).
    """
    rel, pin = _parse_file_pin(entry, manifest_name, where)
    env_path = repo_root / rel
    if not env_path.is_file():
        raise EnvelopeError(
            f"{manifest_name}: {where}: envelope {rel} does not exist"
        )
    try:
        envelope = json.loads(env_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EnvelopeError(
            f"{manifest_name}: {where}: envelope {rel} is not valid JSON ({exc})"
        ) from exc
    try:
        aggregate = envelope_input_hash(envelope, rel)
    except EnvelopeError as exc:
        raise EnvelopeError(f"{manifest_name}: {where}: {exc}") from exc
    if pin != aggregate:
        return (
            f"{manifest_name}: {where} pins sha256:{pin} but envelope {rel} "
            f"carries provenance.input.content_hash sha256:{aggregate}; "
            f"{MANIFEST_FIX_HINT}"
        )
    return None


def manifest_pin_findings(manifest, manifest_name, repo_root):
    """Return (checked, errors, failures) for the manifest's evidence pins.

    checked counts the pins compared; an error is a structural problem
    (unreadable evidence, malformed pin or envelope) and exits 2. A failure
    is a pin that disagrees with the evidence it names and exits 1.
    """
    errors = []
    failures = []
    checked = 0
    if not isinstance(manifest, dict):
        errors.append(f"{manifest_name}: top level is not a JSON object")
        return checked, errors, failures
    evidence = manifest.get("evidence")
    if not isinstance(evidence, dict):
        errors.append(f"{manifest_name}: no evidence object")
        return checked, errors, failures
    for key, entry in evidence.items():
        where = f'evidence["{key}"]'
        if isinstance(entry, str):
            # A bare evidence path: a location recorded without a pin,
            # nothing to compare.
            continue
        if isinstance(entry, list):
            # A list mixes shapes element by element (#220): bare strings
            # are locations without a pin and are skipped, while {file,
            # content_hash, ...} objects are envelope pins compared exactly
            # like the top-level object branch below -- item 5's analog
            # citations are klt sim reports whose provenance.input
            # .content_hash is the pin. A string-only list still pins
            # nothing.
            # A nested list is a cited group (item 11's analog groups pair
            # an ERC and an LVS record per cell); its elements are walked
            # the same way, one level deep.
            flat = []
            for i, element in enumerate(entry):
                if isinstance(element, list):
                    flat.extend(
                        (f"{where}[{i}][{j}]", sub)
                        for j, sub in enumerate(element)
                    )
                else:
                    flat.append((f"{where}[{i}]", element))
            for location, element in flat:
                if isinstance(element, str):
                    continue
                if not isinstance(element, dict):
                    errors.append(
                        f"{manifest_name}: {location}: expected a path string "
                        f"or a {{file, content_hash}} object, got "
                        f"{type(element).__name__}"
                    )
                    continue
                try:
                    mismatch = _envelope_pin_mismatch(
                        element, manifest_name, location, repo_root
                    )
                except EnvelopeError as exc:
                    errors.append(str(exc))
                    continue
                checked += 1
                if mismatch:
                    failures.append(mismatch)
            continue
        if not isinstance(entry, dict):
            errors.append(
                f"{manifest_name}: {where}: expected a path string, a list of "
                f"paths or pinned objects, or a {{file, content_hash}} object, "
                f"got {type(entry).__name__}"
            )
            continue
        if key in ("6", "6.digital") and "not_applicable" in entry:
            form = entry["not_applicable"]
            if not isinstance(form, dict):
                errors.append(
                    f"{manifest_name}: {where}.not_applicable: expected an object"
                )
                continue
            for document in ("spec", "statement"):
                location = f"{where}.not_applicable.{document}"
                try:
                    mismatch = _document_pin_mismatch(
                        form.get(document), manifest_name, location, repo_root
                    )
                except EnvelopeError as exc:
                    errors.append(str(exc))
                    continue
                checked += 1
                if mismatch:
                    failures.append(mismatch)
            continue
        try:
            mismatch = _envelope_pin_mismatch(
                entry, manifest_name, where, repo_root
            )
        except EnvelopeError as exc:
            errors.append(str(exc))
            continue
        checked += 1
        if mismatch:
            failures.append(mismatch)
    return checked, errors, failures


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Verify envelope content_hash values against the committed files."
    )
    parser.add_argument("--envelope-dir", type=Path, default=DEFAULT_ENVELOPE_DIR,
                        help="directory of *.json envelopes (default: manifests/envelopes)")
    parser.add_argument("--manifest", type=Path, default=None,
                        help="check the evidence pins of this block manifest "
                             "against the envelopes or documents they name, instead of "
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
              f"match the evidence they name")
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
        try:
            failures.extend(pdk_pin_findings(envelope, path.name, repo_root))
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
