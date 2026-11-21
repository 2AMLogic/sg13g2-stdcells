#!/usr/bin/env bash
# The recipe's own evidence check (issue #9): exits non-zero unless all three
# flow/README.md power gates hold on the given envelopes. A P&R run whose
# request carried no `power` block is invalid evidence even though it reports
# status "ok" and a clean signal-only LVS.
#
# Issue #175 adds an optional STA + functional-verification pair (arguments 5
# and 6, both or neither): the STA envelope must be constrained with
# non-negative slack at every reported corner and the functional-verification
# envelope must be a passing run with at least one test. A partial pair or an
# unreadable report is not evidence. check-ci.sh replays the four-argument
# power check against the 20261104 record, which predates both reports.
#
# Usage: flow/check-evidence.sh <par-request.json> <par.json> <lvs.json> <erc.json>
#                               [sta.json functional-verification.json]
set -euo pipefail
req="$1"; par="$2"; lvs="$3"; erc="$4"; sta="${5:-}"; fv="${6:-}"
fail=0
bad() { echo "INVALID EVIDENCE: $*" >&2; fail=1; }

jq -e 'has("power") and (.power|type=="object")' "$req" >/dev/null \
  || bad "$req has no power block (a no-power run reaches route with no PDN)"
jq -e '.status=="ok" and .stage_reached=="route"' "$par" >/dev/null \
  || bad "P&R did not reach route with status ok"
jq -e '.power.pdn==true' "$par" >/dev/null \
  || bad "gate 1: power.pdn is not true"
jq -e '.status=="match" and .power_connectivity.status=="match"' "$lvs" >/dev/null \
  || bad "gate 2: LVS status and power_connectivity.status are not both match"
jq -e '.erc_finding_count==0 and (.nets|length>0) and all(.nets[]; .matched_islands==1 and .expected_islands==1)' "$erc" >/dev/null \
  || bad "gate 3: ERC reports findings or a supply net is not exactly one island"

if [ -n "$sta" ] || [ -n "$fv" ]; then
  { [ -n "$sta" ] && [ -n "$fv" ]; } \
    || bad "STA and functional-verification reports must be cited as a pair"
  if [ -r "$sta" ]; then
    # Both envelope shapes reduce to one corner list: `corners[]`, or the flat
    # single-corner response read as its own only entry. Every corner must be
    # a real measurement -- an unconstrained run reports OpenSTA's 1e+39
    # sentinel, a *positive* number, so timing_status is checked before any
    # slack is read -- with non-negative setup slack and null (no hold path)
    # or non-negative hold slack. An empty corner list proves nothing.
    jq -e '
      (.geometry_source|type=="string") and (has("corners") or has("timing_status"))
      and ((.corners // [.]) as $c
        | ($c|length)>=1
        and all($c[];
            .timing_status=="constrained"
            and .worst_slack_ns!=null and .worst_slack_ns>=0
            and (.worst_hold_slack_ns==null or .worst_hold_slack_ns>=0)))
    ' "$sta" >/dev/null \
      || bad "gate 4: STA is not constrained with non-negative slack at every corner ($sta)"
  else
    bad "STA report missing or unreadable: ${sta:-<empty>}"
  fi
  if [ -r "$fv" ]; then
    jq -e 'has("tests") and has("test_count")
      and .status=="pass" and .test_count>=1 and .failed_count==0
      and (.tests|length)>=1' "$fv" >/dev/null \
      || bad "gate 5: functional-verification is not a passing run with at least one test ($fv)"
  else
    bad "functional-verification report missing or unreadable: ${fv:-<empty>}"
  fi
fi
exit "$fail"
