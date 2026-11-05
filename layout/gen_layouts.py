#!/usr/bin/env python3
"""PDK-independent static-CMOS cell layout generator (netlist + config -> GDS).

Usage: gen_layouts.py --config CONFIG.json [--out DIR] [--check]

Default mode (re)writes one `<cell>.gds` per config cell under --out (default:
`<config dir>/gds`). `--check` regenerates in memory and exits 1 on any
difference against the files on disk (changed, missing, or stray `.gds`).
Output is byte-deterministic (own GDSII writer, zero timestamps, fixed
ordering), so the check is a byte compare. Exit 2 means the config is invalid;
exit 3 means a cell cannot be placed (the reason is named, and no partial GDS
is written for any cell).

The devices come from design/gen_netlists.py (`build`), so layout and netlist
agree by construction. The engine holds no PDK constants: row height, pitch,
layer map and every design rule come from the config's `layout` object
(contract in layout/README.md).

Placement model (deliberately small; anything outside it is a named failure):
  * one NMOS diffusion strip (bottom) and one PMOS strip (top), one gate
    column per device pair, diffusion shared between neighbouring devices;
  * the strips are ordered so each is a single chain of devices sharing a
    source/drain net, and both orderings have the same gate-net sequence, so
    each poly column crosses both strips;
  * Metal1 only: VSS/VDD rails on the row edges, vertical stubs from diffusion
    contacts, at most `channel_tracks` horizontal tracks between the strips
    for nets that need joining, one gate contact pad per input.
"""
import argparse
import json
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "design"))
import gen_netlists as gn  # noqa: E402

LAYER_KEYS = ("nwell", "activ", "gatpoly", "psd", "cont", "metal1", "metal1_label")
OPTIONAL_LAYERS = ("nsd",)
RULE_KEYS = (
    "poly_width_nm", "poly_space_nm", "poly_endcap_nm", "poly_to_activ_nm", "cont_nm", "cont_space_nm",
    "activ_enc_cont_nm", "poly_enc_cont_nm", "m1_width_nm", "m1_space_nm",
    "rail_width_nm", "nwell_enc_pactiv_nm", "sd_enc_activ_nm",
)
LAYOUT_INT_KEYS = ("row_height_nm", "gate_pitch_nm", "channel_tracks", "n_diff_y0_nm", "p_diff_top_margin_nm")


class PlaceError(Exception):
    """A cell cannot be placed by this generator; the message names why."""


# ---------------------------------------------------------------- config
def _posint(v):
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


def validate_layout(config):
    """Raise ValueError on a malformed `layout` block; return it."""
    lay = config.get("layout")
    if not isinstance(lay, dict):
        raise ValueError("config needs a 'layout' object")
    for k in LAYOUT_INT_KEYS:
        if not _posint(lay.get(k)):
            raise ValueError(f"layout.{k} missing or not a positive int")
    layers = lay.get("layers")
    if not isinstance(layers, dict):
        raise ValueError("layout.layers missing")
    for k in LAYER_KEYS + tuple(x for x in OPTIONAL_LAYERS if x in layers):
        v = layers.get(k)
        ok = isinstance(v, list) and len(v) == 2 and all(isinstance(x, int) and not isinstance(x, bool) and 0 <= x < 32768 for x in v)
        if not ok:
            raise ValueError(f"layout.layers.{k} must be [layer, datatype]")
    rules = lay.get("rules")
    if not isinstance(rules, dict):
        raise ValueError("layout.rules missing")
    for k in RULE_KEYS:
        if not _posint(rules.get(k)):
            raise ValueError(f"layout.rules.{k} missing or not a positive int")
    if lay["gate_pitch_nm"] % 2:
        raise ValueError("layout.gate_pitch_nm must be even (node centres sit on half pitches)")
    return lay


def validate(config):
    gn.validate(config)
    validate_layout(config)
    return config


# ---------------------------------------------------------------- ordering
def _chains(devs, ends):
    """All orderings of devs (index, kind, d, g, s, w, ng) as one chain where
    neighbours share a diffusion net. Yields lists of (dev, left_net, right_net)."""
    n = len(devs)
    out = []

    def extend(order, left_nets, used):
        if len(order) == n:
            out.append(list(order))
            return
        tail = order[-1][2]
        for i in range(n):
            if i in used:
                continue
            d = devs[i]
            for l, r in ((d[2], d[4]), (d[4], d[2])):
                if l == tail:
                    order.append((i, l, r))
                    used.add(i)
                    extend(order, left_nets, used)
                    used.discard(i)
                    order.pop()

    for i in range(n):
        d = devs[i]
        for l, r in ((d[2], d[4]), (d[4], d[2])):
            extend([(i, l, r)], None, {i})
    return out


