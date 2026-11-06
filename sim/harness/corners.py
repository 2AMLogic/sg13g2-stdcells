"""Process / voltage / temperature corner definitions and PVT grid mechanics.

GENERIC CORE:

- The classic five-corner MOS process sweep (``tt``, ``ff``, ``ss``, ``fs``,
  ``sf``) most open PDKs ship a ``.lib`` section for, registered below as the
  default ``CORNER_SETS["mos"]``. ``CORNER_SETS["tt"]`` is the reduced,
  single-corner smoke-test set (not a valid evidence matrix on its own).
- :class:`Corner`, :class:`PvtPoint`, :func:`resolve_corners` -- corner and
  PVT-point definitions and name resolution.

EXTENSION POINT -- corner sections don't generalize across PDKs (a PDK's
``.lib`` section names for "fast", "slow", or a device family other than MOS
are PDK-specific), and *which* additional corners matter is block-specific
(a SAR ADC cares about CDAC capacitor corners; a bandgap cares about
resistor and BJT corners; plenty of blocks need only the five MOS corners
as-is). Two ways to extend:

1. Edit the ``sections`` tuple on the built-in :data:`CORNERS` entries if
   this PDK's model library uses different section names than the
   ``tt``/``ff``/``ss``/``fs``/``sf`` default (most open PDKs use exactly
   these names; if not, this is the one edit new to this PDK).
2. Add entries to :data:`CORNERS` and call :func:`register_corner_set` to
   name groups of them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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

CORNER_SETS: dict[str, tuple[str, ...]] = {
    # Minimum bar for a quick smoke run. Not a valid evidence matrix on its own.
    "tt": ("tt",),
    # The five classic MOS corners -- the default.
    "mos": ("tt", "ff", "ss", "fs", "sf"),
}
DEFAULT_CORNER_SET = "mos"


def register_corner_set(name: str, corner_names: tuple[str, ...]) -> None:
    """Extension point: name a group of (already-registered) corners."""
    unknown = [c for c in corner_names if c not in CORNERS]
    if unknown:
        raise KeyError(f"corner set {name!r} references unknown corner(s): {unknown}")
    CORNER_SETS[name] = tuple(corner_names)


def resolve_corners(names: list[str] | tuple[str, ...] | None) -> list[Corner]:
    """Turn a list of corner *or* corner-set names into Corner objects."""
    if not names:
        names = [DEFAULT_CORNER_SET]
    resolved: list[Corner] = []
    seen: set[str] = set()
    for name in names:
        expanded = CORNER_SETS.get(name, (name,))
        for corner_name in expanded:
            if corner_name in seen:
                continue
            if corner_name not in CORNERS:
                raise KeyError(
                    f"unknown corner {corner_name!r}; "
                    f"known corners: {', '.join(sorted(CORNERS))}; "
                    f"known sets: {', '.join(sorted(CORNER_SETS))}"
                )
            seen.add(corner_name)
            resolved.append(CORNERS[corner_name])
    return resolved


@dataclass(frozen=True)
class PvtPoint:
    """One point in the PVT grid -- exactly one ngspice invocation."""

    corner: Corner
    temp_c: float
    vdd: float
    index: int = field(default=0, compare=False)


# ---------------------------------------------------------------------------
# sg13g2-stdcells characterization corners (DRAFT -- pending #1 ratification)
# ---------------------------------------------------------------------------
# The README target table's "Liberty corners" row. This is the ONE place the
# pairings live: a ratification change is an edit to CHAR_CORNER_PVT only.
# Process sections reuse the built-in tt/ff/ss corners (no core edits); V and
# T are not part of a Corner, so they are paired here and surfaced as exactly
# three PvtPoints -- deliberately NOT the 3 x 3 x 3 full factorial.

#: Name of the corner set registered below.
CHAR_CORNER_SET = "sg13g2-stdcells-char"

#: DRAFT (pending #1): corner name -> (supply V, temperature C).
CHAR_CORNER_PVT: dict[str, tuple[float, float]] = {
    "tt": (1.20, 25.0),
    "ff": (1.32, -40.0),
    "ss": (1.08, 125.0),
}

register_corner_set(CHAR_CORNER_SET, tuple(CHAR_CORNER_PVT))


def characterization_points() -> list[PvtPoint]:
    """The three paired characterization PVT points, in ``CHAR_CORNER_PVT`` order."""
    return [
        PvtPoint(corner=CORNERS[name], temp_c=temp_c, vdd=vdd, index=i)
        for i, (name, (vdd, temp_c)) in enumerate(CHAR_CORNER_PVT.items())
    ]
