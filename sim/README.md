# sim

Testbenches and PVT corner results (ngspice). harness/ carries the generic sim-harness-core scaffold (see harness/README.md); testbenches and results are empty until there is something to simulate.

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

**Status: no record has been produced yet.** The PSP103 OSDI models are OSDI
v0.4 and need ngspice >= 44; this host has 42, and the batch backend rejects a
host-path `osdi_preload` (filed as 2AMLogic/klayout-tools#4911). The request
builder and record writer are covered by unit tests only.
