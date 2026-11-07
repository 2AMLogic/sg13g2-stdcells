#!/usr/bin/env bash
# Baseline run of the klt digital flow on IHP SG13G2 / sg13g2_stdcell (issue #9):
# synthesize -> place-and-route (target_stage route, with power) -> extract ->
# LVS (gate-level-verilog) -> ERC supply read -> routed-GDS export + klt drc ->
# check-evidence.sh.
# Single local runs only; no corner or Monte Carlo grids, no SPICE.
#
# Usage: flow/run.sh [--pdk-root DIR]   (PDK_ROOT must resolve ihp-sg13g2)
# Records: flow/records/<UTC date>-<short HEAD>/ (refuses to overwrite one).
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; cd "$here"
PDK_ARGS=(--pdk ihp-sg13g2); [ "${1:-}" = "--pdk-root" ] && PDK_ARGS+=(--pdk-root "$2")
rec="records/${RECORD_ID:-$(date -u +%Y%m%d)-$(git rev-parse --short HEAD)}"
[ -e "$rec" ] && { echo "refusing to overwrite $rec (append-only)" >&2; exit 2; }
mkdir -p "$rec" build; rm -rf .klt

klt synthesize request-synth.json "${PDK_ARGS[@]}" --format json > "$rec/synthesize.json"
netlist="$(jq -r '.netlist_path.path' "$rec/synthesize.json")"
cp "../$netlist" build/add8_synth.v
klt place-and-route request-par.json "${PDK_ARGS[@]}" --format json > "$rec/place-and-route.json"
gds="$(jq -r .gds_path "$rec/place-and-route.json")"; vlog="$(jq -r .verilog_path "$rec/place-and-route.json")"
klt extract "$gds" --deck sg13g2 --top add8 --abstract-cells 'sg13g2_*' --def-net-names \
    -o build/add8.gate.spice --format json > "$rec/extract.json"
jq --arg l add8.gate.spice --arg v "$vlog" '.layout.netlist=$l | .reference.netlist=$v' \
    request-lvs.json > build/lvs.json
# klt exits non-zero on a mismatch/violation; keep the envelope and gate on it below.
klt lvs build/lvs.json --format json > "$rec/lvs.json" || true
klt erc "$gds" erc-spec.json --top add8 --deck sg13g2 --format json > "$rec/erc.json" || true
# Preserve the routed GDS (rm -rf .klt above discards it next run) and DRC it.
# Small GDS is committed; set GDS_HASH_ONLY=1 to keep only sha256+size in git.
if [ "${GDS_HASH_ONLY:-0}" = 1 ]; then
    { sha256sum "$gds" | cut -d' ' -f1; stat -c %s "$gds"; } > "$rec/add8.routed.gds.sha256"
else
    cp "$gds" "$rec/add8.routed.gds"
fi
# Non-clean DRC exits non-zero: keep the envelope, record as is (like lvs/erc).
klt drc "$gds" --deck sg13g2 --top add8 "${PDK_ARGS[@]}" --format json > "$rec/drc.json" || true
cp build/add8_synth.v "$rec/add8_synth.v"; cp "$vlog" "$rec/add8.routed.v"
cp "$rec/lvs.json" build/lvs.out.json; cp "$rec/erc.json" build/erc.json
./check-evidence.sh request-par.json "$rec/place-and-route.json" "$rec/lvs.json" "$rec/erc.json"
echo "all three power gates hold; record: flow/$rec"
