#!/usr/bin/env bash
# Edge test (issue #9): a request without `power` must be flagged invalid by
# check-evidence.sh. Runs one real klt place-and-route on a copy of
# request-par.json with `power` deleted, then asserts the check rejects it
# while still seeing status ok / stage route. Needs flow/build/add8_synth.v
# (run flow/run.sh first). Single local run, no grids.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; cd "$here"
d=build/nopower; rm -rf "$d"; mkdir -p "$d"
jq 'del(.power) | .netlist="../add8_synth.v"' request-par.json > "$d/request-par.json"
klt place-and-route "$d/request-par.json" ${PDK_ARGS:---pdk ihp-sg13g2} --format json > "$d/par.json"
jq -e '.status=="ok" and .stage_reached=="route"' "$d/par.json" >/dev/null \
  || { echo "setup: no-power run did not reach route" >&2; exit 2; }
echo "no-power run: status ok, pdn=$(jq -c '.power.pdn // "absent"' "$d/par.json")"
if ./check-evidence.sh "$d/request-par.json" "$d/par.json" build/lvs.out.json build/erc.json 2>"$d/check.err"; then
  echo "FAIL: check accepted a request without power" >&2; exit 1
fi
cat "$d/check.err"; echo "PASS: no-power request flagged invalid"
