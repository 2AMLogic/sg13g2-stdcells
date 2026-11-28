"""Characterization corner set + evidence extension (issue #7).

Run from the repo root:  python -m pytest sim/tests
"""

import pytest

from pathlib import Path

from sim.characterize import runner
from sim.characterize.request import CellSpec
from sim.harness import corners, evidence

GOOD = dict(
    data_provenance="simulated",
    cell="sg13g2_nand2_1",
    arc_related_pin="A",
    arc_when="B",
    arc_sense="negative_unate",
    input_slew_ns=0.1,
    output_load_pf=0.01,
    delay_ns=0.05,
    transition_ns=0.04,
    energy_pj=0.002,
    corner="tt",
    netlist_provenance="extracted from layout @ abc123",
)


def test_characterization_corners_are_paired_not_factorial():
    # FF is simulated ONLY at 1.32 V / -40 C etc.; the 3x3x3 full factorial
    # (27 points) is deliberately not what this is. Each row carries its own
    # klt process section -- the strings emitted in the request's corner block.
    assert corners.CHAR_CORNER_PVT == {
        "tt": ("mos_tt", 1.20, 25.0),
        "ff": ("mos_ff", 1.32, -40.0),
        "ss": ("mos_ss", 1.08, 125.0),
    }


def test_valid_record_passes_and_renders():
    ext = evidence.CharacterizationExtensions(**GOOD)
    ext.validate()
    assert ext.cell == "sg13g2_nand2_1"
    assert any("Netlist provenance" in line for line in ext.render_lines())


@pytest.mark.parametrize("missing", [
    "cell", "arc_related_pin", "arc_sense", "corner", "netlist_provenance",
    "input_slew_ns", "output_load_pf", "delay_ns", "transition_ns", "energy_pj",
    "data_provenance",
])
def test_missing_required_field_rejected(missing):
    kw = dict(GOOD)
    kw.pop(missing)
    with pytest.raises(evidence.EvidenceFormatError):
        evidence.CharacterizationExtensions(**kw).validate()


def test_bad_sense_and_corner_rejected():
    for patch in ({"arc_sense": "sideways"}, {"corner": "fs"}, {"delay_ns": -1.0}):
        with pytest.raises(evidence.EvidenceFormatError):
            evidence.CharacterizationExtensions(**{**GOOD, **patch}).validate()


# --- record provenance carries the simulator (issue #125) -----------------

CELL = CellSpec("sg13g2_inv_1", inputs=("A",), outputs={"Y": "!A"}, netlist="/nl/sg13g2_inv_1.spice")
RECORD_ID = "20260101-000000-abc1234"


def _response(simulation):
    """Minimal klt characterize response; batch shape (top-level fields null)."""
    arc = {
        "related_pin": "A", "output_pin": "Y", "timing_sense": "negative_unate",
        "side_inputs": {},
        "cell_rise": {"values": [[0.05]]}, "cell_fall": {"values": [[0.06]]},
        "rise_transition": {"values": [[0.04]]}, "fall_transition": {"values": [[0.05]]},
        "rise_power": {"values": [[0.001]]}, "fall_power": {"values": [[0.001]]},
    }
    entry = {"cell": {"name": CELL.name}, "arcs": [arc], "leakage": {"values": [[0.1]]}}
    if simulation is not None:
        entry["simulation"] = simulation
    return {
        "provenance": {"klt_version": "klt 0.9.3.dev3"},
        "corner": {"name": "tt"},
        "grid": {"input_transition_ns": [0.1], "output_load_pf": [0.01]},
        "units": {},
        "cells": [entry],
        "cell": None, "arcs": None, "leakage": None, "simulation": None,
    }


def _record_data(simulation):
    return runner.build_record_data(_response(simulation), CELL, backend="local")


def _library_data(simulation):
    d = _record_data(simulation)
    return {**d, "cells": [d], "record_id": RECORD_ID}


def _notes(record_data):
    md = runner.render(RECORD_ID, {"commit": "abc", "dirty": False}, record_data, [])
    return next(line for line in md.splitlines() if line.startswith("**Notes**"))


