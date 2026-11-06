# sim

Testbenches and PVT corner results (ngspice). harness/ carries the PVT corner definitions, evidence schema and record-id helpers (see harness/README.md). Simulation runs through `klt` (see characterize/), not a local ngspice runner.

## characterize/

Drives `klt characterize` for one existing `sg13g2_stdcell` cell (baseline leg;
this repo has no cells of its own yet) and appends the raw per-arc delay /
transition / energy tables as an evidence record under
`sim/characterize/records/<record-id>.md`, using the harness record-id scheme
(`allocate_record_id`). Each record carries the slew and load axes, per-arc
values, the klt version and provenance, and the repo commit. Re-running mints a
new id; nothing is overwritten. This package writes no Liberty — `klt` owns
that, and its `.lib` stays in a scratch directory.

```
python3 -m sim.characterize --pdk-dir <ihp-sg13g2 dir> [--backend local|batch]
python3 -m unittest sim.characterize.tests.test_request
```

One corner per invocation (TT/1.20 V/25 C by default). FF/SS are one
invocation per corner with `--backend batch`, never a local loop.

**Status**: first real record, `sim/characterize/records/20261105-042154-1376b8f.md`
(`sg13g2_inv_1`, TT/1.20 V/25 C, 5x5 slew x load grid, one arc, local backend,
klt 0.9.0.dev1379, ngspice-46). The local run needs ngspice >= 44 for the OSDI
v0.4 PSP103 models. The request preloads `psp103.osdi` (the module the PDK's
`psp103va` model cards bind to), not `psp103_nqs.osdi`. FF/SS corners are not
yet run (batch only).
