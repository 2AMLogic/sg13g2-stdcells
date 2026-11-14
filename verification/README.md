# verification

cocotb testbenches. Recorded results are append-only evidence.

| File | What it is |
|---|---|
| `test_add8.py` | exhaustive cocotb check of `rtl/add8.v` — all 2^17 `a`/`b`/`cin` cases |
| `Makefile` | cocotb + Icarus harness (`RTL_DIR` overrides the DUT dir, e.g. to run the same test on a synthesized netlist) |
| `cold_start.sh` | provisions cocotb in a throwaway virtualenv and runs the testbench from a clean checkout |

## Running it

With cocotb and Icarus already on `PATH`:

```
make -C verification
```

From a clean checkout, with neither provisioned (this repo's CI is deliberately
tool-free, and a stock dispatch host has no cocotb):

```
sh verification/cold_start.sh          # COCOTB_VERSION=2.0.0 by default
```

`cold_start.sh` creates a virtualenv under `$TMPDIR`, installs the pinned
cocotb, clears `sim_build/` so the run cannot pass on stale simulator output,
runs the testbench and removes the virtualenv on exit. It never writes to the
host's own tools. Icarus is the one thing it cannot provision — it is a system
package, not a wheel — so it fails loudly naming `iverilog` rather than
skipping the run.

Either way the exit status is the testbench's: cocotb's Makefile fails the
build on a failing test (verified — an adder that drops `cin` exits 2), so a
zero exit means the exhaustive check really passed.

## T1 item 9

`cold_start.sh` is what `manifests/inventories/item9.digital.json` declares as
the T1 item 9 cold-start command, and `klt signoff --attest 9` **runs** it —
the attestation is an executed check, not a declaration. Re-verify the
committed envelope with:

```
klt signoff --attest 9 --inventory manifests/inventories/item9.digital.json \
    --check manifests/envelopes/item9.digital.attest.json
```

That re-runs the cold start, so it needs Icarus and network access for the
cocotb install. The inventory pins `iverilog` 13.0 and `cocotb` 2.0.0, and
records the explicit no-PDK form: `test_add8.py` drives behavioral RTL with no
cell library, SDF or parasitics, so the cold start consumes no PDK.
