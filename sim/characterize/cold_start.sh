#!/bin/sh
# Cold-start reproduction of the analog characterization testbenches from a
# clean checkout, tool-free.
#
# It is what `manifests/inventories/item9.analog.json` declares as the T1
# item 9 cold-start command, and `klt signoff --attest 9` runs it. It
# exercises the two halves of the characterization bench that need no EDA
# toolchain (stdlib Python only -- the same constraint as this repo's CI):
#
#   1. the request-construction tests (`python3 -m unittest
#      sim.characterize.tests.test_request`) -- the pure builder behind
#      every klt characterize request (corner blocks, NLDM axes, cell
#      entries, library view naming);
#   2. the freshness checker (`python3 -m sim.characterize.check_library`)
#      -- re-derives what the committed Liberty view's provenance sidecar
#      claims: library name, cell set, declared corner, the pinned config's
#      SHA-256, the evidence record it cites, the PDK pin both the sidecar
#      and the record carry, and the provenance stamps. A stale or
#      hand-edited artifact fails it, so a passing exit means the committed
#      characterization evidence really agrees with itself.
#
# What this deliberately does NOT run: the characterization itself. A real
# re-measurement needs klt, ngspice and an IHP-Open-PDK git checkout at the
# pinned commit; that invocation is recorded (never run) in the inventory's
# `documented_argv` and spelled out, PDK checkout included, in README.md
# ("Reproducing the characterization"). Exit status is whichever step fails.
#
# Usage:  sh sim/characterize/cold_start.sh

set -eu

HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$HERE/../.." && pwd)"

cd "$REPO_ROOT"
python3 -m unittest sim.characterize.tests.test_request
python3 -m sim.characterize.check_library
