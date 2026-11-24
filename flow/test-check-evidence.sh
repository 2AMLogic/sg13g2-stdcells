#!/usr/bin/env bash
# Edge tests for check-evidence.sh (issues #9, #175, #190 and #247). Runs one
# real klt place-and-route on a copy of request-par.json with `power` deleted,
# then asserts the check rejects it while still seeing status ok / stage route.
# Then exercises the STA / functional-verification gates: a passing pair is
# accepted, and each bad envelope alone -- a non-ok status, non-routed
# geometry, a `corners` value that is not an array, an unconstrained corner,
# incomplete or unavailable constraint_completeness, negative setup slack,
# negative hold slack, an empty corner list, a failing FV status, a partial
# pair, an unreadable report -- is rejected.
# Needs a completed flow/run.sh (flow/build/{add8_synth.v,par.out.json,
# lvs.out.json,erc.json,sta.json,fv.json}). Single local run, no grids.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; cd "$here"
d=build/nopower; rm -rf "$d"; mkdir -p "$d"
jq 'del(.power) | .netlist="../add8_synth.v"' request-par.json > "$d/request-par.json"
klt place-and-route "$d/request-par.json" ${PDK_ARGS:---pdk ihp-sg13g2} --format json > "$d/par.json"
jq -e '.status=="ok" and .stage_reached=="route"' "$d/par.json" >/dev/null \
  || { echo "setup: no-power run did not reach route" >&2; exit 2; }
echo "no-power run: status ok, pdn=$(jq -c '.power.pdn // "absent"' "$d/par.json")"
if ./check-evidence.sh "$d/request-par.json" "$d/par.json" build/lvs.out.json build/erc.json build/sta.json build/fv.json 2>"$d/check.err"; then
  echo "FAIL: check accepted a request without power" >&2; exit 1
fi
cat "$d/check.err"; echo "PASS: no-power request flagged invalid"

t=build/evidence-edge; rm -rf "$t"; mkdir -p "$t"
for f in par.out.json lvs.out.json erc.json sta.json fv.json; do
  [ -s "build/$f" ] || { echo "setup: run flow/run.sh first (build/$f missing)" >&2; exit 2; }
done

./check-evidence.sh request-par.json build/par.out.json build/lvs.out.json build/erc.json build/sta.json build/fv.json
echo "PASS: passing STA + functional-verification pair accepted"

reject() { # reject <sta> <fv> <label>
  if ./check-evidence.sh request-par.json build/par.out.json build/lvs.out.json build/erc.json "$1" "$2" 2>"$t/err"; then
    echo "FAIL: check accepted $3" >&2; exit 1
  fi
  sed 's/^/  /' "$t/err"; echo "PASS: $3 rejected"
}

jq '(.corners[0]).timing_status="unconstrained"' build/sta.json > "$t/sta-unconstrained.json"
reject "$t/sta-unconstrained.json" build/fv.json "an unconstrained corner"
jq '(.corners[0]).worst_slack_ns=-0.001' build/sta.json > "$t/sta-negsetup.json"
reject "$t/sta-negsetup.json" build/fv.json "negative setup slack"
jq '(.corners[0]).worst_hold_slack_ns=-0.001' build/sta.json > "$t/sta-neghold.json"
reject "$t/sta-neghold.json" build/fv.json "negative hold slack"
jq '.corners=[]' build/sta.json > "$t/sta-nocorners.json"
reject "$t/sta-nocorners.json" build/fv.json "an empty corner list"
jq '.status="error"' build/sta.json > "$t/sta-status.json"
reject "$t/sta-status.json" build/fv.json "an STA envelope with status error"
jq '.geometry_source="synthesized"' build/sta.json > "$t/sta-geom.json"
reject "$t/sta-geom.json" build/fv.json "non-routed STA geometry"
jq '.corners|=(map({key:(.corner),value:.})|from_entries)' build/sta.json > "$t/sta-objcorners.json"
reject "$t/sta-objcorners.json" build/fv.json "a corners object in place of an array"
jq '.corners=null' build/sta.json > "$t/sta-nullcorners.json"
reject "$t/sta-nullcorners.json" build/fv.json "a null corners field"
jq '. + .corners[0] | del(.corner) | .corners=null' build/sta.json > "$t/sta-flat-nullcorners.json"
reject "$t/sta-flat-nullcorners.json" build/fv.json "a null corners field alongside passing top-level timing fields"
jq '.status="fail"' build/fv.json > "$t/fv-fail.json"
reject build/sta.json "$t/fv-fail.json" "a failing functional-verification run"
reject "" build/fv.json "a partial pair (no STA report)"
reject "$t/missing.json" build/fv.json "an unreadable STA report"
reject build/sta.json "$t/missing.json" "an unreadable FV report"
jq '(.corners[0]).worst_slack_ns="-1"' build/sta.json > "$t/sta-strsetup.json"
reject "$t/sta-strsetup.json" build/fv.json "string-valued setup slack"
jq '(.corners[0]).worst_hold_slack_ns="-1"' build/sta.json > "$t/sta-strhold.json"
reject "$t/sta-strhold.json" build/fv.json "string-valued hold slack"
jq 'del(.corners[0].worst_hold_slack_ns)' build/sta.json > "$t/sta-nohold.json"
reject "$t/sta-nohold.json" build/fv.json "a missing hold-slack field"
jq '(.corners[0]).constraint_completeness.status="incomplete"' build/sta.json > "$t/sta-incomplete.json"
reject "$t/sta-incomplete.json" build/fv.json "incomplete constraint_completeness"
grep -qi "constraint.completeness" "$t/err" \
  || { echo "FAIL: gate 4 message did not name constraint completeness" >&2; exit 1; }
