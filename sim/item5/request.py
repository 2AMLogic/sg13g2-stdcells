"""Pure builders for the T1 item-5 analog ``klt sim`` testbenches (spec row 9).

No simulator, no klt, no filesystem access: everything here is deterministic
and unit-tested (``tests/test_request.py``) so a committed request document
can be re-derived from the committed sources it reads (the cell config and
the Liberty view) and compared byte-for-byte.

Two testbench kinds, one request + netlist pair per cell:

* **function** -- one unloaded DUT, inputs stepped through every input
  combination, output sampled mid-state.  The check is "the settled output
  sits at the rail the Liberty ``function`` attribute demands" (limits from
  the config's supply rails).
* **timing** -- one DUT per (timing arc, input transition, output load) grid
  point of the committed Liberty view, each instance with its own PWL ramp
  source and private load capacitor, all in one ``tran`` -- the same
  one-deck-many-instances layout ``klt characterize`` uses (see its docs,
  "How it works").  Delay is measured input-threshold -> output-threshold
  and transition between the library's own slew thresholds on the output
  edge, driven by a linear rail-to-rail ramp whose threshold-to-threshold
  duration equals the tabulated input transition (``ramp = slew /
  (slew_hi - slew_lo)``) -- every convention read from the view's own
  header, none retyped -- so the measured quantity is the same one the
  view tabulates and the limit is agreement with the view's value at that
  same (slew, load) point.

Cell netlists are never written here: each generated testbench ``.include``s
the committed ``design/gen_netlists.py`` output under ``layout/lvs/netlists/``
(the files CI's ``netlists`` stage checks fresh), so the deck under test is
the generated cell, not a copy of it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import product
from pathlib import Path

from design.gen_netlists import evaluate as _gn_evaluate, parse as _gn_parse

from ..characterize.request import MODEL_LIB, OSDI_PRELOAD, CellSpec

#: The one spec row this item-5 analog evidence set grades: row 9, "Liberty
#: corners", whose target is the TT / 1.20 V / 25 C view these testbenches
#: verify.  A measurement tag, echoed by ``klt sim`` into the envelope, from
#: which ``klt signoff`` derives the citation's row coverage.
SPEC_ROW = "9"

#: Testbench check, NOT a spec bound (the ratified spec has no cell delay or
#: transition bound): every timing measurement must agree with the committed
#: Liberty view's value at the same (slew, load) point to within +/- 2 %.
#: The committed view was measured by ``klt characterize`` under the same
#: conventions these testbenches replicate (same ramp law, same thresholds,
#: same models and corner), and the worst observed disagreement across all
#: four cells' full grids is 0.0578 %, so 2 % is ~35x the observed drift --
#: far too tight to hide a real divergence (a stale view, a wrong arc, a
#: mis-sized instance moves values by whole percent), far too loose to trip
#: on solver noise or a future ngspice point release.
TIMING_TOLERANCE = 0.02

#: Testbench check, NOT a spec bound: a settled static-CMOS output draws no
#: DC current, so it must sit within millivolts of the rail the function
#: demands; +/- 10 mV allows for numerical residual while a wrong-function
#: output (the opposite rail, 1.2 V away, or mid-rail) fails by 100x.
RAIL_TOLERANCE_V = 0.01

#: Timing-testbench transient window, mirroring ``klt characterize``'s
#: ``settle`` default of ``max(2 ns, 3 x longest ramp)``: the longest ramp on
#: the committed grid is 0.4 ns / 0.6 = 0.667 ns, so settle = 2 ns and the
#: window settle -> rise -> settle -> fall -> settle is 2+0.667+2+0.667+2
#: = 7.33 ns; 8 ns covers it with the tail measurement point included.
SETTLE_S = 2.0e-9
TRAN_STOP_S = 8.0e-9

#: ngspice ``tmax`` pinned equal to the suggested step, mirroring
#: ``klt characterize``'s ``tran_step_ns = min(1 ps, shortest ramp / 10)``:
#: the shortest ramp on the committed grid is 0.02 ns / 0.6 = 33 ps, so 1 ps
#: wins.
TRAN_STEP_S = 1.0e-12

#: Function-testbench sequencing: inputs step through every input combination
#: (fixed enumeration order), each state held STATE_S with a short EDGE_S
#: transition, output sampled SAMPLE_AFTER_EDGE_S into the state -- far past
#: the sub-nanosecond RC of an unloaded static-CMOS output.
STATE_S = 3.0e-9
EDGE_S = 20.0e-12
SAMPLE_AFTER_EDGE_S = 2.0e-9


class RequestError(ValueError):
    """The request inputs are malformed (raised before klt is ever run)."""


# ---------------------------------------------------------------- liberty

_TABLES = ("cell_rise", "cell_fall", "rise_transition", "fall_transition")


@dataclass(frozen=True)
class LibertyView:
    """The committed Liberty view, parsed: the single source of axes,
    thresholds and expected table values.

    ``tables`` maps ``cell -> related_pin -> table name -> row-major values``
    (``values[i][j]`` at input transition ``slews[i]`` and output load
    ``loads[j]``, in the view's own time unit).
    """

    library: str
    voltage: float
    delay_threshold: float  # fraction of supply, input and output (symmetric)
    slew_lo: float  # fraction of supply
    slew_hi: float
    slews: tuple[float, ...]  # input transitions, view time unit (ns)
    loads: tuple[float, ...]  # output loads, pF
    time_unit_scale: float  # view time unit -> seconds (1e-9 for "1ns")
    timing_senses: dict = field(default_factory=dict)  # (cell, pin) -> sense
    tables: dict = field(default_factory=dict)

    def expected(self, cell: str, related_pin: str, table: str, i: int, j: int) -> float:
        try:
            return self.tables[cell][related_pin][table][i][j]
        except KeyError as exc:
            raise RequestError(
                f"committed view has no {table} for {cell} arc {related_pin}"
            ) from exc


def parse_liberty(text: str) -> LibertyView:
    """Parse the ``klt characterize``-written Liberty view this repo commits.

    Deliberately scoped to that writer's stable format (the view is ``klt``'s
    own output, re-parsed by ``native/statime`` on every characterize run),
    not to Liberty in general.
    """
    voltage = float(re.search(r"nom_voltage\s*:\s*([0-9.eE+-]+)\s*;", text).group(1))
    time_unit = re.search(r'time_unit\s*:\s*"([^"]+)"', text).group(1)
    scale = {"1ns": 1e-9, "1ps": 1e-12, "1us": 1e-6, "1s": 1.0}.get(time_unit)
    if scale is None:
        raise RequestError(f"unsupported Liberty time_unit {time_unit!r}")

    def pct(name: str) -> float:
        return float(re.search(rf"{name}\s*:\s*([0-9.eE+-]+)\s*;", text).group(1)) / 100.0

    d_rise, d_fall = pct("input_threshold_pct_rise"), pct("input_threshold_pct_fall")
    o_rise, o_fall = pct("output_threshold_pct_rise"), pct("output_threshold_pct_fall")
    if not (d_rise == d_fall == o_rise == o_fall):
        raise RequestError("view has asymmetric delay thresholds; builder assumes one value")
    lo, hi = pct("slew_lower_threshold_pct_rise"), pct("slew_upper_threshold_pct_rise")
    if (lo, hi) != (pct("slew_lower_threshold_pct_fall"), pct("slew_upper_threshold_pct_fall")):
        raise RequestError("view has asymmetric slew thresholds; builder assumes one pair")

    tpl = re.search(r"lu_table_template[^{]*\{(.*?)\n  \}", text, re.S).group(1)
    slews = tuple(float(v) for v in re.search(r'index_1 \("([^"]*)"\)', tpl).group(1).split(","))
    loads = tuple(float(v) for v in re.search(r'index_2 \("([^"]*)"\)', tpl).group(1).split(","))

    library = re.search(r"library \(([^)]+)\)", text).group(1)
    senses: dict = {}
    tables: dict = {}
    cell = pin = None
    table_name = None
    rows = None
    for line in text.splitlines():
        s = line.strip()
        m = re.match(r"cell \(([^)]+)\) \{", s)
        if m:
            cell, pin, table_name = m.group(1), None, None
            tables.setdefault(cell, {})
            continue
        m = re.match(r'related_pin\s*:\s*"([^"]+)"', s)
        if m:
            pin = m.group(1)
            tables[cell].setdefault(pin, {})
            continue
        m = re.match(r"timing_sense\s*:\s*(\w+)", s)
        if m and cell and pin:
            senses[(cell, pin)] = m.group(1)
            continue
        m = re.match(rf"({'|'.join(_TABLES)}) \(", s)
        if m and cell and pin:
            table_name, rows = m.group(1), []
            tables[cell][pin][table_name] = rows
            continue
        if table_name is not None and s.startswith('"'):
            m = re.match(r'"([^"]*)"', s)
            rows.append([float(v) for v in m.group(1).split(",")])
        elif table_name is not None and s.startswith(");"):
            table_name = None
    return LibertyView(
        library=library, voltage=voltage, delay_threshold=d_rise,
        slew_lo=lo, slew_hi=hi, slews=slews, loads=loads, time_unit_scale=scale,
        timing_senses=senses, tables=tables,
    )


# ------------------------------------------------- function parse/eval

def parse_function(expr: str):
    """Parse a config/Liberty boolean function over the gen_netlists grammar.

    Delegates to ``design.gen_netlists.parse`` (the one grammar: ``!`` ``*``
    ``^`` ``+``; operators may not be mixed at one nesting level without
    parentheses), so a function string means the same tree here as there.
    Parse failures are re-raised as :class:`RequestError`.
    """
    try:
        return _gn_parse(expr)
    except ValueError as exc:
        raise RequestError(str(exc)) from exc


def evaluate_function(node, env: dict) -> int:
    """Evaluate a parsed function tree over ``{pin: 0|1}``."""
    try:
        return _gn_evaluate(node, {k: int(bool(v)) for k, v in env.items()})
    except KeyError as exc:
        raise RequestError(
            f"function references unknown pin {exc.args[0]!r}") from exc


# ----------------------------------------------------------------- arcs

@dataclass(frozen=True)
class Arc:
    """One timing arc: ``related_pin`` toggles ``output_pin`` under
    ``side_inputs`` (the constant values every other input is held at)."""

    related_pin: str
    output_pin: str
    sense: str  # "negative_unate" | "positive_unate"
    side_inputs: dict[str, int]  # pin -> 0 | 1


def arcs_for(cell: CellSpec) -> list[Arc]:
    """Derive every timing arc from the cell's own function strings.

    Same rule ``klt characterize`` documents ("arcs are derived, not
    declared"): for each input pin, the first input assignment -- in fixed
    enumeration order, :func:`itertools.product` over the config's pin order
    -- whose related-pin flip flips the output is that arc's sensitizing
    vector; no such assignment means no arc for the pin.
    """
    arcs = []
    for out_pin, func in cell.outputs.items():
        ast = parse_function(func)
        for pin in cell.inputs:
            for values in product((0, 1), repeat=len(cell.inputs)):
                env = dict(zip(cell.inputs, values))
                base = evaluate_function(ast, env)
                env[pin] = 1 - env[pin]
                flipped = evaluate_function(ast, env)
                if flipped != base:
                    sense = "negative_unate" if flipped < base else "positive_unate"
                    sides = {p: v for p, v in zip(cell.inputs, values) if p != pin}
                    arcs.append(Arc(pin, out_pin, sense, sides))
                    break
    return arcs


# ------------------------------------------------------------ formatting

def _tag(value: float) -> str:
    """``0.02 -> "0p02"``, ``0.1 -> "0p1"``: a flat measurement-name token."""
    return f"{value:.6f}".rstrip("0").replace(".", "p")


def _num(value: float) -> str:
    return repr(float(value))


# ------------------------------------------------------ netlist builders

def _pin_connections(cell: CellSpec, arc: Arc, in_node: str, y_node: str) -> list[str]:
    conns = []
    for pin in cell.inputs:
        if pin == arc.related_pin:
            conns.append(in_node)
        else:
            conns.append(cell.vdd if arc.side_inputs[pin] else "0")
    conns.append(y_node)
    conns.extend([cell.vdd, cell.gnd])
    return conns


def build_timing_netlist(cell: CellSpec, arcs: list[Arc], view: LibertyView,
                         cell_netlist_ref: str) -> str:
    """The timing testbench circuit body: one DUT per (arc, slew, load).

    ``cell_netlist_ref`` is the ``.include`` path of the generated cell
    netlist as seen from the directory this file is written to (the runner
    computes it; builders stay path-free).
    """
    supply = view.voltage
    ramp_frac = view.slew_hi - view.slew_lo
    lines = [
        f"* {cell.name} timing testbench (sim.item5, spec row {SPEC_ROW}): delay and",
        "* transition at every (input transition, output load) point of the committed",
        f"* view {view.library}, one DUT instance per (arc, slew, load). Replicates the",
        "* klt characterize stimulus: a linear rail-to-rail ramp whose threshold-to-",
        f"* threshold duration equals the tabulated input transition (ramp = slew/{ramp_frac:.6g}).",
        f".include {cell_netlist_ref}",
        f"Vdd {cell.vdd} 0 DC {_num(supply)}",
        f"Vss {cell.gnd} 0 DC 0",
    ]
    for arc in arcs:
        for slew_ns in view.slews:
            slew_s = slew_ns * view.time_unit_scale
            ramp = slew_s / ramp_frac
            t0 = SETTLE_S
            t1 = t0 + ramp
            t2 = t1 + SETTLE_S
            t3 = t2 + ramp
            for load_pf in view.loads:
                tag = f"{arc.related_pin}_s{_tag(slew_ns)}_l{_tag(load_pf)}"
                in_node, y_node = f"in_{tag}", f"y_{tag}"
                lines.append(
                    f"V{tag} {in_node} 0 PWL(0 0 {_num(t0)} 0 {_num(t1)} {_num(supply)} "
                    f"{_num(t2)} {_num(supply)} {_num(t3)} 0 {_num(TRAN_STOP_S)} 0)"
                )
                lines.append(
                    f"X{tag} " + " ".join(_pin_connections(cell, arc, in_node, y_node))
                    + f" {cell.name}"
                )
                lines.append(f"C{tag}_cl {y_node} 0 {_num(load_pf * 1e-12)}")
    return "\n".join(lines) + "\n"


def build_function_netlist(cell: CellSpec, cell_netlist_ref: str, supply_v: float) -> str:
    """The function testbench circuit body: one unloaded DUT stepped through
    every input combination."""
    states = list(product((0, 1), repeat=len(cell.inputs)))
    lines = [
        f"* {cell.name} function testbench (sim.item5, spec row {SPEC_ROW}): logical",
        f"* function at the rails -- inputs step through all {len(states)} input",
        f"* combinations, output sampled {SAMPLE_AFTER_EDGE_S * 1e9:.0f} ns into each state.",
        f".include {cell_netlist_ref}",
        f"Vdd {cell.vdd} 0 DC {_num(supply_v)}",
        f"Vss {cell.gnd} 0 DC 0",
    ]
    for pin_idx, pin in enumerate(cell.inputs):
        pts = []
        prev = None
        for k, state in enumerate(states):
            t = k * STATE_S
            v = state[pin_idx] * supply_v
            if k > 0:
                pts.append((t, prev))  # hold the previous state up to its boundary
            pts.append((t + EDGE_S, v))  # then step to this state's value
            prev = v
        pts.append((len(states) * STATE_S, prev))  # clean flat tail
        pts_txt = " ".join(f"{_num(t)} {_num(v)}" for t, v in pts)
        lines.append(f"Vin_{pin} in_{pin} 0 PWL({pts_txt})")
    outs = [f"y_dut_{pin}" for pin in cell.outputs]
    conns = [f"in_{pin}" for pin in cell.inputs] + outs + [cell.vdd, cell.gnd]
    lines.append("XDUT " + " ".join(conns) + f" {cell.name}")
    return "\n".join(lines) + "\n"


# ----------------------------------------------------- request builders

def _corner_block(process: str, supply_v: float, temperature_c: float) -> dict:
    return {
        "process": [process],
        "supply_v": {"Vdd": [supply_v]},
        "temperature_c": [temperature_c],
    }


def _limits(expected: float, tol: float) -> dict:
    lo, hi = sorted((expected * (1.0 - tol), expected * (1.0 + tol)))
    return {"min": lo, "max": hi}


def _delay_input_edge(sense: str, table: str) -> str:
    """Which input edge drives this delay table's output edge.

    A ``negative_unate`` arc's output rise is caused by the input *falling*
    edge (and vice versa); a ``positive_unate`` arc's edges move together.
    """
    if sense == "negative_unate":
        return "FALL" if table == "cell_rise" else "RISE"
    if sense == "positive_unate":
        return "RISE" if table == "cell_rise" else "FALL"
    raise RequestError(f"unknown timing sense {sense!r}")


def _assemble_request(netlist: str, stop_s: float, measurements: list[dict],
                      supply_v: float, pdk_dir: str | Path) -> dict:
    """Wrap one testbench's measurements in the ``klt sim`` request document.

    The corner is the row 9 TT pairing, read here and nowhere else.
    ``supply_v`` is the rail the testbench's stimulus actually swings to (the
    config rail for the function bench, the view's ``nom_voltage`` for the
    timing bench) and must be that pairing's supply, or the deck would run at
    one rail while the request -- and so the envelope's corner id -- cites
    another.
    """
    from ..harness.corners import CHAR_CORNER_PVT

    process, corner_supply_v, temperature_c = CHAR_CORNER_PVT["tt"]
    if supply_v != corner_supply_v:
        raise RequestError(
            f"{netlist}: stimulus rail {supply_v} V disagrees with"
            f" the TT corner supply {corner_supply_v} V"
        )
    pdk = Path(pdk_dir)
    return {
        "netlist": netlist,
        "corners": _corner_block(process, corner_supply_v, temperature_c),
        "models": {"lib": str(pdk / MODEL_LIB)},
        "options": {"osdi_preload": [str(pdk / p) for p in OSDI_PRELOAD]},
        "analysis": {"kind": "tran",
                     "args": f"{TRAN_STEP_S:.6g} {stop_s:.6g} 0 {TRAN_STEP_S:.6g}"},
        "measurements": measurements,
    }


def build_timing_request(cell: CellSpec, arcs: list[Arc], view: LibertyView,
                         pdk_dir: str | Path, spec_row: str = SPEC_ROW,
                         tol: float = TIMING_TOLERANCE) -> dict:
    """The timing ``klt sim`` request for one cell, at the view's corner.

    One measurement per (arc, slew, load, quantity); every measurement's
    limit is agreement with the view's own value at that same point, every
    measurement is tagged with the spec row it grades.
    """
    request, _ = build_timing_request_with_targets(cell, arcs, view, pdk_dir, spec_row, tol)
    return request


def build_timing_request_with_targets(
    cell: CellSpec, arcs: list[Arc], view: LibertyView, pdk_dir: str | Path,
    spec_row: str = SPEC_ROW, tol: float = TIMING_TOLERANCE,
) -> tuple[dict, dict[str, float]]:
    """Build the timing request and its nominal measurement values in seconds."""
    if not arcs:
        raise RequestError(f"cell {cell.name!r} has no timing arcs")
    missing = [a.related_pin for a in arcs
               if (cell.name, a.related_pin) not in view.timing_senses]
    if missing:
        raise RequestError(f"committed view has no arcs {missing} for {cell.name}")
    wrong = [a.related_pin for a in arcs
             if view.timing_senses[(cell.name, a.related_pin)] != a.sense]
    if wrong:
        raise RequestError(
            f"derived sense disagrees with the committed view for {cell.name} arcs {wrong}"
        )
    supply = view.voltage
    v_delay = supply * view.delay_threshold
    v_lo, v_hi = supply * view.slew_lo, supply * view.slew_hi
    measurements = []
    targets = {}

    def add_measurement(name: str, clause: str, target: float) -> None:
        targets[name] = target
        measurements.append({
            "name": name,
            "spice": f".meas tran {name} {clause}",
            "limits": _limits(target, tol),
            "unit": "s",
            "spec_row": spec_row,
        })

    edges = (("rise", v_lo, v_hi), ("fall", v_hi, v_lo))
    for arc in arcs:
        for i, slew_ns in enumerate(view.slews):
            slew_s = slew_ns * view.time_unit_scale
            for j, load_pf in enumerate(view.loads):
                tag = f"{arc.related_pin}_s{_tag(slew_ns)}_l{_tag(load_pf)}"
                vin, y = f"in_{tag}", f"y_{tag}"
                for table, out_edge in (("cell_rise", "RISE"), ("cell_fall", "FALL")):
                    in_edge = _delay_input_edge(arc.sense, table)
                    add_measurement(
                        f"{tag}_{table}",
                        f"TRIG v({vin}) VAL={v_delay:.6g} {in_edge}=1 "
                        f"TARG v({y}) VAL={v_delay:.6g} {out_edge}=1",
                        view.expected(cell.name, arc.related_pin, table, i, j) * view.time_unit_scale,
                    )
                for edge, trig_v, targ_v in edges:
                    table = f"{edge}_transition"
                    add_measurement(
                        f"{tag}_{table}",
                        f"TRIG v({y}) VAL={trig_v:.6g} {edge.upper()}=1 "
                        f"TARG v({y}) VAL={targ_v:.6g} {edge.upper()}=1",
                        view.expected(cell.name, arc.related_pin, table, i, j) * view.time_unit_scale,
                    )
                # stimulus self-check: the applied ramp's threshold-to-threshold
                # duration is the tabulated input transition, both edges
                # (a falling edge crosses the high threshold first)
                for edge, trig_v, targ_v in edges:
                    add_measurement(
                        f"{tag}_in_slew_{edge}",
                        f"TRIG v({vin}) VAL={trig_v:.6g} {edge.upper()}=1 "
                        f"TARG v({vin}) VAL={targ_v:.6g} {edge.upper()}=1",
                        slew_s,
                    )
    return _assemble_request(f"{cell.name}.timing.spice", TRAN_STOP_S, measurements,
                             supply, pdk_dir), targets


def build_function_request(cell: CellSpec, pdk_dir: str | Path,
                           supply_v: float, spec_row: str = SPEC_ROW,
                           rail_tol_v: float = RAIL_TOLERANCE_V) -> dict:
    """The function ``klt sim`` request for one cell, at the view's corner."""
    request, _ = build_function_request_with_targets(cell, pdk_dir, supply_v, spec_row, rail_tol_v)
    return request


