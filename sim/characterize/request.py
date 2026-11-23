"""Pure request building for ``klt characterize`` (no simulator, no klt)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..harness.corners import CHAR_CORNER_PVT

#: Default NLDM axes: input transition (ns) x output load (pF). Strictly
#: ascending, as klt requires.
DEFAULT_SLEWS_NS: tuple[float, ...] = (0.02, 0.05, 0.1, 0.2, 0.4)
DEFAULT_LOADS_PF: tuple[float, ...] = (0.001, 0.003, 0.01, 0.03, 0.1)

#: Models: the low-voltage MOS corner library and the PSP103 OSDI that its
#: `.model ... psp103va` cards need (psp103_nqs.osdi registers a different module
#: name, so it leaves them "unknown model type"). Paths are relative to the PDK
#: variant directory.
MODEL_LIB = "libs.tech/ngspice/models/cornerMOSlv.lib"
OSDI_PRELOAD = ("libs.tech/ngspice/osdi/psp103.osdi",)


class RequestError(ValueError):
    """The request inputs are malformed (raised before klt is ever run)."""


#: Corner used by the CLI driver; a key of ``sim.harness.corners.CHAR_CORNER_PVT``.
DEFAULT_CORNER = "tt"


def corner_block(name: str) -> dict:
    """The klt request ``corner`` block for characterization corner ``name``.

    Everything comes from ``CHAR_CORNER_PVT`` -- this module keeps no copy of it.
    """
    if name not in CHAR_CORNER_PVT:
        raise RequestError(
            f"{name!r} is not a characterization corner ({', '.join(CHAR_CORNER_PVT)})"
        )
    process, supply_v, temperature_c = CHAR_CORNER_PVT[name]
    return {
        "name": name,
        "process": process,
        "supply_v": supply_v,
        "temperature_c": temperature_c,
    }


@dataclass(frozen=True)
class CellSpec:
    name: str
    inputs: tuple[str, ...]
    #: output pin name -> Liberty boolean function
    outputs: dict[str, str]
    netlist: str  # relative to the PDK dir unless absolute
    vdd: str = "VDD"
    gnd: str = "VSS"


def _axis(values, label: str) -> list[float]:
    vals = [float(v) for v in values]
    if not vals:
        raise RequestError(f"{label} axis is empty")
    if any(v <= 0 for v in vals):
        raise RequestError(f"{label} axis must be positive")
    if any(b <= a for a, b in zip(vals, vals[1:])):
        raise RequestError(f"{label} axis must be strictly ascending")
    return vals


def _cell_entry(cell: CellSpec, pdk: Path) -> dict:
    """The klt block describing one cell: the only place a cell is described.

    A new pin attribute or power-pin convention is changed once, here (each entry
    of :func:`build_library_request`'s ``cells`` list).
    """
    if not cell.inputs or not cell.outputs:
        raise RequestError(f"cell {cell.name!r} needs at least one input and one output")
    netlist = Path(cell.netlist)
    if not netlist.is_absolute():
        netlist = pdk / netlist
    pins = [{"name": n, "direction": "input"} for n in cell.inputs]
    pins += [{"name": n, "direction": "output", "function": f} for n, f in cell.outputs.items()]
    return {
        "name": cell.name,
        "netlist": str(netlist),
        "pins": pins,
        "power_pins": {"vdd": cell.vdd, "gnd": cell.gnd},
    }


def library_view_name(corner: str) -> str:
    """The Liberty view name for characterization corner ``corner``.

    Derived from ``CHAR_CORNER_PVT`` -- supply and temperature are read from the
    table, never retyped: ``sg13g2_stdcells_tt_1p20v_25c`` at the default
    corner, ``sg13g2_stdcells_ff_1p32v_m40c`` at FF (negative temperatures
    spell ``m`` for minus).
    """
    if corner not in CHAR_CORNER_PVT:
        raise RequestError(
            f"{corner!r} is not a characterization corner ({', '.join(CHAR_CORNER_PVT)})"
        )
    _, supply_v, temperature_c = CHAR_CORNER_PVT[corner]
    supply = f"{supply_v:.2f}".replace(".", "p")
    sign = "m" if temperature_c < 0 else ""
    return f"sg13g2_stdcells_{corner}_{supply}v_{sign}{abs(temperature_c):.0f}c"


#: Name of the committed library view's Liberty library (the default corner's
#: view, via :func:`library_view_name`).
LIBRARY_NAME = library_view_name(DEFAULT_CORNER)


def cells_from_config(config_path: str | Path, netlist_dir: str | Path) -> list[CellSpec]:
    """One :class:`CellSpec` per cell of a ``design/gen_netlists.py`` config.

    Pins and Liberty functions come from the config's ``inputs``/``outputs`` (never
    retyped here); each cell's SPICE is ``<netlist_dir>/<cell>.spice`` as emitted by
    ``design/gen_netlists.py`` from the *same* config.
    """
    cfg = json.loads(Path(config_path).read_text())
    process = cfg["process"]
    cells = cfg.get("cells") or []
    if not cells:
        raise RequestError(f"{config_path}: config declares no cells")
    nl = Path(netlist_dir).resolve()
    return [
        CellSpec(
            c["name"],
            inputs=tuple(c["inputs"]),
            outputs=dict(c["outputs"]),
            vdd=process.get("vdd_net", "VDD"),
            gnd=process.get("vss_net", "VSS"),
            netlist=str(nl / f"{c['name']}.spice"),
        )
        for c in cells
    ]


def build_library_request(
    cells: list[CellSpec],
    corner: str,
    pdk_dir: str | Path,
    library_name: str | None = None,
    slews_ns=DEFAULT_SLEWS_NS,
    loads_pf=DEFAULT_LOADS_PF,
) -> dict:
    """Return a multi-cell, single-corner ``klt characterize`` request (``cells`` form).

    One ``.lib`` results.
    The library name defaults to :func:`library_view_name` of this corner, so a
    request never claims another corner's name.
    """
    if not cells:
        raise RequestError("a library request needs at least one cell")
    names = [c.name for c in cells]
    if len(set(names)) != len(names):
        raise RequestError("duplicate cell names in library request")
    library_name = library_name or library_view_name(corner)
    pdk = Path(pdk_dir)
    return {
        "corner": corner_block(corner),
        "grid": {
            "input_transition_ns": _axis(slews_ns, "slew"),
            "output_load_pf": _axis(loads_pf, "load"),
        },
        "models": {"lib": str(pdk / MODEL_LIB)},
        "options": {
            "osdi_preload": [str(pdk / p) for p in OSDI_PRELOAD],
            "keep_artifacts": False,
        },
        "library": {"name": library_name},
        "cells": [_cell_entry(c, pdk) for c in cells],
    }
