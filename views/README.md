# views

Generated abstract views (LEF, Liberty).

## Liberty: `sg13g2_stdcells_tt_1p20v_25c.lib`

NLDM Liberty at TT / 1.20 V / 25 C for the cells in `layout/example_config.json`
(spec row 9), emitted by `klt characterize`. Do not edit it by hand; regenerate:

```
python3 -m sim.characterize --library --pdk-dir <ihp-sg13g2 dir>
```

The command regenerates each cell's SPICE with `design/gen_netlists.py` from the
same config, runs one `cells`-form `klt characterize` request (a single corner,
so it runs locally), rewrites the `.lib` and its `.lib.provenance` sidecar
(klt version, repo commit, corner, config path and SHA-256, evidence record id),
and appends a record under `sim/characterize/records/`. Combinational arcs only.
