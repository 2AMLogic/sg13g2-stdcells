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
    column per finger, diffusion shared between neighbouring devices; a device
    of F fingers is F adjacent columns alternating source/drain, joined by a
    poly bridge below the NMOS diffusion and given one gate contact. The NMOS
    and PMOS device on one gate net are drawn with the same finger count (the
    larger; a device with fewer netlist fingers is folded, same total width);
  * a strip may hold devices of different drawn finger widths: it is one merged
    polygon whose outer edge is fixed (the NMOS strip grows up, the PMOS strip
    grows down) and whose channel-facing edge steps at the device boundary. A
    tall-short-tall height profile would leave a re-entrant notch in that
    polygon, which the diffusion/implant space-or-notch rules forbid, so it is
    a named failure rather than a drawn shape;
  * the strips are ordered so each is a single chain of devices sharing a
    source/drain net, and both orderings have the same gate-net sequence, so
    each poly column crosses both strips;
  * Metal1 only: VSS/VDD rails on the row edges, vertical stubs from diffusion
    contacts, at most `channel_tracks` horizontal tracks between the strips
    for nets that need joining, one gate contact pad per input;
  * one well tap (n-well tie to VDD, under the VDD rail) and one substrate tap
    (p-substrate tie to VSS, under the VSS rail) per cell, so the extracted
    device bodies land on VDD/VSS instead of a synthesized well/substrate net.
    The n-well is extended above the row to enclose the well tie.
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
    "rail_width_nm", "nwell_enc_pactiv_nm", "nwell_enc_nactiv_nm", "activ_space_nm",
    "sd_enc_activ_nm",
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
def end_net(l, r, fingers):
    """Net at the far end of a device whose `fingers` columns alternate l, r, l, ..."""
    return r if fingers % 2 else l


def _chains(devs):
    """All orderings of devs (index, kind, d, g, s, w, fingers) as one chain where
    neighbours share a diffusion net. A device of F fingers is F columns that
    alternate source/drain, so it ends on its right net only for odd F; for even F
    it ends back on its left net. Yields lists of (dev, left_net, right_net)."""
    n = len(devs)
    out = []

    def extend(order, used):
        if len(order) == n:
            out.append(list(order))
            return
        i0, l0, r0 = order[-1]
        tail = end_net(l0, r0, devs[i0][6])
        for i in range(n):
            if i in used:
                continue
            d = devs[i]
            for l, r in ((d[2], d[4]), (d[4], d[2])):
                if l == tail:
                    order.append((i, l, r))
                    used.add(i)
                    extend(order, used)
                    used.discard(i)
                    order.pop()

    for i in range(n):
        d = devs[i]
        for l, r in ((d[2], d[4]), (d[4], d[2])):
            extend([(i, l, r)], {i})
    return out


def order_strips(ndevs, pdevs):
    """Pick (n_order, p_order) with equal gate-net sequences, deterministically."""
    if len(ndevs) != len(pdevs):
        raise PlaceError(f"{len(ndevs)} NMOS vs {len(pdevs)} PMOS devices: gate columns cannot pair up")
    nch, pch = _chains(ndevs), _chains(pdevs)
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


def _dev_at(order, devs_, cols_, c):
    """The (folded) device drawn in column `c` of a strip."""
    return devs_[order[cols_[c][0]][0]]


def _dev_desc(d):
    """A folded device's netlist geometry and its drawn geometry, both named.

    The fold step can divide a width that is uniform in the netlist into fingers
    that appear nowhere in it (a 500 nm 1-finger device folded to 2 fingers is
    drawn as 2 x 250 nm), so a message quoting only one of the two sends the
    reader looking for a number the netlist does not contain."""
    return (f"{d[1].upper()}MOS on gate {d[3]} (netlist {d[5]} nm / {d[7]} "
            f"finger{'' if d[7] == 1 else 's'} -> drawn {d[6]} x {d[5] // d[6]} nm)")


