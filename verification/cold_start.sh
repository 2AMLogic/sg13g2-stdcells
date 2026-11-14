#!/bin/sh
# Cold-start reproduction of verification/test_add8.py from a clean checkout.
#
# Neither this repo's CI (deliberately tool-free: stdlib Python + pytest + jq)
# nor a stock dispatch host has cocotb installed, so `make -C verification`
# alone is not a cold start -- it only runs where someone has already
# provisioned the simulator stack. This script provisions the Python half
# itself, in a throwaway virtualenv that it removes on exit, and leaves the
# host's own tools untouched.
#
# It is what `manifests/inventories/item9.digital.json` declares as the T1
# item 9 cold-start command, and `klt signoff --attest 9` runs it. Exit status
# is the testbench's: cocotb's Makefile fails the build on a failing test
# (verified -- a wrong adder exits 2), so a passing exit means the exhaustive
# 2^17-case check really passed.
#
# Icarus is the one thing this cannot provision (it is a system package, not a
# wheel); the script fails loudly naming it rather than skipping the run.
#
# Usage:  sh verification/cold_start.sh
#         COCOTB_VERSION=2.0.0 sh verification/cold_start.sh

set -eu

COCOTB_VERSION="${COCOTB_VERSION:-2.0.0}"

HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

if ! command -v iverilog >/dev/null 2>&1; then
    echo "cold_start: iverilog not on PATH -- install Icarus Verilog (SIM=icarus)" >&2
    exit 1
fi

VENV="$(mktemp -d "${TMPDIR:-/tmp}/sg13g2-cocotb-XXXXXX")"
trap 'rm -rf "$VENV"' EXIT INT TERM

echo "cold_start: provisioning cocotb==$COCOTB_VERSION in $VENV" >&2
python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --disable-pip-version-check "cocotb==$COCOTB_VERSION"

# A cold start builds from nothing: discard any incremental simulator output
# so the run cannot pass on a stale sim_build.
rm -rf "$HERE/sim_build" "$HERE/results.xml"

echo "cold_start: running the cocotb testbench on $(iverilog -V 2>&1 | head -1)" >&2
PATH="$VENV/bin:$PATH" make -C "$HERE"