def build_function_request_with_targets(
    cell: CellSpec, pdk_dir: str | Path, supply_v: float,
    spec_row: str = SPEC_ROW, rail_tol_v: float = RAIL_TOLERANCE_V,
) -> tuple[dict, dict[str, float]]:
    """Build the function request and its expected output rails in volts."""
    asts = {pin: parse_function(func) for pin, func in cell.outputs.items()}
    states = list(product((0, 1), repeat=len(cell.inputs)))
    measurements = []
    targets = {}
    for k, state in enumerate(states):
        env = dict(zip(cell.inputs, state))
        at = k * STATE_S + SAMPLE_AFTER_EDGE_S
        state_tag = "_".join(f"{p}{v}" for p, v in env.items())
        for out_pin, ast in asts.items():
            name = f"y_{state_tag}_{out_pin}"
            if evaluate_function(ast, env):
                targets[name] = supply_v
                limits = {"min": supply_v - rail_tol_v, "max": supply_v + rail_tol_v}
            else:
                targets[name] = 0.0
                limits = {"max": rail_tol_v}
            measurements.append({
                "name": name,
                "spice": f".meas tran {name} FIND v(y_dut_{out_pin}) AT={at:.6g}",
                "limits": limits,
                "unit": "V",
                "spec_row": spec_row,
            })
    return _assemble_request(f"{cell.name}.function.spice",
                             len(states) * STATE_S + 1e-9, measurements,
                             supply_v, pdk_dir), targets
