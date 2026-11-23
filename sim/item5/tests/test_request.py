"""Pure builders for the item-5 testbenches (spec row 9).

Run from the repo root:  python3 -m pytest sim/item5/tests

The committed Liberty view and cell config are read as fixtures -- the whole
point of these builders is that the committed request documents re-derive
from committed sources, so the tests pin that derivation against the real
tree, not a mock.
"""

import json
from pathlib import Path

import pytest

from sim.characterize.request import CellSpec, cells_from_config
from sim.harness.corners import CHAR_CORNER_PVT
from sim.item5.request import (RAIL_TOLERANCE_V, SPEC_ROW, TIMING_TOLERANCE,
                               arcs_for, build_function_netlist,
                               build_function_request, build_timing_netlist,
                               build_timing_request, evaluate_function,
                               parse_function, parse_liberty)

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG = REPO_ROOT / "layout" / "example_config.json"
VIEW = REPO_ROOT / "views" / "sg13g2_stdcells_tt_1p20v_25c.lib"
NETLISTS = REPO_ROOT / "layout" / "lvs" / "netlists"
VIEW_TEXT = VIEW.read_text()

INV1 = CellSpec("sg13g2_inv_1", inputs=("A",), outputs={"Y": "!A"},
                netlist=str(NETLISTS / "sg13g2_inv_1.spice"))
NAND2 = CellSpec("sg13g2_nand2_1", inputs=("A", "B"), outputs={"Y": "!(A*B)"},
                 netlist=str(NETLISTS / "sg13g2_nand2_1.spice"))


@pytest.fixture(scope="module")
def view():
    return parse_liberty(VIEW_TEXT)


@pytest.fixture(scope="module")
def cells():
    return cells_from_config(CONFIG, NETLISTS)


# ------------------------------------------------------------- functions

@pytest.mark.parametrize("func,env,want", [
    ("!A", {"A": 1}, 0),
    ("!A", {"A": 0}, 1),
    ("!(A*B)", {"A": 1, "B": 1}, 0),
    ("!(A*B)", {"A": 1, "B": 0}, 1),
    ("(A^B)*!(A*B)", {"A": 1, "B": 1}, 0),
    ("(A+B)*!C", {"A": 0, "B": 0, "C": 1}, 0),
])
def test_evaluate_committed_grammar(func, env, want):
    assert evaluate_function(parse_function(func), env) == want


def test_mixed_operators_rejected():
    with pytest.raises(ValueError, match="mixed operators"):
        parse_function("A*B+C")


def test_unknown_pin_rejected():
    with pytest.raises(ValueError, match="unknown pin"):
        evaluate_function(parse_function("!A"), {"B": 1})


# ------------------------------------------------------------------ arcs

def test_inv_arc():
    arcs = arcs_for(INV1)
    assert [(a.related_pin, a.output_pin, a.sense, a.side_inputs) for a in arcs] == \
        [("A", "Y", "negative_unate", {})]


def test_nand2_arcs():
    arcs = arcs_for(NAND2)
    assert [(a.related_pin, a.sense, a.side_inputs) for a in arcs] == \
        [("A", "negative_unate", {"B": 1}), ("B", "negative_unate", {"A": 1})]


def test_config_cells_have_arcs_in_the_view(view, cells):
    # the committed config's four cells, and every derived arc exists in the
    # committed view with the same sense -- the precondition the runner checks
    for cell in cells:
        for arc in arcs_for(cell):
            assert view.timing_senses[(cell.name, arc.related_pin)] == arc.sense


# --------------------------------------------------------------- liberty

def test_view_axes_and_thresholds(view):
    assert view.slews == (0.02, 0.05, 0.1, 0.2, 0.4)
    assert view.loads == (0.001, 0.003, 0.01, 0.03, 0.1)
    assert view.voltage == 1.2
    assert view.delay_threshold == 0.5
    assert (view.slew_lo, view.slew_hi) == (0.2, 0.8)
    assert view.time_unit_scale == 1e-9


def test_view_tables_shape(view):
    for cell in ("sg13g2_inv_1", "sg13g2_inv_2", "sg13g2_inv_4", "sg13g2_nand2_1"):
        pins = view.tables[cell]
        assert set(pins) == {"A"} if cell.startswith("sg13g2_inv") else set(pins) == {"A", "B"}
        for tables in pins.values():
            for table, rows in tables.items():
                assert len(rows) == 5 and all(len(r) == 5 for r in rows), (cell, table)


