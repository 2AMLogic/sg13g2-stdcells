#!/usr/bin/env bash
# Edge tests for check-evidence.sh (issues #9, #175, #190 and #247). With no
# argument, runs one real klt place-and-route on a copy of request-par.json
# with `power` deleted, then asserts the check rejects it while still seeing
# status ok / stage route. Then exercises the STA / functional-verification
# gates: a passing pair is accepted, and each bad envelope alone -- a non-ok
# status, non-routed geometry, a `corners` value that is not an array, an
# unconstrained corner, incomplete or unavailable constraint_completeness,
# negative setup slack, negative hold slack, an empty corner list, a failing
# FV status, a partial pair, an unreadable report -- is rejected with
# INVALID EVIDENCE on stderr, so a usage error (exit 2) cannot pass as a
# gate rejection.
# `--record DIR` (issue #288) skips the live klt run and replays the same
# STA/FV edge cases against a committed record's place-and-route.json,
# lvs.json, erc.json, sta.json and functional-verification.json, minting
# mutants in a scratch dir: jq and bash only, no klt and no prior flow run,
# which is how check-ci.sh covers gates 4 and 5 in tool-free CI.
# No-argument mode needs a completed flow/run.sh (flow/build/{add8_synth.v,
# par.out.json,lvs.out.json,erc.json,sta.json,fv.json}). Single local run, no
# grids.
set -euo pipefail
# --record DIR resolves against the invoker's cwd, before the cd "$here" below.
record=""
if [ "$#" -eq 2 ] && [ "$1" = "--record" ]; then
  [ -d "$2" ] || { echo "setup: record dir '$2' not found" >&2; exit 2; }
  record="$(cd "$2" && pwd)"
elif [ "$#" -ne 0 ]; then
  echo "usage: $0 [--record DIR]" >&2
  exit 2
fi
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; cd "$here"

if [ -z "$record" ]; then
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
fi

# The five reports the STA/FV edge cases replay over: the flow/run.sh scratch
# outputs by default, a committed record's five reports with --record (whose
# mutants then go to a scratch dir, not build/ or the record itself).
req=request-par.json
if [ -z "$record" ]; then
  par=build/par.out.json; lvs=build/lvs.out.json; erc=build/erc.json
  sta=build/sta.json; fv=build/fv.json
  for f in "$par" "$lvs" "$erc" "$sta" "$fv"; do
    [ -s "$f" ] || { echo "setup: run flow/run.sh first ($f missing)" >&2; exit 2; }
  done
  t=build/evidence-edge; rm -rf "$t"; mkdir -p "$t"
else
  par="$record/place-and-route.json"; lvs="$record/lvs.json"; erc="$record/erc.json"
  sta="$record/sta.json"; fv="$record/functional-verification.json"
  for f in "$par" "$lvs" "$erc" "$sta" "$fv"; do
    [ -s "$f" ] || { echo "setup: record $record is incomplete ($f missing)" >&2; exit 2; }
  done
  t=$(mktemp -d)
  trap 'rm -rf "$t"' EXIT
fi

./check-evidence.sh "$req" "$par" "$lvs" "$erc" "$sta" "$fv"
echo "PASS: passing STA + functional-verification pair accepted"

reject() { # reject <sta> <fv> <label>: non-zero exit AND INVALID EVIDENCE on
  # stderr, so a usage error (exit 2) or a missing file cannot pass as a
  # gate rejection.
  local rc=0
  ./check-evidence.sh "$req" "$par" "$lvs" "$erc" "$1" "$2" 2>"$t/err" || rc=$?
  if [ "$rc" -eq 0 ]; then
    echo "FAIL: check accepted $3" >&2; exit 1
  fi
  if ! grep -q 'INVALID EVIDENCE' "$t/err"; then
    echo "FAIL: $3 rejected (exit $rc) without INVALID EVIDENCE:" >&2
    sed 's/^/  /' "$t/err" >&2; exit 1
  fi
  sed 's/^/  /' "$t/err"; echo "PASS: $3 rejected"
}

