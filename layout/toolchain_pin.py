"""Shared klt capability check and runner plumbing for layout/ runners.

Every runner that shells out to `klt` calls `check_commands` first, so a
missing subcommand is a named tooling error rather than a skipped check.
The runners also take their CLI skeleton, that preflight's diagnostic and
their `--check` report bookkeeping from here, so they cannot drift apart on
flags, exit codes or stderr (see layout/toolchain.json).
Python stdlib only.
"""
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys

TOOLCHAIN = pathlib.Path(__file__).resolve().parent / "toolchain.json"
DECK = "sg13g2"


def required_commands(toolchain=TOOLCHAIN):
    return list(json.loads(pathlib.Path(toolchain).read_text())["klt_required_commands"])


def advertised_commands(help_text):
    """Subcommand names from `klt --help` (indented `name   description` rows)."""
    return set(re.findall(r"^    ([a-z][a-z0-9-]*)\s{2,}\S", help_text, re.M))


def missing_commands(required, help_text):
    have = advertised_commands(help_text)
    return [c for c in required if c not in have]


def check_commands(needed=None, toolchain=TOOLCHAIN):
    """Return [] when klt advertises every command in `needed` (default: all
    of klt_required_commands); else the missing names. Raises OSError if klt
    cannot be run."""
    needed = required_commands(toolchain) if needed is None else needed
    out = subprocess.run(["klt", "--help"], capture_output=True, text=True, check=True).stdout
    return missing_commands(needed, out)


def install_hint(toolchain=TOOLCHAIN):
    return json.loads(pathlib.Path(toolchain).read_text())["klt_install"]


def ensure_commands(runner_name, install_detail=None):
    """The capability preflight, reported the same way from every runner.
    Returns 0 when klt advertises every required command, else exit code 1
    after naming the problem on stderr as `<runner_name>: ...`. A missing
    command is followed by `install_detail`, or by the `klt_install` hint."""
    try:
        missing = check_commands()
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"{runner_name}: cannot run klt: {e}", file=sys.stderr)
        return 1
    if missing:
        detail = f"install: {install_hint()}" if install_detail is None else install_detail
        print(f"{runner_name}: klt lacks {missing}; {detail}", file=sys.stderr)
        return 1
    return 0


def relpath(p):
    return os.path.relpath(p)


def load_json(source):
    """The JSON document parsed from the file `source`, unless `source` is
    already a parsed dict."""
    return source if isinstance(source, dict) else json.loads(pathlib.Path(source).read_text())


def cell_names(config):
    return [c["name"] for c in load_json(config)["cells"]]


def parse_runner_args(doc, default_out, argv=None, extra_flags=()):
    """Parse a runner CLI: --config (required), each flag in `extra_flags`
    (all optional, no default), --gds, --out and --check. Returns
    (args, cfgdir, gds, out): --gds defaults to <config dir>/gds and --out to
    <config dir>/<default_out>. The first line of the runner docstring `doc`
    is the --help description."""
    ap = argparse.ArgumentParser(description=doc.splitlines()[0])
    ap.add_argument("--config", required=True)
    for flag in extra_flags:
        ap.add_argument(flag)
    ap.add_argument("--gds")
    ap.add_argument("--out")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    cfgdir = pathlib.Path(a.config).resolve().parent
    gds = pathlib.Path(a.gds) if a.gds else cfgdir / "gds"
    out = pathlib.Path(a.out) if a.out else cfgdir / default_out
    return a, cfgdir, gds, out


def check_report_fresh(what, rep, subcmd, run_fn):
    """Why the `klt <subcmd>` report `rep` cannot vouch for `what` ([] = it
    was re-checked and is fresh): it is missing, or `run_fn(rep)` (the
    runner's `klt <subcmd> --check`) exited non-zero. klt's stdout is cut to
    200 characters."""
    if not rep.exists():
        return [f"{what}: report {rep} missing"]
    c = run_fn(rep)
    if c.returncode != 0:
        return [f"{what}: klt {subcmd} --check exit {c.returncode}: {c.stdout.strip()[:200]}"]
    return []


def stray_reports(directory, expected_stems, label="stray report"):
    """One `<label> <file>` line per *.json report in `directory` whose stem
    is not in `expected_stems`, sorted by name."""
    strays = sorted(p.name for p in pathlib.Path(directory).glob("*.json")
                    if p.stem not in expected_stems)
    return [f"{label} {n}" for n in strays]


def emit_check_errors(bad):
    """Print every `--check` problem on stderr; return the `--check` exit code."""
    for b in bad:
        print(b, file=sys.stderr)
    return 1 if bad else 0
