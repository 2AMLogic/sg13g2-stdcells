"""Pure request building for ``klt characterize`` (no simulator, no klt)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

#: Default NLDM axes: input transition (ns) x output load (pF). Strictly
#: ascending, as klt requires.
DEFAULT_SLEWS_NS: tuple[float, ...] = (0.02, 0.05, 0.1, 0.2, 0.4)
DEFAULT_LOADS_PF: tuple[float, ...] = (0.001, 0.003, 0.01, 0.03, 0.1)

#: Models: the low-voltage MOS corner library and the PSP103 OSDI that its
#: devices need preloaded (paths relative to the PDK variant directory).
MODEL_LIB = "libs.tech/ngspice/models/cornerMOSlv.lib"
OSDI_PRELOAD = ("libs.tech/ngspice/osdi/psp103_nqs.osdi",)
CELL_NETLIST = "libs.ref/sg13g2_stdcell/spice/sg13g2_stdcell.spice"


class RequestError(ValueError):
    """The request inputs are malformed (raised before klt is ever run)."""


@dataclass(frozen=True)
class Corner:
    name: str
    process: str  # model-library section, e.g. "mos_tt"
    supply_v: float
    temperature_c: float


TT = Corner("tt_1p20v_25c", "mos_tt", 1.20, 25.0)


@dataclass(frozen=True)
class CellSpec:
    name: str
    inputs: tuple[str, ...]
    #: output pin name -> Liberty boolean function
    outputs: dict[str, str]
    vdd: str = "VDD"
    gnd: str = "VSS"
    netlist: str = CELL_NETLIST  # relative to the PDK dir unless absolute
    extra: dict = field(default_factory=dict)


#: Baseline leg: the existing sg13g2_stdcell inverter (this repo has no cells).
SG13G2_INV_1 = CellSpec("sg13g2_inv_1", inputs=("A",), outputs={"Y": "!A"})


def _axis(values, label: str) -> list[float]:
    vals = [float(v) for v in values]
    if not vals:
        raise RequestError(f"{label} axis is empty")
    if any(v <= 0 for v in vals):
        raise RequestError(f"{label} axis must be positive")
    if any(b <= a for a, b in zip(vals, vals[1:])):
        raise RequestError(f"{label} axis must be strictly ascending")
    return vals


def build_request(
    cell: CellSpec,
    corner: Corner,
    pdk_dir: str | Path,
    slews_ns=DEFAULT_SLEWS_NS,
    loads_pf=DEFAULT_LOADS_PF,
    keep_artifacts: bool = False,
) -> dict:
    """Return a single-cell, single-corner ``klt characterize`` request dict.

    All paths are absolute so the request means the same wherever it is written.
    """
    pdk = Path(pdk_dir)
    if not cell.inputs or not cell.outputs:
        raise RequestError(f"cell {cell.name!r} needs at least one input and one output")
    netlist = Path(cell.netlist)
    if not netlist.is_absolute():
        netlist = pdk / netlist
    pins = [{"name": n, "direction": "input"} for n in cell.inputs]
    pins += [{"name": n, "direction": "output", "function": f} for n, f in cell.outputs.items()]
    return {
        "cell": {
            "name": cell.name,
            "netlist": str(netlist),
            "pins": pins,
            "power_pins": {"vdd": cell.vdd, "gnd": cell.gnd},
        },
        "corner": {
            "name": corner.name,
            "process": corner.process,
            "supply_v": corner.supply_v,
            "temperature_c": corner.temperature_c,
        },
        "grid": {
            "input_transition_ns": _axis(slews_ns, "slew"),
            "output_load_pf": _axis(loads_pf, "load"),
        },
        "models": {"lib": str(pdk / MODEL_LIB)},
        "options": {
            "osdi_preload": [str(pdk / p) for p in OSDI_PRELOAD],
            "keep_artifacts": keep_artifacts,
        },
    }
