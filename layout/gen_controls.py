#!/usr/bin/env python3
"""Regenerate the recorded negative-control streams (layout/{drc,erc}/controls/*.gds).

Usage: gen_controls.py [--config CONFIG.json] [--out DIR] [--erc-out DIR] [--check]

Default mode (re)writes one `<control>.gds` per table row -- the notch DRC
controls under --out (default: `layout/drc/controls`), the ERC tap controls
under --erc-out (default: `layout/erc/controls`) -- pruning stray `.gds`
files; the `.json` reports next to them are recorded evidence and are never
touched. `--check` regenerates in memory and exits 1 on any difference
against the files on disk (changed, missing, or stray `.gds`);
`check-ci.sh layouts` runs it on every PR. Exit 2 means the config is
invalid; exit 3 means a control's forcing cannot be placed.

Each control is the shipped generator's own drawing engine inside the
shared `forced_strip_profile` context manager: one strip's devices are handed
the forced height profile and, for the refused rows, `_notch_violation` is
stubbed to None so the notch is drawn -- the same forcing
`layout/tests/test_gen_layouts.py::ForcedNotch` exercises. The table below
is the recipe the recorded controls were produced with (issue #120): the
config cell is renamed to `notch_<strip>_p<pitch>` (the committed streams'
structure name, with `_lib` as the library name), and the two 840-pitch
rows carry the row-height and channel-track overrides the taller `and2` row
needs on top of the pitch bump.

Each ERC control (issue #179) is the same drawing engine with one tap band's
shapes filtered out of the finished drawing: the well (or substrate) band is
the only activ of the tap's implant polarity beyond the diffusion strips, so
its activ/implant/contact boxes are identified by that y-position alone
(above `row_height - p_diff_top_margin`, below `n_diff_y0`) and dropped --
no generator internals are patched or re-derived. The committed report must
then show `erc.missing_tie` for the removed tie (`layout/run_erc.py` grades
that direction). The row's `remove` names the band: "nwell" or "substrate".
"""
import argparse
import contextlib
import copy
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "design"))
import gen_layouts as gl  # noqa: E402
import gen_netlists as gn  # noqa: E402

CONFIG = pathlib.Path(__file__).resolve().parent / "example_config.json"
CONTROLS = pathlib.Path(__file__).resolve().parent / "drc" / "controls"
ERC_CONTROLS = pathlib.Path(__file__).resolve().parent / "erc" / "controls"

# The shipped inv_1 / inv_4 device sets, by config cell name (looked up so
# the tables follow the config), and the and2 row the 840-pitch controls
# were measured on (not a shipped cell; the definition ForcedNotch exercises).
INV1 = "sg13g2_inv_1"
INV4 = "sg13g2_inv_4"
AND2 = {"family": "and2", "drive": 1, "inputs": ["A", "B"], "outputs": {"X": "(A*B)"}}

# One row per committed control, in recording order (#86, then #114, then
# #169): `stem` is the committed filename (`.gds` appended); `cell` the base
# cell; `layout` the overrides on the shipped config's layout block; `force`
# the strip drawn with a forced height profile; `notch_off` whether
# `_notch_violation` was stubbed off so the refused notch is drawn; `breaks`
# a (strip, order position) pair forcing a diffusion break there, patching
# `order_strips` instead of the profile.
TABLE = [
    {"stem": "notch-nmos-p420-refused", "cell": INV4, "layout": {},
     "force": ("n", [500, 320, 500, 500]), "notch_off": True},
    {"stem": "notch-nmos-p840-admitted", "cell": AND2,
     "layout": {"row_height_nm": 4200, "gate_pitch_nm": 840, "channel_tracks": 2},
     "force": ("n", [1000, 500, 1000]), "notch_off": False},
    {"stem": "notch-pmos-p840-refused", "cell": AND2,
     "layout": {"row_height_nm": 4200, "gate_pitch_nm": 840, "channel_tracks": 2},
     "force": ("p", [800, 500, 800]), "notch_off": True},
    {"stem": "notch-pmos-p600-merged", "cell": INV4, "layout": {"gate_pitch_nm": 600},
     "force": ("p", [800, 500, 800, 800]), "notch_off": False},
    {"stem": "break-pmos-p420", "cell": "sg13g2_nand2_1", "layout": {},
     "breaks": ("p", 1)},
]