def order_strips(ndevs, pdevs):
    """Pick (n_order, p_order) with equal gate-net sequences, deterministically."""
    if len(ndevs) != len(pdevs):
        raise PlaceError(f"{len(ndevs)} NMOS vs {len(pdevs)} PMOS devices: gate columns cannot pair up")
    nch, pch = _chains(ndevs, None), _chains(pdevs, None)
    if not nch:
        raise PlaceError("NMOS devices do not form a single diffusion chain (needs a diffusion break)")
    if not pch:
        raise PlaceError("PMOS devices do not form a single diffusion chain (needs a diffusion break)")
    best = None
    for a in nch:
        ga = [ndevs[i][3] for i, _, _ in a]
        for b in pch:
            if [pdevs[i][3] for i, _, _ in b] == ga:
                key = (tuple(i for i, _, _ in a), tuple(i for i, _, _ in b), tuple(l for _, l, _ in a), tuple(l for _, l, _ in b))
                if best is None or key < best[0]:
                    best = (key, a, b)
    if best is None:
        raise PlaceError("no NMOS/PMOS strip orderings share one gate-net sequence (gate nets cannot align in columns)")
    return best[1], best[2]


# ---------------------------------------------------------------- geometry
class Shapes:
    def __init__(self):
        self.boxes = []   # (layername, x0, y0, x1, y1)
        self.labels = []  # (layername, x, y, text)

    def box(self, layer, x0, y0, x1, y1):
        self.boxes.append((layer, min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)))


def _overlap_or_close(a, b, gap):
    return not (a[2] + gap <= b[0] or b[2] + gap <= a[0] or a[3] + gap <= b[1] or b[3] + gap <= a[1])


