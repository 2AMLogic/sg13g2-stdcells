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
#   attestations     envelope content_hash values match the committed files
#   manifest-pins    block manifest evidence pins match the envelopes they name
#   netlists         generated LVS netlists are fresh
#   layouts          generated layouts are fresh
#   evidence-accept  the evidence check accepts the committed flow record
#   evidence-reject  the evidence check rejects the negative control
#   evidence-sta-fv-accept  the six-argument evidence check (gates 4 STA and 5
#                    functional verification) accepts the committed record
#   evidence-sta-fv-reject  the shared STA/FV edge-case suite in
#                    flow/test-check-evidence.sh rejects jq-minted mutants of
#                    the committed record
#
# With no argument every stage runs, in the order above. The workflow passes a
# stage name per step so GitHub still reports pass/fail per check.
set -euo pipefail

cd "$(dirname "$0")"

# The flow record CI gates on. Repointing CI at a newer record is this one line.
FLOW_RECORD=flow/records/20261104-df96543

ALL_STAGES="tests attestations manifest-pins netlists layouts evidence-accept evidence-reject evidence-sta-fv-accept evidence-sta-fv-reject"

stage_tests() {
  python3 -m pytest design/tests layout/tests sim manifests/tests
}

# Every envelope under manifests/envelopes/ records a sha256 per attested
# file; this stage re-hashes the committed files and fails on any
# disagreement, so an edit to an attested file cannot leave the envelope
# silently describing bytes that no longer exist (issue #103). Stdlib Python
# only. When the failure is a deliberate edit, re-attest locally with
# `klt signoff --attest <item> --inventory <inventory> -o <envelope>` -- CI
# has no klt, so re-attestation is always a local step.
#
# This stage and stage_manifest_pins below are ALSO declared as
# `merge.treeChecks` in .loom/config.json (issue #228), so merge-pr.sh runs
# them against the real merge tree (base + PR head) just before merging. PR CI
# alone cannot see a PR that is green against an older main and red against
# the current one. Keep the two command lists in step: a change to either
# stage's command must be mirrored in .loom/config.json.
stage_attestations() {
  python3 manifests/check_attestations.py
}

# The block manifest (manifests/sg13g2-stdcells.json) pins, per evidence key,
# the provenance.input.content_hash of the envelope it names (issue #116). The
# attestations stage deliberately skips that aggregate field, so nothing
# compared pins to envelopes: a re-mint that forgot to re-point the manifest,
# or a manifest edit that forgot to re-mint, left main publishing a signoff
# count its own grader contradicted (11 committed vs 10 fresh at the time).
# --manifest mode checks exactly that pin. On failure, the message names the
# repair: re-mint the envelope with `klt signoff --attest` or re-point the
# manifest pin -- both are local steps, CI has no klt. A manifest carrying
# no pins at all is also an error (#129): the stage cannot pass vacuously.
stage_manifest_pins() {
  python3 manifests/check_attestations.py --manifest manifests/sg13g2-stdcells.json
}

stage_netlists() {
  python3 design/gen_netlists.py --config layout/example_config.json \
    --out layout/lvs/netlists --check
}

stage_layouts() {
  python3 layout/gen_layouts.py --config layout/example_config.json --check
  # The recorded notch controls (layout/drc/controls/*.gds) are evidence and
  # get the same freshness check as the shipped GDS (issue #120).
  python3 layout/gen_controls.py --check
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

# Gates 4 (STA) and 5 (functional verification) of check-evidence.sh, replayed
# on the committed STA/FV record (issue #189). jq and bash only: the mutants are
# minted from the committed sta.json / functional-verification.json, never from
# a live flow run. The reject stage delegates to the shared edge-case suite in
# flow/test-check-evidence.sh --record (issue #288), so CI and the local
# post-flow run exercise one mutation list instead of two drifting copies.
# FLOW_RECORD stays on the legacy record for the stages above.
STA_FV_RECORD=flow/records/20261121-be3a384

stage_evidence_sta_fv_accept() {
  flow/check-evidence.sh flow/request-par.json \
    "$STA_FV_RECORD/place-and-route.json" \
    "$STA_FV_RECORD/lvs.json" \
    "$STA_FV_RECORD/erc.json" \
    "$STA_FV_RECORD/sta.json" \
    "$STA_FV_RECORD/functional-verification.json"
}

stage_evidence_sta_fv_reject() {
  # One shared suite (issue #288): the same jq + bash STA/FV edge cases the
  # local post-flow run exercises, replayed against the committed record.
  # Tool-free -- --record mode skips the live klt no-power control.
  flow/test-check-evidence.sh --record "$STA_FV_RECORD"
}

run_stage() {
  case "$1" in
    tests) stage_tests ;;
    attestations) stage_attestations ;;
    manifest-pins) stage_manifest_pins ;;
    netlists) stage_netlists ;;
    layouts) stage_layouts ;;
    evidence-accept) stage_evidence_accept ;;
    evidence-reject) stage_evidence_reject ;;
    evidence-sta-fv-accept) stage_evidence_sta_fv_accept ;;
    evidence-sta-fv-reject) stage_evidence_sta_fv_reject ;;
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
