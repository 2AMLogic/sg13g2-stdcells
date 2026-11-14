#!/usr/bin/env bash
# The single source of truth for the CI check list (issue #81). The command text
# used to be written out three times — in .github/workflows/ci.yml, in
# package.json's `check:ci`, and in README.md ("Continuous integration") — so a
# check could be edited in one copy and silently disagree with the others. All
# three now call this script; only this file spells the commands out.
#
# Tool-free by constraint (see .github/workflows/ci.yml): stdlib Python 3,
# pytest and jq only. No klt, ngspice or PDK, so tool-dependent runs (SPICE,
# DRC, LVS, place-and-route) are not covered here.
#
# Usage: ./check-ci.sh [stage]
#
#   tests            unit tests
#   netlists         generated LVS netlists are fresh
#   layouts          generated layouts are fresh
#   evidence-accept  the evidence check accepts the committed flow record
#   evidence-reject  the evidence check rejects the negative control
#
# With no argument every stage runs, in the order above. The workflow passes a
# stage name per step so GitHub still reports pass/fail per check.
set -euo pipefail

cd "$(dirname "$0")"

# The flow record CI gates on. Repointing CI at a newer record is this one line.
FLOW_RECORD=flow/records/20261104-df96543

ALL_STAGES="tests netlists layouts evidence-accept evidence-reject"

stage_tests() {
  python3 -m pytest design/tests layout/tests sim
}

stage_netlists() {
  python3 design/gen_netlists.py --config layout/example_config.json \
    --out layout/lvs/netlists --check
}

stage_layouts() {
  python3 layout/gen_layouts.py --config layout/example_config.json --check
}

stage_evidence_accept() {
  flow/check-evidence.sh flow/request-par.json \
    "$FLOW_RECORD/place-and-route.json" \
    "$FLOW_RECORD/lvs.json" \
    "$FLOW_RECORD/erc.json"
}

# The negative control is a P&R run whose request carried no power block: it
# reports status "ok", so the check must reject it for this stage to pass.
stage_evidence_reject() {
  if flow/check-evidence.sh flow/request-par.json \
    "$FLOW_RECORD/negative-control-nopower.place-and-route.json" \
    "$FLOW_RECORD/lvs.json" \
    "$FLOW_RECORD/erc.json"; then
    echo "negative control was accepted; expected non-zero exit" >&2
    return 1
  fi
}

run_stage() {
  case "$1" in
    tests) stage_tests ;;
    netlists) stage_netlists ;;
    layouts) stage_layouts ;;
    evidence-accept) stage_evidence_accept ;;
    evidence-reject) stage_evidence_reject ;;
    *)
      echo "check-ci.sh: unknown stage '$1' (stages: $ALL_STAGES)" >&2
      return 2
      ;;
  esac
}

if [ "$#" -gt 1 ]; then
  echo "check-ci.sh: at most one stage argument (stages: $ALL_STAGES)" >&2
  exit 2
fi

if [ "$#" -eq 1 ]; then
  run_stage "$1"
else
  for stage in $ALL_STAGES; do
    echo "== $stage"
    run_stage "$stage"
  done
fi
