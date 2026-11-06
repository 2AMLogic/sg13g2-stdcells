# sg13g2-stdcells — agent instructions

Open-source canary block: a 8-Track Standard-Cell Library on the IHP SG13G2 PDK,
designed and verified by AI agents — a **mixed-signal** block.

- **PDK**: IHP SG13G2 (open PDK).
  Digital: cocotb + Icarus, Yosys, OpenROAD. Analog: xschem + ngspice.
  Layout, DRC, and LVS go through klayout-tools (`klt`).
- **Friction protocol (the canary's job)**: every time klayout-tools is
  awkward, missing a capability, or wrong for what you need, file an issue at
  `2AMLogic/klayout-tools` describing the tool gap generically — that tracker is
  scoped to the tool, so keep design-specific detail (spec values, this repo's
  content) out of it and describe the gap, not the design.
- **Verification is the product**: no claim without a testbench. Recorded
  results are append-only evidence; a result is not superseded by deletion, it
  is superseded by a later record that says why.
- Spec changes go through `spec/` with a decision record. Agents do not relax
  the ratified spec to make a result pass.
- **Ratification is a merged PR, and the status line merges with it.**
  Ratifying a decision record is the act of that record's own PR being
  reviewed and merged — two reviewer keys, `ratification/ee-key/` and
  `ratification/market-key/`, neither held by an author of the PR or the
  design. The record's own `Status:` line is part of what gets merged: flip it
  from `proposed` to `RATIFIED` (or mark the ratified rows, for a partial
  ratification) **in the PR itself**, once both keys are posted and before the
  merge. Never as a follow-up commit afterwards — a merged record still saying
  `proposed` is indistinguishable from one nobody ever ratified.

- **Scope discipline — do not restate ETH Zurich's numbers as ours.** This
  repo's reference, EZ130 8T (arXiv:2609.29965), publishes area and energy
  wins over `sg13g2_stdcell` measured with commercial tools on their cells.
  Those figures belong to them. They may be cited as a reference point, always
  attributed and always labelled as theirs; they may never appear in this
  repo's Status block, target table result column, or any claim about what
  this library achieves. The two sources also disagree — the paper says 35%
  area / 39% energy, the ETH library page says 33% for both — so any number
  taken from them is cited with which source it came from. A comparison
  becomes ours only when this repo has run the benchmark on cells it built and
  recorded the result as evidence.
- **A library is a generator, not a block.** The unit of work here is a cell
  family with shared templates, not one drawn instance. Resist hand-drawing
  the second cell that differs from the first only by drive strength or input
  count — if it cannot be generated, the generator is the bug. This is the
  main way this canary differs from every sibling, and the main way it will
  drift back into looking like them.

## Harness bootstrap

Two siblings, because this canary has two halves and no single sibling has both.

- **Analog/device half — copy `sg13g2-opamp`.** It is the nearest SG13G2
  canary with a real transistor-level `sim/` tree, so it supplies the PDK
  resolution, corner sweep, and evidence-recording patterns for per-cell
  SPICE characterization. Same process, same device models, same `klt` DRC/LVS
  path. Only its corner, evidence-schema and record-id patterns were kept
  (`sim/harness/`); the local-ngspice runner half was removed (#21) —
  simulation goes through `klt sim` / `klt characterize`.
- **Digital/flow half — copy `sky130-modexp`.** It is the program's first
  digital canary, so it supplies the `rtl/` + `flow/` + `verification/` shape:
  Yosys synthesis and OpenROAD place-and-route driven through `klt`, with
  cocotb for functional checks. That is the machinery the synthesis benchmark
  in the README's target table runs on.

Copy the patterns, not the content. Neither sibling builds a cell library, so
the generator layer on top of both is this repo's own.

<!-- BEGIN LOOM ORCHESTRATION -->
This repository uses [Loom](https://github.com/rjwalters/loom) for AI-powered development orchestration — see the Loom repository for the full guide (roles, labels, worktrees, configuration). When installed, Loom also writes a locally-substituted copy of that guide to `.loom/CLAUDE.md`.

Work is coordinated through `loom:` labels on issues and pull requests, and the same roles run either under `loom-daemon` or by hand in an attended session — daemon mode is optional. Create the labels once with `.loom/scripts/sync-labels.sh` (an install ships `.github/labels.yml` but does not create the labels on the forge). A pull request ready for review carries `loom:review-requested`; Judge reviews it and applies `loom:pr` (approved) or `loom:changes-requested`; Doctor fixes a `loom:changes-requested` pull request and returns it to `loom:review-requested`. Only a `loom:pr` pull request gets merged, and always via this repo's merge script (`.loom/scripts/merge-pr.sh`) — never a raw forge merge command such as `gh pr merge`. Full state machine: `.loom/docs/label-state-machine.md`.
<!-- END LOOM ORCHESTRATION -->
