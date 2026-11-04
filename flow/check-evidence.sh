#!/usr/bin/env bash
# The recipe's own evidence check (issue #9): exits non-zero unless all three
# flow/README.md power gates hold on the given envelopes. A P&R run whose
# request carried no `power` block is invalid evidence even though it reports
# status "ok" and a clean signal-only LVS.
#
# Usage: flow/check-evidence.sh <par-request.json> <par.json> <lvs.json> <erc.json>
set -euo pipefail
req="$1"; par="$2"; lvs="$3"; erc="$4"
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
exit "$fail"
