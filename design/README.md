# design

Schematics (xschem) and the cell-family netlist generator.

## `gen_netlists.py` — PDK-independent static-CMOS generator

Turns a config (process parameters + cell list with boolean output functions)
into deterministic transistor-level SPICE, one `<cell>.spice` per cell. The
engine contains no PDK constants; everything PDK-specific is injected through
the config. stdlib only.

```
python3 design/gen_netlists.py --config design/example_config.json            # write
python3 design/gen_netlists.py --config design/example_config.json --check    # freshness
python3 -m unittest discover -s design/tests                                  # tests
```

`--out` defaults to `<config dir>/netlists`. Exit codes: `0` ok/fresh, `1`
`--check` found changed, missing or stray `.spice` files, `2` invalid config or
function string. Output is byte-deterministic (sorted, no timestamps), so
`--check` is a byte compare.

### Config contract (`schema_version` 1)

```jsonc
{
  "schema_version": 1,
  "process": {                       // every key required
    "supply_v": 1.0,                 // number; printed in the header comment only
    "l_nm": 100,                     // channel length, nm
    "unit_n_nm": 500, "unit_p_nm": 800,   // unit device widths, nm; must be multiples of the grid
    "grid_nm": 10,                   // optional positive int (default 10): width grid for unit widths and fingers
    "finger_max_n": 1000, "finger_max_p": 1200,  // max width per finger, nm (>= 10; unsplittable widths exit 2)
    "nmos_model": "...", "pmos_model": "...",    // model/subckt name per device
    "nmos_prefix": "XMN", "pmos_prefix": "XMP",  // instance-name prefixes (+ index)
    "vdd_net": "VDD", "vss_net": "VSS",          // rails; also the bulk nets
    "device_params": "w={w} l={l} ng={ng} m=1"   // only {w} {l} {ng} placeholders
  },
  "cells": [{
    "name": "demo_a21oi_1", "family": "a21oi", "drive": 1,   // drive: int >= 1
    "inputs": ["A1", "A2", "B1"],                            // port order
    "outputs": {"Y": "!((A1*A2)+B1)"}                        // port name -> function
  }]
}
```

Extra keys (e.g. `library`, `scope`) are ignored, so a port may keep its own
metadata in the same file. Cell names must be unique and every variable in a
function must be a declared input.

**Reserved pin names.** The generator mints internal nodes named `n<digits>`,
`<pin>_b` and `<pin>_i`, so no input/output pin may match `n<digits>` or end in
`_b`/`_i` (case-sensitive; `n`, `nA` are fine), equal `vdd_net`/`vss_net`, or
appear in both `inputs` and `outputs`. `validate()` rejects these naming the cell and pin.

**Function syntax.** `!` not, `*` and, `+` or, `^` xor, parentheses. `*`, `+`
and `^` cannot be mixed at one nesting level without parentheses (no precedence
is assumed). Empty or malformed strings are rejected.

**Topology.** Functions are put in negation normal form; XOR/XNOR and mux
selects use literal-complement structure, with one shared unit inverter per
inverted input. A `!g` output is one inverting stage; a non-inverting output is
an inverting stage (drive `max(1, drive // 2)`) plus an output inverter (full
drive). Device width = unit × stage scale × longest series path through that
device, split into the fewest equal fingers within the finger cap.

**Netlist shape.** `.subckt <name> <inputs> <sorted outputs> <vdd> <vss>`; one
device line per transistor: `<prefix><i> d g s bulk model <device_params>`.

### Scope

`example_config.json` and `netlists/` are a placeholder demo (`demo_nmos` /
`demo_pmos`, made-up sizes), used only by the tests. They are not an SG13G2
catalog or sizing; that waits for a ratified spec. Nothing here states an area
or energy result.