# One row per committed ERC tap control (issues #179 and #232), in recording
# order: `stem` the committed filename (`.gds`/`.json` appended); `cell` the
# base config cell; `top` the committed stream's structure name (`_lib`
# appended for the library); `remove` which tap band is filtered out --
# "nwell" (the n-well tie to VDD) or "substrate" (the p-substrate tie to
# VSS).
ERC_TABLE = [
    {"stem": "missing-tie-nwell-inv1", "cell": INV1, "top": "missing_tie_nwell_inv1",
     "remove": "nwell"},
    {"stem": "missing-tie-substrate-inv1", "cell": INV1, "top": "missing_tie_substrate_inv1",
     "remove": "substrate"},
]


def _base_cell(cfg, base):
    """A deep copy of a row's base cell: a config cell by name, or an inline one."""
    if not isinstance(base, str):
        return copy.deepcopy(base)
    for c in cfg["cells"]:
        if c["name"] == base:
            return copy.deepcopy(c)
    raise ValueError(f"config has no cell {base!r} for a control row")


@contextlib.contextmanager
def forced_strip_profile(strip, profile, notch_off=False):
    """Force `gl._strip_profile` to hand back `profile` for `strip`'s devices.

    The notch check stays live unless `notch_off` (drawing a refused control,
    whose notch must still be drawn). Both patched attributes are restored on
    exit, so a cell that fails to place cannot leave the generator patched
    for the next one."""
    real_prof, real_hit = gl._strip_profile, gl._notch_violation

    def patched_prof(order, devs_, cols_):
        p = real_prof(order, devs_, cols_)
        return list(profile) if devs_[0][1] == strip else p

    gl._strip_profile = patched_prof
    gl._notch_violation = (lambda *a, **k: None) if notch_off else real_hit
    try:
        yield
    finally:
        gl._strip_profile = real_prof
        gl._notch_violation = real_hit


@contextlib.contextmanager
def forced_break(strip, at):
    """Force one diffusion break at order position `at` of `strip`.

    Patches `gl.order_strips`: the pairing the model picks is kept and one
    break is added to it. Restored on exit even if the cell fails to place."""
    real_order = gl.order_strips

    def patched_order(ndevs, pdevs):
        nord, nbrk, pord, pbrk = real_order(ndevs, pdevs)
        if strip == "p":
            pbrk = tuple(sorted(set(pbrk) | {at}))
        else:
            nbrk = tuple(sorted(set(nbrk) | {at}))
        return nord, nbrk, pord, pbrk

    gl.order_strips = patched_order
    try:
        yield
    finally:
        gl.order_strips = real_order


def regenerate(row, config):
    """One control as {committed filename: bytes}, via the shared forcing.

    The forcing context wraps `gl.generate`, so a failed row cannot leave
    the generator patched for the next one."""
    cfg = copy.deepcopy(config)
    cfg["layout"].update(row["layout"])
    cell = _base_cell(cfg, row["cell"])
    if "breaks" in row:
        strip = row["breaks"][0]
        # The naming rule every committed stream follows: the config's cell
        # name is the GDS structure name, with "_lib" appended for the library.
        cell["name"] = f"break_{strip}_p{cfg['layout']['gate_pitch_nm']}"
    else:
        strip, profile = row["force"]
        cell["name"] = f"notch_{strip}_p{cfg['layout']['gate_pitch_nm']}"
    cfg["cells"] = [cell]

    if "breaks" in row:
        forcing = forced_break(*row["breaks"])
    else:
        forcing = forced_strip_profile(strip, row["force"][1], notch_off=row["notch_off"])
    with forcing:
        files = gl.generate(cfg)
    (name,) = files  # one control cell in, one stream out
    return {f"{row['stem']}.gds": files[name]}


def generate_controls(config, table=None):
    """{committed control filename: bytes} for every table row."""
    files = {}
    for row in (table if table is not None else TABLE):
        files.update(regenerate(row, config))
    return files


# The layers each tap band draws on (implant polarity picks the band: nsd is
# the n-well tap, psd the substrate tap), and the diffusion-strip edges a
# band sits beyond -- the generator pushes the well band above the PMOS strip
# and the substrate band below the NMOS strip (layout/gen_layouts.py), so
# those two config-level edges identify the band's boxes by y-position alone.
_TAP_BANDS = {
    "nwell": {"activ", "nsd", "cont"},
    "substrate": {"activ", "psd", "cont"},
}