def test_view_known_value(view):
    # the grid centre the probe run measured live: inv_1 cell_rise @ 0.1 ns /
    # 0.01 pF (index [2][2]) is 0.0912005 ns in the committed view
    assert view.expected("sg13g2_inv_1", "A", "cell_rise", 2, 2) == pytest.approx(0.0912005)


# -------------------------------------------------------------- netlists

def test_timing_netlist_instances(view):
    text = build_timing_netlist(NAND2, arcs_for(NAND2), view, "ref.spice")
    # one DUT + one source + one load per (arc, slew, load), plus the rails
    assert text.count("\nX") == 2 * 25
    assert text.count(" PWL(") == 2 * 25
    assert text.count("_cl y") == 2 * 25
    assert ".include ref.spice" in text
    assert "Vss VSS 0 DC 0" in text
    # side inputs tied to the rail the sensitizing vector demands: the A arc
    # holds B high (ramped A first), the B arc holds A high (ramped B second)
    assert "XA_s0p1_l0p01 in_A_s0p1_l0p01 VDD y_A_s0p1_l0p01 VDD VSS sg13g2_nand2_1" in text
    assert "XB_s0p1_l0p01 VDD in_B_s0p1_l0p01 y_B_s0p1_l0p01 VDD VSS sg13g2_nand2_1" in text
    assert text.startswith("*")


def test_function_netlist_states():
    text = build_function_netlist(NAND2, "ref.spice", 1.2)
    # one DUT, no load, both inputs stepped, four states per input PWL
    assert text.count("\nX") == 1
    assert "Vin_A in_A 0 PWL(" in text and "Vin_B in_B 0 PWL(" in text
    assert "_cl " not in text


def test_function_netlist_pwl_holds_states():
    # regression: a state's value must HOLD until the next boundary (a hold
    # point at the boundary), not interpolate into a 3 ns ramp -- the input
    # is 0 V and 1.2 V at the sample instants, never mid-ramp
    text = build_function_netlist(NAND2, "ref.spice", 1.2)
    pwl_a = text.split("Vin_A in_A 0 PWL(")[1].split(")")[0]
    times = [float(tok) for i, tok in enumerate(pwl_a.split()) if i % 2 == 0]
    assert times == sorted(times) and len(set(times)) == len(times)
    # A (first input, slowest-varying) = 0,0,1,1 across the four states
    values = [float(tok) for i, tok in enumerate(pwl_a.split()) if i % 2 == 1]
    assert values[0] == 0.0 and values[1] == 0.0
    assert 1.2 in values and values.count(1.2) >= 2
    # the value sampled at each mid-state instant equals a rail exactly
    at = [1.5e-9, 4.5e-9, 7.5e-9, 10.5e-9]
    for t in at:
        v = _pwl_value(times, values, t)
        assert v in (0.0, 1.2), (t, v)


def _pwl_value(times, values, t):
    for (t0, v0), (t1, v1) in zip(zip(times, values), zip(times[1:], values[1:])):
        if t0 <= t <= t1 and v0 == v1:
            return v0
    raise AssertionError(f"t={t} falls on a transition")


# -------------------------------------------------------------- requests

def test_timing_request_measurements_and_limits(view):
    req = build_timing_request(INV1, arcs_for(INV1), view, "/pdk")
    names = [m["name"] for m in req["measurements"]]
    # per (arc, slew, load): 4 view-quantity checks + 2 stimulus self-checks
    assert len(names) == len(set(names)) == 25 * 6
    assert "A_s0p02_l0p001_cell_rise" in names
    assert "A_s0p4_l0p1_in_slew_fall" in names
    centre = next(m for m in req["measurements"] if m["name"] == "A_s0p1_l0p01_cell_rise")
    want = 0.0912005e-9
    assert centre["limits"] == {"min": pytest.approx(want * (1 - TIMING_TOLERANCE)),
                                "max": pytest.approx(want * (1 + TIMING_TOLERANCE))}
    assert centre["unit"] == "s" and centre["spec_row"] == SPEC_ROW
    assert all(m["spec_row"] == SPEC_ROW and "limits" in m for m in req["measurements"])


def test_timing_request_negative_unate_edges(view):
    req = build_timing_request(INV1, arcs_for(INV1), view, "/pdk")
    fall = next(m for m in req["measurements"] if m["name"] == "A_s0p1_l0p01_cell_fall")
    rise = next(m for m in req["measurements"] if m["name"] == "A_s0p1_l0p01_cell_rise")
    # the inverter's output fall is driven by the input RISE edge, and its
    # output rise by the input FALL edge (negative_unate, as the view declares)
    assert "VAL=0.6 RISE=1 TARG v(y_A_s0p1_l0p01) VAL=0.6 FALL=1" in fall["spice"]
    assert "VAL=0.6 FALL=1 TARG v(y_A_s0p1_l0p01) VAL=0.6 RISE=1" in rise["spice"]


