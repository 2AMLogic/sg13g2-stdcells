# Work Log

Chronological record of merged PRs and closed issues. Maintained by the Guide role.

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
