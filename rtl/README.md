# rtl

Verilog sources.

| File | What it is |
|---|---|
| `add8.v` | 8-bit combinational adder with carry in/out. The benchmark design for the `sg13g2_stdcell` baseline run (issue #9). Combinational only: this library has no sequential cells in scope, so a design with flops could never be remapped onto it. Not the final benchmark choice; if #1 names one it replaces this. |