def layout_cell(cell, proc, lay):
    """Return (Shapes, width_nm, height_nm) for one config cell, or raise PlaceError."""
    R, P = lay["rules"], lay["gate_pitch_nm"]
    H = lay["row_height_nm"]
    name = cell["name"]
    c = gn.build(cell, proc)
    devs = [(i,) + d for i, d in enumerate(c.devices)]  # (i, kind, drain, gate, source, w, ng)
    ndevs = [(i, k, d, g, s, w, ng) for (i, k, d, g, s, w, ng) in devs if k == "n"]
    pdevs = [(i, k, d, g, s, w, ng) for (i, k, d, g, s, w, ng) in devs if k == "p"]
    for d in devs:
        if d[6] != 1:
            raise PlaceError(f"device of {d[5]} nm needs {d[6]} fingers; multi-finger devices are not placed")
    nord, pord = order_strips(ndevs, pdevs)
    N = len(nord)
    W = (N + 1) * P
    rail = R["rail_width_nm"]
    vdd, vss = proc["vdd_net"], proc["vss_net"]
    node_x = [P // 2 + j * P for j in range(N + 1)]
    gate_x = [(j + 1) * P for j in range(N)]
    wn = max(ndevs[i][5] for i, _, _ in nord)
    wp = max(pdevs[i][5] for i, _, _ in pord)
    n_y0 = lay["n_diff_y0_nm"]
    n_y1 = n_y0 + wn
    p_y1 = H - lay["p_diff_top_margin_nm"]
    p_y0 = p_y1 - wp
    if p_y0 <= n_y1:
        raise PlaceError(f"row height {H} nm leaves no channel between the NMOS and PMOS strips")
    half_c = R["cont_nm"] // 2
    act_hang = half_c + R["activ_enc_cont_nm"]  # diffusion extent beyond a node-centre
    if P // 2 - R["poly_width_nm"] // 2 < half_c:
        raise PlaceError("gate pitch too small for a contact between two gates")
    S = Shapes()

    # Node nets for each strip: node j sits between device j-1 and j.
    def nodes(order, devs_):
        nets = [None] * (N + 1)
        for j, (i, l, r) in enumerate(order):
            nets[j] = l
            nets[j + 1] = r
        return nets

    nn, pn = nodes(nord, ndevs), nodes(pord, pdevs)

    # Diffusion, implants, well. Strip drawn as one rectangle per device row.
    ax0, ax1 = node_x[0] - act_hang, node_x[-1] + act_hang
    S.box("activ", ax0, n_y0, ax1, n_y1)
    S.box("activ", ax0, p_y0, ax1, p_y1)
    sd = R["sd_enc_activ_nm"]
    S.box("psd", ax0 - sd, p_y0 - sd, ax1 + sd, p_y1 + sd)
    if "nsd" in lay["layers"]:
        S.box("nsd", ax0 - sd, n_y0 - sd, ax1 + sd, n_y1 + sd)
    S.box("nwell", ax0 - R["nwell_enc_pactiv_nm"], p_y0 - R["nwell_enc_pactiv_nm"], ax1 + R["nwell_enc_pactiv_nm"], H + rail // 2)

    # Poly columns: one stripe per gate, crossing both strips.
    pw = R["poly_width_nm"]
    ext = R["poly_endcap_nm"]
    for j in range(N):
        S.box("gatpoly", gate_x[j] - pw // 2, n_y0 - ext, gate_x[j] + pw // 2, p_y1 + ext)

    # Contacts per node (stacked inside the diffusion) and the M1 stub on them.
    mw = R["m1_width_nm"]
    pitch_c = R["cont_nm"] + R["cont_space_nm"]

    def contact_ys(y0, y1):
        room = y1 - y0 - 2 * R["activ_enc_cont_nm"] - R["cont_nm"]
        if room < 0:
            raise PlaceError(f"diffusion {y1 - y0} nm tall is too short for a contact")
        k = room // pitch_c + 1
        span = (k - 1) * pitch_c
        base = (y0 + y1) // 2 - span // 2 - half_c
        return [base + t * pitch_c for t in range(k)]

    net_m1 = {}  # net -> list of (rect, kind, x, side)
    for strip, nets, y0, y1, side in (("n", nn, n_y0, n_y1, "below"), ("p", pn, p_y0, p_y1, "above")):
        cys = contact_ys(y0, y1)
        for j, net in enumerate(nets):
            x = node_x[j]
            for cy in cys:
                S.box("cont", x - half_c, cy, x + half_c, cy + R["cont_nm"])
            lo, hi = cys[0], cys[-1] + R["cont_nm"]
            if net == vss and strip == "n":
                lo = -rail // 2
            elif net == vdd and strip == "p":
                hi = H + rail // 2
            elif net in (vss, vdd):
                raise PlaceError(f"{strip.upper()}MOS diffusion node on rail {net} of the wrong polarity")
            rect = (x - mw // 2, lo, x + mw // 2, hi)
            net_m1.setdefault(net, []).append((rect, side))

    # Gate contacts: a poly pad in the channel, on the column's poly.
    gates = [ndevs[i][3] for i, _, _ in nord]
    gate_rects = {}
    pad_h = R["cont_nm"] + 2 * R["poly_enc_cont_nm"]
    gate_pad_y = p_y0 - R["poly_to_activ_nm"] - R["poly_enc_cont_nm"] - R["cont_nm"]
    if gate_pad_y - R["poly_enc_cont_nm"] < n_y1 + R["poly_to_activ_nm"]:
        raise PlaceError("channel too short for a gate contact pad")
    seen_gate = {}
    for j, g in enumerate(gates):
        if g in seen_gate:
            raise PlaceError(f"gate net {g} drives two columns; joining them needs more routing than one track model")
        seen_gate[g] = j

    # Horizontal tracks for signal nets with more than one attachment.
    tracks = {}
    need = [n for n, att in net_m1.items() if n not in (vss, vdd) and len(att) > 1]
    need.sort()
    if len(need) > lay["channel_tracks"]:
        raise PlaceError(f"nets {need} need {len(need)} channel tracks, config allows {lay['channel_tracks']}")
    # Tracks sit at the channel bottom; gate contact pads sit at the channel top.
    track_base = n_y1 - R["activ_enc_cont_nm"] + R["m1_space_nm"]  # clear the NMOS contact stubs
    for t, net in enumerate(need):
        y0 = track_base + t * (mw + R["m1_space_nm"])
        if y0 + mw + R["m1_space_nm"] > gate_pad_y:
            raise PlaceError(f"channel too short for track {t + 1} of net {net}")
        tracks[net] = (y0, y0 + mw)
    m1 = []  # (net, rect)
    for net, att in sorted(net_m1.items()):
        if net in tracks:
            ty0, ty1 = tracks[net]
            xs = []
            for rect, side in att:
                x0, y0, x1, y1 = rect
                if side == "below":
                    y1 = max(y1, ty1)
                else:
                    y0 = min(y0, ty0)
                m1.append((net, (x0, y0, x1, y1)))
                xs.append((x0 + x1) // 2)
            m1.append((net, (min(xs) - mw // 2, ty0, max(xs) + mw // 2, ty1)))
        else:
            for rect, _ in att:
                m1.append((net, rect))
    for rect_net, rect in m1:
        S.box("metal1", *rect)

    poly_pads = []
    # Gate pads: poly + contact + M1, offset to a side whose M1 neighbours leave room.
    for j, g in enumerate(gates):
        placed = None
        for sgn in (-1, 1):
            cx = gate_x[j] + sgn * (R["poly_enc_cont_nm"] + half_c)
            pad = (cx - mw // 2, gate_pad_y, cx + mw // 2, gate_pad_y + R["cont_nm"])
            others = [r for n2, r in m1 if n2 != g]
            if cx - half_c - R["poly_enc_cont_nm"] < 0 or cx + half_c + R["poly_enc_cont_nm"] > W:
                continue
            ppad = (min(cx - half_c - R["poly_enc_cont_nm"], gate_x[j] - pw // 2), gate_pad_y - R["poly_enc_cont_nm"],
                    max(cx + half_c + R["poly_enc_cont_nm"], gate_x[j] + pw // 2), gate_pad_y - R["poly_enc_cont_nm"] + pad_h)
            others_poly = [(gate_x[k] - pw // 2, ppad[1], gate_x[k] + pw // 2, ppad[3]) for k in range(N) if k != j] + poly_pads
            if any(_overlap_or_close(ppad, r, R["poly_space_nm"]) for r in others_poly):
                continue
            if all(not _overlap_or_close(pad, r, R["m1_space_nm"]) for r in others):
                placed = (cx, pad)
                poly_pads.append(ppad)
                break
        if placed is None:
            raise PlaceError(f"no Metal1-clean spot for the gate contact of {g} (neighbouring stubs/tracks in the way)")
        cx, pad = placed
        S.box("gatpoly", min(cx - half_c - R["poly_enc_cont_nm"], gate_x[j] - pw // 2), gate_pad_y - R["poly_enc_cont_nm"],
              max(cx + half_c + R["poly_enc_cont_nm"], gate_x[j] + pw // 2), gate_pad_y - R["poly_enc_cont_nm"] + pad_h)
        S.box("cont", cx - half_c, gate_pad_y, cx + half_c, gate_pad_y + R["cont_nm"])
        S.box("metal1", *pad)
        m1.append((g, pad))
        S.labels.append(("metal1_label", cx, gate_pad_y + half_c, g))

    # Rails and output/rail labels.
    S.box("metal1", 0, -rail // 2, W, rail // 2)
    S.box("metal1", 0, H - rail // 2, W, H + rail // 2)
    S.labels.append(("metal1_label", W // 2, 0, vss))
    S.labels.append(("metal1_label", W // 2, H, vdd))
    for pin in sorted(cell["outputs"]):
        if pin not in net_m1:
            raise PlaceError(f"output {pin} has no diffusion node")
        rect = net_m1[pin][0][0]
        S.labels.append(("metal1_label", (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2, pin))
    for net_a, ra in m1:
        for net_b, rb in m1:
            if net_a != net_b and (ra[0] < rb[2] and rb[0] < ra[2] and ra[1] < rb[3] and rb[1] < ra[3]):
                raise PlaceError(f"Metal1 of {net_a} overlaps {net_b} (routing model cannot separate them)")
    return S, W, H


# ---------------------------------------------------------------- GDSII
def _rec(rtype, dtype, payload=b""):
    return struct.pack(">HBB", len(payload) + 4, rtype, dtype) + payload


def _real8(x):
    if x == 0:
        return b"\0" * 8
    sign = 0x80 if x < 0 else 0
    x = abs(x)
    exp = 0
    while x >= 1:
        x /= 16
        exp += 1
    while x < 1 / 16:
        x *= 16
        exp -= 1
    mant = int(round(x * (1 << 56)))
    if mant >= 1 << 56:
        mant >>= 4
        exp += 1
    return bytes([sign | (exp + 64)]) + mant.to_bytes(7, "big")


def _str(s):
    b = s.encode("ascii")
    return b + b"\0" if len(b) % 2 else b


def gds_bytes(cell_name, shapes, layers):
    """Deterministic GDSII: 1 nm database unit, zero timestamps, sorted shapes."""
    zero = struct.pack(">12h", *([0] * 12))
    out = [
        _rec(0x00, 2, struct.pack(">h", 600)),
        _rec(0x01, 2, zero),
        _rec(0x02, 6, _str(cell_name + "_lib")),
        _rec(0x03, 5, _real8(1e-3) + _real8(1e-9)),
        _rec(0x05, 2, zero),
        _rec(0x06, 6, _str(cell_name)),
    ]
    for layer, x0, y0, x1, y1 in sorted(shapes.boxes, key=lambda b: (layers[b[0]], b[1:])):
        ln, dt = layers[layer]
        pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
        out += [_rec(0x08, 0), _rec(0x0D, 2, struct.pack(">h", ln)), _rec(0x0E, 2, struct.pack(">h", dt)),
                _rec(0x10, 3, b"".join(struct.pack(">ii", x, y) for x, y in pts)), _rec(0x11, 0)]
    for layer, x, y, text in sorted(shapes.labels, key=lambda t: (layers[t[0]], t[1:])):
        ln, dt = layers[layer]
        out += [_rec(0x0C, 0), _rec(0x0D, 2, struct.pack(">h", ln)), _rec(0x16, 2, struct.pack(">h", dt)),
                _rec(0x10, 3, struct.pack(">ii", x, y)), _rec(0x19, 6, _str(text)), _rec(0x11, 0)]
    out += [_rec(0x07, 0), _rec(0x04, 0)]
    return b"".join(out)


# ---------------------------------------------------------------- driver
def generate(config, config_name="config"):
    """Return {filename: bytes}. Raises ValueError (bad config) or PlaceError."""
    validate(config)
    proc, lay = config["process"], config["layout"]
    layers = {k: tuple(v) for k, v in lay["layers"].items()}
    files = {}
    for cell in config["cells"]:
        try:
            shapes, _, _ = layout_cell(cell, proc, lay)
        except (PlaceError, ValueError) as e:
            raise PlaceError(f"cell {cell['name']!r}: {e}")
        files[f"{cell['name']}.gds"] = gds_bytes(cell["name"], shapes, layers)
    return files


def check(files, outdir):
    errs = []
    on_disk = {p.name for p in outdir.glob("*.gds")} if outdir.is_dir() else set()
    for name, data in sorted(files.items()):
        path = outdir / name
        if name not in on_disk:
            errs.append(f"missing: {path}")
        elif path.read_bytes() != data:
            errs.append(f"stale: {path} (committed {path.stat().st_size} B differs from regenerated {len(data)} B)")
    for name in sorted(on_disk - set(files)):
        errs.append(f"stray: {outdir / name} is not in the config")
    return errs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", required=True, help="cell/process/layout config JSON (see layout/README.md)")
    ap.add_argument("--out", help="GDS directory (default: <config dir>/gds)")
    ap.add_argument("--check", action="store_true", help="fail if committed GDS differ from regenerated ones")
    a = ap.parse_args(argv)
    cfg_path = pathlib.Path(a.config)
    try:
        files = generate(json.loads(cfg_path.read_text()), cfg_path.name)
    except (ValueError, OSError) as e:
        print(f"gen_layouts: invalid config {cfg_path}: {e}", file=sys.stderr)
        return 2
    except PlaceError as e:
        print(f"gen_layouts: cannot place: {e}", file=sys.stderr)
        return 3
    outdir = pathlib.Path(a.out) if a.out else cfg_path.resolve().parent / "gds"
    if a.check:
        errs = check(files, outdir)
        for e in errs:
            print(e, file=sys.stderr)
        if errs:
            print(f"gen_layouts: {len(errs)} GDS file(s) out of date; run layout/gen_layouts.py", file=sys.stderr)
            return 1
        print(f"gen_layouts: {len(files)} GDS fresh")
        return 0
    outdir.mkdir(parents=True, exist_ok=True)
    for stale in outdir.glob("*.gds"):
        if stale.name not in files:
            stale.unlink()
    for name, data in files.items():
        (outdir / name).write_bytes(data)
    print(f"gen_layouts: wrote {len(files)} GDS to {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