def test_build_record_data_captures_simulator_from_per_cell_block():
    # The response's top-level simulation is null (batch shape); the per-cell
    # entry is the only source -- reading the top-level key would drop it.
    assert _record_data({"engine": "ngspice", "engine_version": "47"}).get("simulator") \
        == {"engine": "ngspice", "version": "47"}


def test_notes_line_names_simulator():
    assert "simulator ngspice-47" in _notes(_library_data({"engine": "ngspice", "engine_version": "47"}))


def test_sidecar_names_simulator_beside_klt(tmp_path):
    config = tmp_path / "cfg.json"
    config.write_text("{}\n")
    prov = runner.provenance_for(config, {"name": "tt"},
                                 _library_data({"engine": "ngspice", "engine_version": "47"}))
    assert prov["simulator"] == "ngspice-47"
    assert "klt_version" in prov
    assert prov["library"] == "sg13g2_stdcells_tt_1p20v_25c"
    ff = runner.provenance_for(config, {"name": "ff"},
                               _library_data({"engine": "ngspice", "engine_version": "47"}))
    assert ff["library"] == "sg13g2_stdcells_ff_1p32v_m40c"


@pytest.mark.parametrize("simulation", [
    None,
    {},
    {"engine": "ngspice", "engine_version": None},
    {"engine": None, "engine_version": "47"},
])
def test_missing_simulator_renders_explicit_unknown(simulation):
    data = _record_data(simulation)
    captured = data["simulator"]
    assert captured == {"engine": (simulation or {}).get("engine"),
                        "version": (simulation or {}).get("engine_version")}
    assert captured["engine"] is None or captured["version"] is None
    assert "simulator unknown" in _notes(data)


# --- CLI selects the corner (issue #140) -----------------------------------

def _main_capture(monkeypatch, argv):
    seen = {}

    def fake_lib(*a, **kw):
        seen["lib"] = a, kw
        return "rec"

    monkeypatch.setattr(runner, "characterize_library", fake_lib)
    return runner.main(argv), seen


def test_cli_corner_reaches_characterize_library(monkeypatch):
    from sim.harness.corners import CHAR_CORNER_PVT

    assert list(CHAR_CORNER_PVT) == ["tt", "ff", "ss"]  # choices draw from here, not retyped
    rc, seen = _main_capture(monkeypatch, ["--corner", "ss", "--lib", "ff.lib"])
    assert rc == 0
    assert seen["lib"][0][1] == "ss"
    assert seen["lib"][1]["lib_path"] == Path("ff.lib").resolve()


def test_cli_default_corner_is_tt(monkeypatch):
    rc, seen = _main_capture(monkeypatch, [])
    assert rc == 0
    assert seen["lib"][0][1] == "tt"


def test_cli_unknown_corner_and_backend_exit_nonzero():
    for argv in (["--corner", "fs"], ["--backend", "ssh"]):
        with pytest.raises(SystemExit) as exc:
            runner.main(argv)
        assert exc.value.code != 0


def test_cli_library_flag_is_removed():
    with pytest.raises(SystemExit) as exc:
        runner.main(["--library"])
    assert exc.value.code != 0


def test_cli_default_corner_uses_default_lib_and_config(monkeypatch):
    # The tt-named default view path is the derived name at the default corner.
    rc, seen = _main_capture(monkeypatch, [])
    assert rc == 0
    assert seen["lib"][1]["lib_path"] == runner.DEFAULT_LIB.resolve()
    assert seen["lib"][0][0] == runner.DEFAULT_CONFIG.resolve()


def test_cli_nondefault_corner_defaults_to_corner_named_lib(monkeypatch):
    # The default view path is corner-named (issue #143), so --corner ff needs
    # no explicit --lib to avoid overwriting the committed TT view.
    rc, seen = _main_capture(monkeypatch, ["--corner", "ff"])
    assert rc == 0
    expected = runner.REPO_ROOT / "views" / "sg13g2_stdcells_ff_1p32v_m40c.lib"
    assert seen["lib"][1]["lib_path"] == expected.resolve()