def test_stimulus_self_check_edges(view):
    # regression: a falling edge crosses the HIGH slew threshold first, so the
    # fall self-check must TRIG on 0.96 and TARG on 0.24 (a fixed lo->hi order
    # measures a negative duration and fails its own limit)
    req = build_timing_request(INV1, arcs_for(INV1), view, "/pdk")
    r = next(m for m in req["measurements"] if m["name"] == "A_s0p1_l0p01_in_slew_rise")
    f = next(m for m in req["measurements"] if m["name"] == "A_s0p1_l0p01_in_slew_fall")
    assert "TRIG v(in_A_s0p1_l0p01) VAL=0.24 RISE=1 TARG v(in_A_s0p1_l0p01) VAL=0.96" in r["spice"]
    assert "TRIG v(in_A_s0p1_l0p01) VAL=0.96 FALL=1 TARG v(in_A_s0p1_l0p01) VAL=0.24" in f["spice"]
    assert r["limits"] == f["limits"]
    assert r["limits"]["min"] == pytest.approx(0.1e-9 * 0.98)
    assert r["limits"]["max"] == pytest.approx(0.1e-9 * 1.02)


def test_timing_request_corner_is_row9_target(view):
    req = build_timing_request(INV1, arcs_for(INV1), view, "/pdk")
    process, supply_v, temperature_c = CHAR_CORNER_PVT["tt"]
    assert req["corners"] == {"process": [process],
                              "supply_v": {"Vdd": [supply_v]},
                              "temperature_c": [temperature_c]}
    assert req["netlist"] == "sg13g2_inv_1.timing.spice"
    assert req["analysis"]["kind"] == "tran"


def test_timing_request_missing_arc_rejected(view):
    stranger = CellSpec("sg13g2_unknown_9", inputs=("A",), outputs={"Y": "!A"},
                        netlist="x.spice")
    with pytest.raises(ValueError, match="no arcs"):
        build_timing_request(stranger, arcs_for(stranger), view, "/pdk")


def test_function_request_states_and_limits(view):
    supply = json.loads(CONFIG.read_text())["process"]["supply_v"]
    req = build_function_request(NAND2, "/pdk", supply)
    names = [m["name"] for m in req["measurements"]]
    assert names == [f"y_{state}_Y" for state in ("A0_B0", "A0_B1", "A1_B0", "A1_B1")]
    by_name = {m["name"]: m for m in req["measurements"]}
    for state, expected_high in (("A0_B0", True), ("A0_B1", True),
                                 ("A1_B0", True), ("A1_B1", False)):
        m = by_name[f"y_{state}_Y"]
        if expected_high:
            assert m["limits"] == {"min": supply - RAIL_TOLERANCE_V,
                                   "max": supply + RAIL_TOLERANCE_V}
        else:
            assert m["limits"] == {"max": RAIL_TOLERANCE_V}
        assert m["unit"] == "V" and m["spec_row"] == SPEC_ROW
    # samples sit 2 ns into each 3 ns state, after the 20 ps state edges
    # (states enumerate (A,B) = 00, 01, 10, 11 at 0, 3, 6, 9 ns)
    assert "AT=2e-09" in by_name["y_A0_B0_Y"]["spice"]
    assert "AT=5e-09" in by_name["y_A0_B1_Y"]["spice"]
    assert "AT=8e-09" in by_name["y_A1_B0_Y"]["spice"]


def test_lims_always_bracket_the_committed_value(view):
    tables = ("cell_rise", "cell_fall", "rise_transition", "fall_transition")
    for cell in cells_from_config(CONFIG, NETLISTS):
        req = build_timing_request(cell, arcs_for(cell), view, "/pdk")
        for m in req["measurements"]:
            for table in tables:
                if not m["name"].endswith("_" + table):
                    continue
                tag = m["name"][: -len(table) - 1]
                arc, rest = tag.split("_s", 1)
                slew_s, load_s = rest.split("_l", 1)
                slew = float(slew_s.replace("p", "."))
                load = float(load_s.replace("p", "."))
                i, j = view.slews.index(slew), view.loads.index(load)
                want = view.expected(cell.name, arc, table, i, j) * 1e-9
                assert m["limits"]["min"] < want < m["limits"]["max"], (m["name"], want)
