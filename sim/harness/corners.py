"""This library's characterization corner pairings: process, supply, temperature.

There is deliberately no corner-set registry or PVT-grid layer (removed in
#51) and no multi-family / five-corner process layer (removed in #109):
nothing consumed either. If a multi-corner ``klt characterize`` request later
needs a grid, or a different process mapping is ever needed, add rows here
against that real use.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# sg13g2-stdcells characterization corners (spec 0001 Row 9)
# ---------------------------------------------------------------------------
# The README target table's "Liberty corners" row. This is the ONE place the
# pairings live: a spec change is an edit to CHAR_CORNER_PVT only.
# TT is the target corner; FF and SS are stretch (spec 0001 Row 9, RATIFIED).
# Each row carries its own model ``.lib`` process section (this PDK's
# cornerMOSlv.lib uses ``mos_<corner>``) plus the supply/temperature pairing --
# deliberately NOT the 3 x 3 x 3 full factorial.

#: Ratified (spec 0001 Row 9): corner name -> (process section, supply V, temperature C).
CHAR_CORNER_PVT: dict[str, tuple[str, float, float]] = {
    "tt": ("mos_tt", 1.20, 25.0),
    "ff": ("mos_ff", 1.32, -40.0),
    "ss": ("mos_ss", 1.08, 125.0),
}
