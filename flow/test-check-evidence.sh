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
unset CDPATH
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
reject_sta() {
  jq "$2" "${4:-$sta}" > "$t/$1.json"
  reject "$t/$1.json" "$fv" "$3"
}
reject_fv() {
  jq "$2" "$fv" > "$t/$1.json"
  reject "$sta" "$t/$1.json" "$3"
}

reject_sta sta-unconstrained '(.corners[0]).timing_status="unconstrained"' "an unconstrained corner"
reject_sta sta-negsetup '(.corners[0]).worst_slack_ns=-0.001' "negative setup slack"
reject_sta sta-neghold '(.corners[0]).worst_hold_slack_ns=-0.001' "negative hold slack"
reject_sta sta-nocorners '.corners=[]' "an empty corner list"
reject_sta sta-status '.status="error"' "an STA envelope with status error"
reject_sta sta-geom '.geometry_source="synthesized"' "non-routed STA geometry"
reject_sta sta-objcorners '.corners|=(map({key:(.corner),value:.})|from_entries)' "a corners object in place of an array"
reject_sta sta-nullcorners '.corners=null' "a null corners field"
reject_sta sta-flat-nullcorners '. + .corners[0] | del(.corner) | .corners=null' "a null corners field alongside passing top-level timing fields"
reject_fv fv-fail '.status="fail"' "a failing functional-verification run"
reject "$t/missing.json" "$fv" "an unreadable STA report"
reject "$sta" "$t/missing.json" "an unreadable FV report"
reject_sta sta-strsetup '(.corners[0]).worst_slack_ns="-1"' "string-valued setup slack"
reject_sta sta-strhold '(.corners[0]).worst_hold_slack_ns="-1"' "string-valued hold slack"
reject_sta sta-nohold 'del(.corners[0].worst_hold_slack_ns)' "a missing hold-slack field"
reject_sta sta-incomplete '(.corners[0]).constraint_completeness.status="incomplete"' "incomplete constraint_completeness"
grep -qi "constraint.completeness" "$t/err" \
  || { echo "FAIL: gate 4 message did not name constraint completeness" >&2; exit 1; }
reject_sta sta-cc-unknown '(.corners[0]).constraint_completeness.status="unknown"' "unknown constraint_completeness"
reject_sta sta-unconstrained-ep '(.corners[0]).constraint_completeness.unconstrained_endpoints.count=1' "non-zero unconstrained_endpoints.count under complete status"
reject_sta sta-unclocked-unavail '(.corners[0]).constraint_completeness.unclocked_registers={status:"unavailable",count:null}' "unavailable unclocked_registers with null count under complete status"
reject_sta sta-no-cc 'del(.corners[0].constraint_completeness)' "a missing constraint_completeness block"
reject_sta sta-unclocked-reg '(.corners[0]).constraint_completeness.unclocked_registers.count=1' "non-zero unclocked_registers.count under complete status"
reject_sta sta-unconstrained-unavail '(.corners[0]).constraint_completeness.unconstrained_endpoints={status:"unavailable",count:null}' "unavailable unconstrained_endpoints with null count under complete status"
jq '. + .corners[0] | del(.corners, .corner)' "$sta" > "$t/sta-flat-ok.json"
./check-evidence.sh "$req" "$par" "$lvs" "$erc" "$t/sta-flat-ok.json" "$fv"
echo "PASS: flat single-corner STA envelope accepted"
reject_sta sta-flat-incomplete '.constraint_completeness.status="incomplete"' "a flat single-corner STA envelope with incomplete constraint_completeness" "$t/sta-flat-ok.json"
: > "$t/empty.json"
reject "$t/empty.json" "$fv" "an empty STA file"
reject "$sta" "$t/empty.json" "an empty FV file"
reject_fv fv-testfailed '.tests[0].status="failed"' "a failed test under a passing summary"
reject_fv fv-allskipped '.tests[0].status="skipped" | .passed_count=0 | .skipped_count=1' "an all-skipped envelope"
reject_fv fv-strcount '.test_count="0"' "a string-valued test_count"
# Argument forms: a six-argument call with an empty optional path is an
# unreadable report (rejected with INVALID EVIDENCE like any other), while
# five arguments, empty or not, is a usage error (exit 2) -- the check picks
# its mode by argument count, never by emptiness.
reject "" "" "empty STA and FV paths"
reject "" "$fv" "an empty STA path with a valid FV report"
reject "$sta" "" "a valid STA report with an empty FV path"
base=("$req" "$par" "$lvs" "$erc")
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
