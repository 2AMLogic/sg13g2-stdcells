# views

Generated Liberty views, one per characterization corner. The view name is
derived from the corner's supply/temperature pairing in
`sim.harness.corners.CHAR_CORNER_PVT` (`sim.characterize.request.library_view_name`):
`sg13g2_stdcells_<corner>_<supply>v_<temp>c`, with negative temperatures
spelling `m` for minus — so TT/1.20 V/25 C is `sg13g2_stdcells_tt_1p20v_25c.lib`
and FF/1.32 V/-40 C is `sg13g2_stdcells_ff_1p32v_m40c.lib`. LEF abstracts are
future work (ROADMAP.md).

## Liberty: `sg13g2_stdcells_tt_1p20v_25c.lib`

NLDM Liberty at TT / 1.20 V / 25 C for the cells in `layout/example_config.json`
(spec row 9), emitted by `klt characterize`. Do not edit it by hand; regenerate:

```
python3 -m sim.characterize --library --pdk-dir <ihp-sg13g2 dir>
```

The command regenerates each cell's SPICE with `design/gen_netlists.py` from the
same config, runs one `cells`-form `klt characterize` request (a single corner,
so it runs locally), rewrites the `.lib` and its `.lib.provenance` sidecar
(klt version, repo commit, corner, config path and SHA-256, the IHP-Open-PDK
commit the `--pdk-dir` checkout was at, evidence record id), and appends a
record under `sim/characterize/records/`. Combinational arcs only. The
`--pdk-dir` must be a clean IHP-Open-PDK git checkout — the run refuses
otherwise, and how to make one at the pinned commit is in the root README
("Reproducing the characterization").