jq '(.corners[0]).constraint_completeness.status="unknown"' build/sta.json > "$t/sta-cc-unknown.json"
reject "$t/sta-cc-unknown.json" build/fv.json "unknown constraint_completeness"
jq '(.corners[0]).constraint_completeness.unconstrained_endpoints.count=1' build/sta.json > "$t/sta-unconstrained-ep.json"
reject "$t/sta-unconstrained-ep.json" build/fv.json "non-zero unconstrained_endpoints.count under complete status"
jq '(.corners[0]).constraint_completeness.unclocked_registers={status:"unavailable",count:null}' build/sta.json > "$t/sta-unclocked-unavail.json"
reject "$t/sta-unclocked-unavail.json" build/fv.json "unavailable unclocked_registers with null count under complete status"
jq 'del(.corners[0].constraint_completeness)' build/sta.json > "$t/sta-no-cc.json"
reject "$t/sta-no-cc.json" build/fv.json "a missing constraint_completeness block"
jq '(.corners[0]).constraint_completeness.unclocked_registers.count=1' build/sta.json > "$t/sta-unclocked-reg.json"
reject "$t/sta-unclocked-reg.json" build/fv.json "non-zero unclocked_registers.count under complete status"
jq '(.corners[0]).constraint_completeness.unconstrained_endpoints={status:"unavailable",count:null}' build/sta.json > "$t/sta-unconstrained-unavail.json"
reject "$t/sta-unconstrained-unavail.json" build/fv.json "unavailable unconstrained_endpoints with null count under complete status"
jq '. + .corners[0] | del(.corners, .corner)' build/sta.json > "$t/sta-flat-ok.json"
./check-evidence.sh request-par.json build/par.out.json build/lvs.out.json build/erc.json "$t/sta-flat-ok.json" build/fv.json
echo "PASS: flat single-corner STA envelope accepted"
jq '.constraint_completeness.status="incomplete"' "$t/sta-flat-ok.json" > "$t/sta-flat-incomplete.json"
reject "$t/sta-flat-incomplete.json" build/fv.json "a flat single-corner STA envelope with incomplete constraint_completeness"
: > "$t/empty.json"
reject "$t/empty.json" build/fv.json "an empty STA file"
reject build/sta.json "$t/empty.json" "an empty FV file"
jq '.tests[0].status="failed"' build/fv.json > "$t/fv-testfailed.json"
reject build/sta.json "$t/fv-testfailed.json" "a failed test under a passing summary"
jq '.tests[0].status="skipped" | .passed_count=0 | .skipped_count=1' build/fv.json > "$t/fv-allskipped.json"
reject build/sta.json "$t/fv-allskipped.json" "an all-skipped envelope"
jq '.test_count="0"' build/fv.json > "$t/fv-strcount.json"
reject build/sta.json "$t/fv-strcount.json" "a string-valued test_count"
# Argument forms: empty optional paths and a wrong count must not pass.
base=(request-par.json build/par.out.json build/lvs.out.json build/erc.json)
for extra in "" "|" "|build/fv.json" "build/sta.json|"; do
  IFS='|' read -r a b <<<"$extra"
  if [ -z "$extra" ]; then args=("${base[@]}" ""); else args=("${base[@]}" "$a" "$b"); fi
  if ./check-evidence.sh "${args[@]}" 2>/dev/null; then
    echo "FAIL: check accepted optional arguments [$extra]" >&2; exit 1
  fi
  echo "PASS: optional arguments [$extra] rejected"
done
if ./check-evidence.sh "${base[@]}" build/sta.json 2>/dev/null; then
  echo "FAIL: check accepted five arguments" >&2; exit 1
fi
echo "PASS: five arguments rejected"
echo "all evidence edge cases hold"