def _strip_profile(order, devs_, cols_):
    """Drawn finger width per column: the strip's height profile."""
    return [d[5] // d[6] for d in (_dev_at(order, devs_, cols_, c) for c in range(len(cols_)))]


def _runs(prof):
    """Maximal spans of equal-height columns as [first column, last column, height]."""
    out = []
    for c, h in enumerate(prof):
        if out and out[-1][2] == h:
            out[-1][1] = c
        else:
            out.append([c, c, h])
    return out


def _notch_column(prof):
    """First column that sits in a valley of `prof` (taller columns on both
    sides), or None. Such a column is a re-entrant notch in the merged strip
    polygon; a profile without one is unimodal, so every step is a single
    concave corner, which the space-or-notch rules allow."""
    for c in range(1, len(prof) - 1):
        if max(prof[:c]) > prof[c] < max(prof[c + 1:]):
            return c
    return None


def layout_cell(cell, proc, lay):
    """Return (Shapes, width_nm, height_nm) for one config cell, or raise PlaceError."""
    R, P = lay["rules"], lay["gate_pitch_nm"]
    H = lay["row_height_nm"]
    c = gn.build(cell, proc)
    devs = [(i,) + d for i, d in enumerate(c.devices)]  # (i, kind, drain, gate, source, w, ng)
    ndevs = [(i, k, d, g, s, w, ng) for (i, k, d, g, s, w, ng) in devs if k == "n"]
    pdevs = [(i, k, d, g, s, w, ng) for (i, k, d, g, s, w, ng) in devs if k == "p"]
    # Fingers per gate net: a poly column crosses both strips, so the NMOS and
    # PMOS device on one gate net are drawn with the same finger count, the larger
    # of the two. A device with fewer netlist fingers is folded (same total W).
    grid = gn.grid_nm(proc)
    fingers = {}
    for d in devs:
        fingers[d[3]] = max(fingers.get(d[3], 1), d[6])

    def fold(d):
        k = fingers[d[3]]
        if d[5] % (k * grid):
            raise PlaceError(f"{d[1]}MOS device of {d[5]} nm on gate {d[3]} cannot be drawn as {k} fingers on the {grid} nm grid")
        return d[:6] + (k, d[6])  # drawn finger count, then the netlist one (for messages)

    ndevs, pdevs = [fold(d) for d in ndevs], [fold(d) for d in pdevs]
    nord, pord = order_strips(ndevs, pdevs)
    cols = [(j, k) for j, (i, _, _) in enumerate(nord) for k in range(ndevs[i][6])]  # column -> (position in order, finger)
    pcols = [(j, k) for j, (i, _, _) in enumerate(pord) for k in range(pdevs[i][6])]
    N = len(cols)
    if N != len(pcols):
        raise PlaceError("NMOS and PMOS strips have different column counts")
    # Height profile: devices of different drawn finger widths share a strip, so
    # the strip's channel-facing edge steps from column to column. Refuse a
    # profile with a valley in it -- that is a re-entrant notch in the merged
    # activ/psd/nsd polygon, and those are space-*or-notch* rules.
    nprof = _strip_profile(nord, ndevs, cols)
    pprof = _strip_profile(pord, pdevs, pcols)
    for kind, order, devs_, cols_, prof in (("N", nord, ndevs, cols, nprof), ("P", pord, pdevs, pcols, pprof)):
        c = _notch_column(prof)
        if c is not None:
            raise PlaceError(
                f"{kind}MOS strip height profile {prof} nm is tall-short-tall at column {c}, so the "
                f"merged diffusion and implant would leave a re-entrant notch (activ.space / psd.space "
                f"are space-or-notch rules); the short device is {_dev_desc(_dev_at(order, devs_, cols_, c))}")
    W = (N + 1) * P
    rail = R["rail_width_nm"]
    vdd, vss = proc["vdd_net"], proc["vss_net"]
    node_x = [P // 2 + j * P for j in range(N + 1)]
    gate_x = [(j + 1) * P for j in range(N)]
    n_y0 = lay["n_diff_y0_nm"]
    p_y1 = H - lay["p_diff_top_margin_nm"]
    # Each strip's outer edge is fixed; the channel-facing one steps. Every
    # channel check below reads the *tallest* run, so a short device in the strip
    # cannot loosen a clearance by accident.
    n_y1 = n_y0 + max(nprof)
    p_y0 = p_y1 - max(pprof)
    if p_y0 <= n_y1:
        raise PlaceError(f"row height {H} nm leaves no channel between the NMOS and PMOS strips")
    half_c = R["cont_nm"] // 2
    act_hang = half_c + R["activ_enc_cont_nm"]  # diffusion extent beyond a node-centre
    if P // 2 - R["poly_width_nm"] // 2 < half_c:
        raise PlaceError("gate pitch too small for a contact between two gates")
    S = Shapes()

    # Node nets for each strip: node j sits between device j-1 and j.
    def nodes(order, devs_):
        nets = [order[0][1]]
        for i, l, r in order:  # F fingers alternate l, r, l, ...; the next device starts on the last node
            nets += [r if f % 2 == 0 else l for f in range(devs_[i][6])]
        return nets

    nn, pn = nodes(nord, ndevs), nodes(pord, pdevs)

    # Poly extents, needed before the well box because the well tap sits poly-clear
    # above the PMOS strip and the n-well has to enclose it.
    pw = R["poly_width_nm"]
    ext = R["poly_endcap_nm"]
    # Fingers of one device are joined by a poly bridge below the NMOS diffusion,
    # poly_to_activ clear of it; only those columns grow down to the bridge.
    bridge_y1 = n_y0 - R["poly_to_activ_nm"]
    bridge_y0 = bridge_y1 - pw
    dev_cols = {}  # position in order -> [column indices]
    for c, (pos, _) in enumerate(cols):
        dev_cols.setdefault(pos, []).append(c)
    multi = any(len(cs) > 1 for cs in dev_cols.values())
    poly_y0 = min(n_y0 - ext, bridge_y0) if multi else n_y0 - ext
    poly_y1 = p_y1 + ext

    # Well/substrate tap bands, one per rail. Without them extraction puts the
    # NMOS body on the deck-synthesized substrate net and the PMOS body on an
    # anonymous n-well net, so every device body is unverified against the
    # reference netlist's VSS/VDD (issue #73). The band is one contact tall plus
    # the diffusion enclosure on each side, pushed as close to its rail as the
    # diffusion spacing and the field-poly clearance allow -- for a multi-finger
    # cell the poly bridge, not the NMOS diffusion, is what binds on the VSS side.
    if "nsd" not in lay["layers"]:
        raise PlaceError("layout.layers.nsd is missing, so the n-well tap cannot be drawn as a well tie "
                         "(the deck derives the tie as activ & nsd); give the config an nsd layer")
    sd = R["sd_enc_activ_nm"]
    if p_y0 - n_y1 <= 2 * sd:
        raise PlaceError(f"channel {p_y0 - n_y1} nm is narrower than the two implant enclosures "
                         f"(2 x sd_enc_activ {sd} nm): psd over the PMOS strip would overlap nsd "
                         "over the NMOS strip, which is not a mask either tool can resolve")
    tap_h = R["cont_nm"] + 2 * R["activ_enc_cont_nm"]
    sub_y1 = min(n_y0 - R["activ_space_nm"], poly_y0 - R["poly_to_activ_nm"])
    sub_y0 = sub_y1 - tap_h
    well_y0 = max(p_y1 + R["activ_space_nm"], poly_y1 + R["poly_to_activ_nm"])
    well_y1 = well_y0 + tap_h
    # The tap implant abuts the device implant of the opposite type instead of
    # overlapping it: psd over nsd is not a mask either tool can resolve.
    if n_y0 - sd <= sub_y1 or p_y1 + sd >= well_y0:
        raise PlaceError(f"sd_enc_activ {sd} nm reaches past the tap bands "
                         f"(substrate {sub_y0}..{sub_y1} nm, well {well_y0}..{well_y1} nm); "
                         "the tap implant cannot abut the device implant")

    # Diffusion, implants, well: one rectangle per run of equal-height columns.
    # Neighbouring runs each reach `act_hang` past the node column they share, so
    # they overlap there and merge into one stepped polygon. The implants and the
    # n-well follow the same step; one rectangle over the tallest run would
    # over-enclose the short ones and can break the implant space rule against a
    # neighbouring cell.
    ax0, ax1 = node_x[0] - act_hang, node_x[-1] + act_hang
    nwe = R["nwell_enc_pactiv_nm"]
    for strip, prof in (("n", nprof), ("p", pprof)):
        for c0, c1, h in _runs(prof):
            x0, x1 = node_x[c0] - act_hang, node_x[c1 + 1] + act_hang
            if strip == "n":
                S.box("activ", x0, n_y0, x1, n_y0 + h)
                S.box("nsd", x0 - sd, n_y0 - sd, x1 + sd, n_y0 + h + sd)
            else:
                S.box("activ", x0, p_y1 - h, x1, p_y1)
                S.box("psd", x0 - sd, p_y1 - h - sd, x1 + sd, p_y1 + sd)
                S.box("nwell", x0 - nwe, p_y1 - h - nwe, x1 + nwe, well_y1 + R["nwell_enc_nactiv_nm"])

    # Poly columns: one stripe per gate, crossing both strips.
    for c in range(N):
        bridged = len(dev_cols[cols[c][0]]) > 1
        S.box("gatpoly", gate_x[c] - pw // 2, min(n_y0 - ext, bridge_y0) if bridged else n_y0 - ext, gate_x[c] + pw // 2, poly_y1)
    for cs in dev_cols.values():
        if len(cs) > 1:
            S.box("gatpoly", gate_x[cs[0]] - pw // 2, bridge_y0, gate_x[cs[-1]] + pw // 2, bridge_y1)

    # Tap bands: activ + the tie implant + one contact per node column. The
    # contact is centred in the band, which puts it on the rail for a cell whose
    # band is not pushed off-centre; the Metal1 patch below closes the rest.
    taps = []  # (net, contact y0, contact y1)
    for ty0, ty1, implant, imp_y0, imp_y1, net in (
            (sub_y0, sub_y1, "psd", sub_y0 - sd, n_y0 - sd, vss),
            (well_y0, well_y1, "nsd", p_y1 + sd, well_y1 + sd, vdd)):
        S.box("activ", ax0, ty0, ax1, ty1)
        S.box(implant, ax0 - sd, imp_y0, ax1 + sd, imp_y1)
        cy = (ty0 + ty1) // 2 - half_c
        for x in node_x:
            S.box("cont", x - half_c, cy, x + half_c, cy + R["cont_nm"])
        taps.append((net, cy, cy + R["cont_nm"]))
        # The band was derived from the extreme edges of the device shapes; check
        # it against every shape actually drawn rather than trusting that sum.
        band = (ax0, ty0, ax1, ty1)
        for layer, gap in (("activ", R["activ_space_nm"]), ("gatpoly", R["poly_to_activ_nm"])):
            for b in S.boxes:
                if b[0] == layer and b[1:] != band and _overlap_or_close(band, b[1:], gap):
                    raise PlaceError(f"{net} tap band {ty0}..{ty1} nm is not {gap} nm clear of "
                                     f"{layer} at {b[1:]}")

    # Contacts per node (stacked inside the diffusion) and the M1 stub on them.
    mw = R["m1_width_nm"]
    pitch_c = R["cont_nm"] + R["cont_space_nm"]

    def contact_ys(y0, y1, what):
        room = y1 - y0 - 2 * R["activ_enc_cont_nm"] - R["cont_nm"]
        if room < 0:
            raise PlaceError(f"diffusion {y1 - y0} nm tall is too short for a contact: {what}")
        k = room // pitch_c + 1
        span = (k - 1) * pitch_c
        base = (y0 + y1) // 2 - span // 2 - half_c
        return [base + t * pitch_c for t in range(k)]

    net_m1 = {}  # net -> list of (rect, side)
    for strip, nets, order, devs_, cols_, prof, side in (
            ("n", nn, nord, ndevs, cols, nprof, "below"),
            ("p", pn, pord, pdevs, pcols, pprof, "above")):
        for j, net in enumerate(nets):
            # Node j sits between columns j-1 and j, and its contact stack has to
            # fit inside both, so the contact floor is a per-device limit: a
            # device folded short cannot hold a contact even where its taller
            # neighbour could. Sizing from the shorter column also names that
            # device in the failure.
            c = min((cc for cc in (j - 1, j) if 0 <= cc < N), key=lambda cc: prof[cc])
            h = prof[c]
            y0, y1 = (n_y0, n_y0 + h) if strip == "n" else (p_y1 - h, p_y1)
            cys = contact_ys(y0, y1, _dev_desc(_dev_at(order, devs_, cols_, c)))
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
    pad_h = R["cont_nm"] + 2 * R["poly_enc_cont_nm"]
    gate_pad_y = p_y0 - R["poly_to_activ_nm"] - R["poly_enc_cont_nm"] - R["cont_nm"]
    if gate_pad_y - R["poly_enc_cont_nm"] < n_y1 + R["poly_to_activ_nm"]:
        raise PlaceError("channel too short for a gate contact pad")
    seen_gate = set()
    for g in gates:
        if g in seen_gate:
            raise PlaceError(f"gate net {g} drives the columns of two different devices; joining them needs more routing than one track model")
        seen_gate.add(g)

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
    for _, rect in m1:
        S.box("metal1", *rect)

    poly_pads = []
    # Gate pads: one per device (its fingers are bridged), poly + contact + M1, on
    # the first finger/side whose M1 and poly neighbours leave room.
    for pos, g in enumerate(gates):
        mine = dev_cols[pos]
        placed = None
        for j in mine:
            for sgn in (-1, 1):
                cx = gate_x[j] + sgn * (R["poly_enc_cont_nm"] + half_c)
                pad = (cx - mw // 2, gate_pad_y, cx + mw // 2, gate_pad_y + R["cont_nm"])
                others = [r for n2, r in m1 if n2 != g]
                if cx - half_c - R["poly_enc_cont_nm"] < 0 or cx + half_c + R["poly_enc_cont_nm"] > W:
                    continue
                ppad = (min(cx - half_c - R["poly_enc_cont_nm"], gate_x[j] - pw // 2), gate_pad_y - R["poly_enc_cont_nm"],
                        max(cx + half_c + R["poly_enc_cont_nm"], gate_x[j] + pw // 2), gate_pad_y - R["poly_enc_cont_nm"] + pad_h)
                others_poly = [(gate_x[k] - pw // 2, ppad[1], gate_x[k] + pw // 2, ppad[3]) for k in range(N) if k not in mine] + poly_pads
                if any(_overlap_or_close(ppad, r, R["poly_space_nm"]) for r in others_poly):
                    continue
                if all(not _overlap_or_close(pad, r, R["m1_space_nm"]) for r in others):
                    placed = (j, cx, pad, ppad)
                    break
            if placed:
                break
        if placed is None:
            raise PlaceError(f"no Metal1-clean spot for the gate contact of {g} (neighbouring stubs/tracks in the way)")
        j, cx, pad, ppad = placed
        poly_pads.append(ppad)
        S.box("gatpoly", *ppad)
        S.box("cont", cx - half_c, gate_pad_y, cx + half_c, gate_pad_y + R["cont_nm"])
        S.box("metal1", *pad)
        m1.append((g, pad))
        S.labels.append(("metal1_label", cx, gate_pad_y + half_c, g))

    # Rails and output/rail labels.
    S.box("metal1", 0, -rail // 2, W, rail // 2)
    S.box("metal1", 0, H - rail // 2, W, H + rail // 2)
    # Tap Metal1: one patch per tap, covering its contacts and merged with its
    # rail, so a band pushed off the rail centre is still tied to the rail.
    for net, cy0, cy1 in taps:
        ry0, ry1 = (-rail // 2, rail // 2) if net == vss else (H - rail // 2, H + rail // 2)
        hang = max(mw // 2, half_c)  # cover the contacts even if M1 is narrower
        patch = (node_x[0] - hang, min(cy0, ry0), node_x[-1] + hang, max(cy1, ry1))
        for n2, r in m1:
            if n2 != net and _overlap_or_close(patch, r, R["m1_space_nm"]):
                raise PlaceError(f"{net} tap Metal1 is not {R['m1_space_nm']} nm clear of {n2}")
        S.box("metal1", *patch)
        m1.append((net, patch))
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
    return gn.sync_outputs(
        files, outdir, "*.gds", check=a.check, tool="gen_layouts", script="layout/gen_layouts.py",
        plural="GDS", out_of_date="GDS file(s)",
    )


if __name__ == "__main__":
    sys.exit(main())
