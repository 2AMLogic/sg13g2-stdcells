"""Process corner definitions and the library's characterization PVT pairings.

- The classic five-corner MOS process sweep (``tt``, ``ff``, ``ss``, ``fs``,
  ``sf``) most open PDKs ship a ``.lib`` section for, as :data:`CORNERS`.
- :class:`Corner` -- one named corner: an ordered tuple of model ``.lib``
  sections, one per entry in :data:`FAMILIES`.
- :data:`CHAR_CORNER_PVT` -- this library's characterization corner pairings.

There is deliberately no corner-set registry or PVT-grid layer (removed in
#51): nothing consumed it. If a multi-corner ``klt characterize`` request
later needs a grid, add it then, against that real use.

EXTENSION POINT -- corner sections don't generalize across PDKs, and *which*
additional corners matter is block-specific. Edit the ``sections`` tuple on
the :data:`CORNERS` entries if this PDK's model library uses different
section names, or add entries to :data:`CORNERS`.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Device families in the order their ``.lib`` sections are included in the
#: generated deck. The generic core sweeps only
#: "mos" by default; a block adds families (and per-corner sections for them)
#: as it needs them.
FAMILIES: tuple[str, ...] = ("mos",)


@dataclass(frozen=True)
class Corner:
    """A named process corner: an ordered list of model ``.lib`` sections,
    one per entry in :data:`FAMILIES`."""

    name: str
    sections: tuple[str, ...]
    description: str = ""


#: The classic five MOS corners. Section names match FAMILIES = ("mos",);
#: most open PDKs use exactly these strings as their `.lib` section names --
#: if this PDK's model library uses different ones, edit the tuples below
#: rather than the surrounding mechanics.
CORNERS: dict[str, Corner] = {
    "tt": Corner("tt", ("tt",), "typical NMOS / typical PMOS"),
    "ff": Corner("ff", ("ff",), "fast NMOS / fast PMOS"),
    "ss": Corner("ss", ("ss",), "slow NMOS / slow PMOS"),
    "fs": Corner("fs", ("fs",), "fast NMOS / slow PMOS"),
    "sf": Corner("sf", ("sf",), "slow NMOS / fast PMOS"),
}

# ---------------------------------------------------------------------------
# sg13g2-stdcells characterization corners (DRAFT -- pending #1 ratification)
# ---------------------------------------------------------------------------
# The README target table's "Liberty corners" row. This is the ONE place the
# pairings live: a ratification change is an edit to CHAR_CORNER_PVT only.
# Process sections reuse the built-in tt/ff/ss corners (no core edits); V and
# T are not part of a Corner, so they are paired here -- deliberately NOT the
# 3 x 3 x 3 full factorial.

#: DRAFT (pending #1): corner name -> (supply V, temperature C).
CHAR_CORNER_PVT: dict[str, tuple[float, float]] = {
    "tt": (1.20, 25.0),
    "ff": (1.32, -40.0),
    "ss": (1.08, 125.0),
}
