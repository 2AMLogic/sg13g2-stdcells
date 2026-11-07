"""Shared klt capability check for layout/ runners (see layout/toolchain.json).

Every runner that shells out to `klt` calls `check_commands` first, so a
missing subcommand is a named tooling error rather than a skipped check.
Python stdlib only.
"""
import json
import pathlib
import re
import subprocess

TOOLCHAIN = pathlib.Path(__file__).resolve().parent / "toolchain.json"


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