jq '(.corners[0]).timing_status="unconstrained"' "$sta" > "$t/sta-unconstrained.json"
reject "$t/sta-unconstrained.json" "$fv" "an unconstrained corner"
jq '(.corners[0]).worst_slack_ns=-0.001' "$sta" > "$t/sta-negsetup.json"
reject "$t/sta-negsetup.json" "$fv" "negative setup slack"
jq '(.corners[0]).worst_hold_slack_ns=-0.001' "$sta" > "$t/sta-neghold.json"
reject "$t/sta-neghold.json" "$fv" "negative hold slack"
jq '.corners=[]' "$sta" > "$t/sta-nocorners.json"
reject "$t/sta-nocorners.json" "$fv" "an empty corner list"
jq '.status="error"' "$sta" > "$t/sta-status.json"
reject "$t/sta-status.json" "$fv" "an STA envelope with status error"
jq '.geometry_source="synthesized"' "$sta" > "$t/sta-geom.json"
reject "$t/sta-geom.json" "$fv" "non-routed STA geometry"
jq '.corners|=(map({key:(.corner),value:.})|from_entries)' "$sta" > "$t/sta-objcorners.json"
reject "$t/sta-objcorners.json" "$fv" "a corners object in place of an array"
jq '.corners=null' "$sta" > "$t/sta-nullcorners.json"
reject "$t/sta-nullcorners.json" "$fv" "a null corners field"
jq '. + .corners[0] | del(.corner) | .corners=null' "$sta" > "$t/sta-flat-nullcorners.json"
reject "$t/sta-flat-nullcorners.json" "$fv" "a null corners field alongside passing top-level timing fields"
jq '.status="fail"' "$fv" > "$t/fv-fail.json"
reject "$sta" "$t/fv-fail.json" "a failing functional-verification run"
reject "" "$fv" "a partial pair (no STA report)"
reject "$t/missing.json" "$fv" "an unreadable STA report"
reject "$sta" "$t/missing.json" "an unreadable FV report"
jq '(.corners[0]).worst_slack_ns="-1"' "$sta" > "$t/sta-strsetup.json"
reject "$t/sta-strsetup.json" "$fv" "string-valued setup slack"
jq '(.corners[0]).worst_hold_slack_ns="-1"' "$sta" > "$t/sta-strhold.json"
reject "$t/sta-strhold.json" "$fv" "string-valued hold slack"
jq 'del(.corners[0].worst_hold_slack_ns)' "$sta" > "$t/sta-nohold.json"
reject "$t/sta-nohold.json" "$fv" "a missing hold-slack field"
jq '(.corners[0]).constraint_completeness.status="incomplete"' "$sta" > "$t/sta-incomplete.json"
reject "$t/sta-incomplete.json" "$fv" "incomplete constraint_completeness"
grep -qi "constraint.completeness" "$t/err" \
  || { echo "FAIL: gate 4 message did not name constraint completeness" >&2; exit 1; }
jq '(.corners[0]).constraint_completeness.status="unknown"' "$sta" > "$t/sta-cc-unknown.json"
reject "$t/sta-cc-unknown.json" "$fv" "unknown constraint_completeness"
jq '(.corners[0]).constraint_completeness.unconstrained_endpoints.count=1' "$sta" > "$t/sta-unconstrained-ep.json"
reject "$t/sta-unconstrained-ep.json" "$fv" "non-zero unconstrained_endpoints.count under complete status"
jq '(.corners[0]).constraint_completeness.unclocked_registers={status:"unavailable",count:null}' "$sta" > "$t/sta-unclocked-unavail.json"
reject "$t/sta-unclocked-unavail.json" "$fv" "unavailable unclocked_registers with null count under complete status"
jq 'del(.corners[0].constraint_completeness)' "$sta" > "$t/sta-no-cc.json"
reject "$t/sta-no-cc.json" "$fv" "a missing constraint_completeness block"
jq '(.corners[0]).constraint_completeness.unclocked_registers.count=1' "$sta" > "$t/sta-unclocked-reg.json"
reject "$t/sta-unclocked-reg.json" "$fv" "non-zero unclocked_registers.count under complete status"
jq '(.corners[0]).constraint_completeness.unconstrained_endpoints={status:"unavailable",count:null}' "$sta" > "$t/sta-unconstrained-unavail.json"
reject "$t/sta-unconstrained-unavail.json" "$fv" "unavailable unconstrained_endpoints with null count under complete status"
jq '. + .corners[0] | del(.corners, .corner)' "$sta" > "$t/sta-flat-ok.json"
./check-evidence.sh "$req" "$par" "$lvs" "$erc" "$t/sta-flat-ok.json" "$fv"
echo "PASS: flat single-corner STA envelope accepted"
jq '.constraint_completeness.status="incomplete"' "$t/sta-flat-ok.json" > "$t/sta-flat-incomplete.json"
reject "$t/sta-flat-incomplete.json" "$fv" "a flat single-corner STA envelope with incomplete constraint_completeness"
: > "$t/empty.json"
reject "$t/empty.json" "$fv" "an empty STA file"
reject "$sta" "$t/empty.json" "an empty FV file"
jq '.tests[0].status="failed"' "$fv" > "$t/fv-testfailed.json"
reject "$sta" "$t/fv-testfailed.json" "a failed test under a passing summary"
jq '.tests[0].status="skipped" | .passed_count=0 | .skipped_count=1' "$fv" > "$t/fv-allskipped.json"
reject "$sta" "$t/fv-allskipped.json" "an all-skipped envelope"
jq '.test_count="0"' "$fv" > "$t/fv-strcount.json"
reject "$sta" "$t/fv-strcount.json" "a string-valued test_count"
# Argument forms: a six-argument call with an empty optional path is an
# unreadable report (rejected with INVALID EVIDENCE like any other), while
# five arguments, empty or not, is a usage error (exit 2) -- the check picks
# its mode by argument count, never by emptiness.
base=("$req" "$par" "$lvs" "$erc")
for extra in "|" "|$fv" "$sta|"; do
  IFS='|' read -r a b <<<"$extra"
  reject "$a" "$b" "optional arguments [$extra]"
done
for five in "" "$sta"; do
  rc=0
  ./check-evidence.sh "${base[@]}" "$five" >/dev/null 2>/dev/null || rc=$?
  if [ "$rc" -ne 2 ]; then
    echo "FAIL: five arguments [${five:-<empty>}] exited $rc, expected usage error 2" >&2
    exit 1
  fi
  echo "PASS: five arguments [${five:-<empty>}] rejected as a usage error"
done
echo "all evidence edge cases hold"
