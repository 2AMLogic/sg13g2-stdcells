"""Characterization corner set + evidence extension (issue #7).

Run from the repo root:  python -m pytest sim/tests
"""

import pytest

from sim.harness import corners, evidence

GOOD = dict(
    record_kind="characterization",
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


def test_corner_set_resolves_to_tt_ff_ss():
    names = [c.name for c in corners.resolve_corners([corners.CHAR_CORNER_SET])]
    assert names == ["tt", "ff", "ss"]


def test_characterization_points_are_paired_not_factorial():
    # Edge case from the issue: FF is simulated ONLY at 1.32 V / -40 C etc.
    # The 3x3x3 full factorial (27 points) is deliberately not what this is.
    pts = corners.characterization_points()
    assert [(p.corner.name, p.vdd, p.temp_c) for p in pts] == [
        ("tt", 1.20, 25.0),
        ("ff", 1.32, -40.0),
        ("ss", 1.08, 125.0),
    ]


def test_builtin_corners_untouched():
    assert set(corners.CORNER_SETS) >= {"tt", "mos", corners.CHAR_CORNER_SET}
    assert corners.CORNER_SETS["mos"] == ("tt", "ff", "ss", "fs", "sf")


def test_valid_record_passes_and_renders():
    ext = evidence.CharacterizationExtensions(**GOOD)
    ext.validate()
    assert ext.as_dict()["cell"] == "sg13g2_nand2_1"
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


def test_char_fields_rejected_on_other_record_kind():
    with pytest.raises(evidence.EvidenceFormatError):
        evidence.CharacterizationExtensions(record_kind="corner-matrix", cell="x").validate()


def test_from_manifest_roundtrip_and_unknown_key():
    ext = evidence.from_manifest(GOOD)
    ext.validate()
    with pytest.raises(evidence.EvidenceFormatError):
        evidence.from_manifest({"bogus": 1})