def regenerate_erc(row, config):
    """One ERC control as {committed filename: bytes}: the base cell drawn by
    the shipped engine with one tap band's shapes filtered out.

    No generator internals are patched: `gen_layouts.layout_cell` draws the
    intact cell, then the band's activ/implant/cont boxes -- the only shapes
    of that implant polarity beyond the diffusion strips -- are dropped from
    the finished drawing. The rails and the band's Metal1 patch stay (a rail
    that no longer ties its well is exactly the defect under test); the
    `klt erc` tie check sees no tap geometry inside the well and reports
    `erc.missing_tie` (layout/run_erc.py grades that direction)."""
    cfg = copy.deepcopy(config)
    cell = _base_cell(cfg, row["cell"])
    cell["name"] = row["top"]
    cfg["cells"] = [cell]
    lay = cfg["layout"]
    layers = {k: tuple(v) for k, v in lay["layers"].items()}
    shapes, _, _ = gl.layout_cell(cell, cfg["process"], lay)
    p_y1 = lay["row_height_nm"] - lay["p_diff_top_margin_nm"]
    n_y0 = lay["n_diff_y0_nm"]

    def in_removed_band(box):
        layer, _x0, y0, _x1, y1 = box
        if layer not in _TAP_BANDS[row["remove"]]:
            return False
        return y0 >= p_y1 if row["remove"] == "nwell" else y1 <= n_y0

    shapes.boxes = [b for b in shapes.boxes if not in_removed_band(b)]
    return {f"{row['stem']}.gds": gl.gds_bytes(row["top"], shapes, layers)}


def generate_erc_controls(config, table=None):
    """{committed ERC control filename: bytes} for every ERC table row."""
    files = {}
    for row in (table if table is not None else ERC_TABLE):
        files.update(regenerate_erc(row, config))
    return files


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", default=str(CONFIG), help="cell/process/layout config JSON (default: the shipped example config)")
    ap.add_argument("--out", help="notch DRC controls directory (default: layout/drc/controls)")
    ap.add_argument("--erc-out", help="ERC tap controls directory (default: layout/erc/controls)")
    ap.add_argument("--check", action="store_true", help="fail if committed control GDS differ from regenerated ones")
    a = ap.parse_args(argv)
    cfg_path = pathlib.Path(a.config)
    try:
        config = json.loads(cfg_path.read_text())
        files = generate_controls(config)
        erc_files = generate_erc_controls(config)
    except (ValueError, OSError) as e:
        print(f"gen_controls: invalid config {cfg_path}: {e}", file=sys.stderr)
        return 2
    except gl.PlaceError as e:
        print(f"gen_controls: cannot place: {e}", file=sys.stderr)
        return 3
    # A bare `--out` keeps its single-output behavior (only the notch DRC set is
    # written there); a bare `--erc-out` writes only the ERC set. With neither,
    # both committed sets are regenerated in place. Each set is pruned by its
    # own `*.gds` sync, so the two directories must never coincide.
    both_default = not a.out and not a.erc_out
    targets = []
    if a.out or both_default:
        targets.append((files, pathlib.Path(a.out) if a.out else CONTROLS, "control GDS", "control GDS file(s)"))
    if a.erc_out or both_default:
        targets.append((erc_files, pathlib.Path(a.erc_out) if a.erc_out else ERC_CONTROLS, "ERC control GDS", "ERC control GDS file(s)"))
    if len(targets) == 2 and targets[0][1].resolve() == targets[1][1].resolve():
        print(f"gen_controls: --out and --erc-out resolve to the same directory {targets[0][1]}; "
              "each set prunes *.gds, so they must differ", file=sys.stderr)
        return 2
    rc = 0
    for tfiles, tdir, plural, out_of_date in targets:
        rc |= gn.sync_outputs(
            tfiles, tdir, "*.gds", check=a.check, tool="gen_controls", script="layout/gen_controls.py",
            plural=plural, out_of_date=out_of_date,
        )
    return rc


if __name__ == "__main__":
    sys.exit(main())
