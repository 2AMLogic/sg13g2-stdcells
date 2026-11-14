# Work Log

Chronological record of merged PRs and closed issues. Maintained by the Guide role.

### 2026-11-14

- **PR #84**: docs: state the recorded cell evidence in the README Status block
- **PR #83**: feat: cite the cocotb testbench and hygiene inventory for T1 items 9 and 10
- **PR #79**: feat: generate well and substrate taps, closing analog LVS on all four cells
- **Issue #76** (closed): README: bring the Status section and repo-layout tree in line with what is on main
- **Issue #75** (closed): manifests: cite the committed Liberty view, cocotb testbench and hygiene inventory for T1 items 8, 9, 10 and regrade
- **Issue #73** (closed): layout: draw well and substrate taps in gen_layouts.py and re-run LVS on the four cells

### 2026-11-13

- **PR #71**: ci: pin pytest to 9.2.0 and split the harness README's dependency claim
- **PR #68**: build: point check:ci and test at the real CI commands, collapse four test runs into one
- **PR #67**: chore: gate the committed SG13G2 netlists in CI, drop the demo placeholders
- **PR #63**: refactor(characterize): one cell-entry builder, and docs that match the committed .lib
- **Issue #70** (closed): Pin the pytest version CI installs and fix the 'no third-party dependencies' contradiction in sim/harness/README.md
- **Issue #66** (closed): Wire package.json check scripts to the real CI commands: they print 'No checks configured' and exit 0
- **Issue #65** (closed): Remove committed demo_* placeholder netlists from design/netlists and gate the real cell netlists in CI instead
- **Issue #58** (closed): Deduplicate cell-entry building in sim/characterize/request.py and fix stale 'no cells / writes no Liberty' docs
- **PR #61**: refactor(sim/harness): drop the unused tb.json manifest adapter
- **Issue #54** (closed): Remove unused from_manifest and MANIFEST_KEYS from sim/harness/evidence.py

### 2026-11-12

- **PR #53**: refactor(sim): remove unused corner-set registry and PVT grid
- **Issue #51** (closed): Remove unused corner-set registry and PvtPoint grid from sim/harness/corners.py

### 2026-11-10

- **PR #50**: refactor(sim): remove unused constants from sim/harness/__init__.py
- **Issue #34** (closed): Remove unused harness constants and test-only corner-set layer in sim/harness

### 2026-11-07

- **PR #46**: feat(layout): LVS runner, recorded LVS reports and analog T1 citations
- **PR #48**: refactor(gen): share check/write/prune logic between generators
- **PR #43**: ci: add tool-free CI workflow and README reproduction commands
- **PR #45**: feat(views): characterize generated cells to a committed TT Liberty view
- **PR #44**: feat(flow): record routed add8 GDS and klt drc evidence for T1 digital items 2, 3
- **Issue #42** (closed): Analog T1 evidence: LVS on generated cells and manifest citations for items 1, 2, 4
- **Issue #47** (closed): Dedupe check/main sync logic shared by gen_netlists.py and gen_layouts.py
- **Issue #38** (closed): No open work toward T1 after #27, and no CI workflow on main
- **Issue #39** (closed): CI workflow on main and T1 item 10 inventory
- **Issue #40** (closed): Characterize generated cells to a committed Liberty view in views/ (spec row 9)
- **Issue #41** (closed): Digital T1 evidence: routed add8 GDS and klt drc report (items 2, 3)

### 2026-11-06

- **PR #36**: feat(layout): place multi-finger devices as adjacent poly columns
- **Issue #35** (closed): layout: place multi-finger devices in gen_layouts.py so drive-2 and 4-input cells lay out
- **PR #32**: refactor(sim): remove dead PVT-grid and sabotage helpers
- **Issue #31** (closed): Remove dead grid helpers left in sim/harness/corners.py after #21
- **PR #29**: refactor(sim): remove unexercised local-ngspice half of sim/harness
- **PR #28**: feat(manifests): add block manifest and graded klt signoff T1 report
- **PR #12**: docs(spec): add target-specification decision record and sync README table
- **Issue #21** (closed): Remove unexercised local-ngspice half of sim/harness (cli, runner, testbench, pdk, toolchain)
- **Issue #27** (closed): manifests: block manifest and first graded klt signoff T1 verdict
- **Issue #1** (closed): Ratify the target specification

### 2026-11-05

- **PR #23**: feat: add config-driven static-CMOS cell layout generator with --check
- **PR #20**: fix: preload psp103.osdi and record first real klt characterize run
- **PR #19**: refactor: route characterization driver through harness corners and validated evidence
- **Issue #22** (closed): Add a config-driven cell layout generator (netlist + process config -> GDS) with --check
- **Issue #17** (closed): Consolidate characterize driver onto harness corners and CharacterizationExtensions
- **Issue #8** (closed): sim: drive klt characterize for a baseline sg13g2_stdcell cell and record evidence
- **Issue #2** (closed): Harness bootstrap

### 2026-11-04

- **PR #18**: feat: reject generator-colliding pin names and add configurable width grid
- **PR #15**: feat: add add8 baseline flow on sg13g2_stdcell with recorded power gates
- **PR #14**: feat: add klt characterize driver and append-only per-arc evidence records
- **PR #13**: feat: add draft characterization corner set and validated characterization evidence
- **PR #11**: feat: add PDK-independent static-CMOS netlist generator
- **PR #10**: feat: add __main__.py so the sim harness runs as a module
- **PR #6**: Resync Loom 0.19.382 → 0.19.1263 ahead of fleet admission
- **Issue #16** (closed): gen_netlists: reject pin names colliding with generated nodes; make width grid a config key
- **Issue #9** (closed): flow: synthesis + place-and-route skeleton and baseline benchmark against sg13g2_stdcell
- **Issue #7** (closed): sim/harness: register characterization corners and validated evidence fields
- **Issue #5** (closed): Land a PDK-independent static-CMOS netlist generator (topology from boolean functions)
- **Issue #4** (closed): sim/harness: no __main__.py, so documented 'python -m sim.harness' fails
