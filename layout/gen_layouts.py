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
    and PMOS device on one gate net carry the same finger count, already
    reconciled by the netlist generator (the larger, same total width), so
    the layout consumes the netlist's fingering as-is;
  * a strip may hold devices of different drawn finger widths: it is one merged
    polygon whose outer edge is fixed (the NMOS strip grows up, the PMOS strip
    grows down) and whose channel-facing edge steps at the device boundary. A
    valley in that profile leaves a re-entrant notch whose opening in each
    drawn layer is the short run's width minus two overhangs; the
    diffusion/implant space-or-notch rules tolerate it only when the shapes
    merge (opening <= 0) or the opening clears that layer's space minimum, so
    a valley that falls into some layer's forbidden band is a named failure
    rather than a drawn shape;
  * the strips are ordered so each is one or more chains of devices sharing a
    source/drain net, and both orderings have the same gate-net sequence, so
    each poly column crosses both strips. Neighbouring chains are separated by
    a diffusion break: a gap whose width comes from the config's activ and
    PMOS-implant space rules plus the enclosures that overhang it. Both strips
    widen at the union of their break positions (a poly column must cross both
    strips at one x), so a strip whose chain continues through the other
    strip's break bridges the gap with its own diffusion while the strip that
    breaks parts there; the n-well always bridges (one well, one tap per
    cell). A net the break splits is re-joined in Metal1 on a channel track.
    Fewest breaks first, so a cell that places as single chains keeps its
    ordering and its committed GDS;
  * Metal1 only: VSS/VDD rails on the row edges, vertical stubs from diffusion
    contacts, at most `channel_tracks` horizontal tracks between the strips
    for nets that need joining, one gate contact pad per input. A gate whose
    net is also driven from diffusion (a multi-stage cell's internal net) is a
    terminal of that route, not a standalone pad: its pad grows into a riser
    down to the net's track, the track grows out to meet it, and nets that
    need a riser take the topmost tracks so a riser crosses no other track;
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

LAYER_KEYS = ("nwell", "activ", "gatpoly", "psd", "nsd", "cont", "metal1", "metal1_label")
RULE_KEYS = (
    "poly_width_nm", "poly_space_nm", "poly_endcap_nm", "poly_to_activ_nm", "cont_nm", "cont_space_nm",
    "activ_enc_cont_nm", "poly_enc_cont_nm", "m1_width_nm", "m1_space_nm",
    "rail_width_nm", "nwell_enc_pactiv_nm", "nwell_enc_nactiv_nm", "activ_space_nm",
    "sd_enc_activ_nm", "psd_space_nm", "nwell_space_nm",
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
    for k in LAYER_KEYS:
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


def _step_options(devs, i, tail):
    """The orientations device i can take given the previous chain's `tail`
    net (None before the first device): (left, right, starts_new_chain)."""
    d = devs[i]
    if tail is None:
        return [(d[2], d[4], False), (d[4], d[2], False)]
    out = []
    if tail in (d[2], d[4]):
        l, r = (d[2], d[4]) if tail == d[2] else (d[4], d[2])
        out.append((l, r, False))
    for l, r in ((d[2], d[4]), (d[4], d[2])):
        if l != tail:
            out.append((l, r, True))
    return out


def _tail(order, devs):
    """The net the last placed device ends on (where a continuation shares)."""
    i, l, r = order[-1]
    return end_net(l, r, devs[i][6])


def _pairings(ndevs, pdevs, budget, cap):
    """Every pairing of the two strips as
    (n_order, n_breaks, p_order, p_breaks) whose gate-net sequence matches
    position by position and whose union of break positions (a break in
    either strip shifts the columns of both, so the union is what costs
    width) has at most `budget` entries. Returns None if `cap` search steps
    are exhausted first: a bounded miss is a quality loss (a wider pairing
    still exists), never a correctness one, so the caller may fall back to
    the greedy pairing. At budget 0 the result set is exactly the single-chain
    model's, and the caller's key keeps that model's pick."""
    n = len(ndevs)
    gates = {}
    for i, d in enumerate(ndevs):
        gates.setdefault(d[3], ([], []))[0].append(i)
    for i, d in enumerate(pdevs):
        gates.setdefault(d[3], ([], []))[1].append(i)
    out = []
    steps = [0]

    def extend(k, nord, pord, used_n, used_p, nbrk, pbrk, break_count):
        steps[0] += 1
        if steps[0] > cap:
            raise _SearchExhausted
        if k == n:
            out.append((list(nord), tuple(nbrk), list(pord), tuple(pbrk)))
            return
        ntail = _tail(nord, ndevs) if nord else None
        ptail = _tail(pord, pdevs) if pord else None
        for g in sorted(gates):
            nis, pis = gates[g]
            for i in nis:
                if i in used_n:
                    continue
                for nopt in _step_options(ndevs, i, ntail):
                    for j in pis:
                        if j in used_p:
                            continue
                        for popt in _step_options(pdevs, j, ptail):
                            next_break_count = break_count + (nopt[2] or popt[2])
                            if next_break_count > budget:
                                continue
                            nord.append((i, nopt[0], nopt[1]))
                            pord.append((j, popt[0], popt[1]))
                            used_n.add(i)
                            used_p.add(j)
                            extend(k + 1, nord, pord, used_n, used_p,
                                   nbrk + (k,) if nopt[2] else nbrk,
                                   pbrk + (k,) if popt[2] else pbrk, next_break_count)
                            used_p.discard(j)
                            used_n.discard(i)
                            pord.pop()
                            nord.pop()

    try:
        extend(0, [], [], set(), set(), (), (), 0)
    except _SearchExhausted:
        return None
    return out


class _SearchExhausted(Exception):
    pass


def _greedy_pairing(ndevs, pdevs):
    """A deterministic first-fit pairing for strips too large to search: at
    each position the lowest gate net and device indices win, and each strip
    continues its chain where an orientation allows it, breaking otherwise.
    The caller has checked the two strips share one gate-net multiset, so
    each round both strips find the same lowest gate with an unused device
    and can pick from it independently: one first-fit choice per strip."""
    gates = {}
    for i, d in enumerate(ndevs):
        gates.setdefault(d[3], ([], []))[0].append(i)
    for i, d in enumerate(pdevs):
        gates.setdefault(d[3], ([], []))[1].append(i)

    def first_fit(devs, side, tail, used):
        """The lowest unused device of the lowest gate that has one, in the
        first orientation that continues the chain, or in the first
        orientation at all when only breaking ones remain."""
        for g in sorted(gates):
            live = [i for i in gates[g][side] if i not in used]
            if not live:
                continue
            breaking = None
            for i in live:
                for opt in _step_options(devs, i, tail):
                    if not opt[2]:
                        return i, opt[0], opt[1], False
                    if breaking is None:
                        breaking = (i, opt[0], opt[1])
            return (*breaking, True)

    nord, pord, nbrk, pbrk = [], [], (), ()
    used_n, used_p = set(), set()
    for k in range(len(ndevs)):
        i, nl, nr, nnew = first_fit(ndevs, 0, _tail(nord, ndevs) if nord else None, used_n)
        j, pl, pr, pnew = first_fit(pdevs, 1, _tail(pord, pdevs) if pord else None, used_p)
        nord.append((i, nl, nr))
        pord.append((j, pl, pr))
        used_n.add(i)
        used_p.add(j)
        nbrk = nbrk + (k,) if nnew else nbrk
        pbrk = pbrk + (k,) if pnew else pbrk
    return nord, nbrk, pord, pbrk


def order_strips(ndevs, pdevs):
    """Pick (n_order, n_breaks, p_order, p_breaks) with equal gate-net
    sequences and the fewest diffusion breaks, deterministically.

    A break in either strip shifts the columns after it in both -- every poly
    column crosses the two strips -- so what is minimized is the union of the
    two break sets, and the search deepens on exactly that union, one shared
    budget over both strips. With no breaks this is exactly the single-chain
    model, so a cell that places without breaks keeps the ordering (and the
    bytes) it already had: the zero-break candidates compare on the same
    (device indices, left nets) the single-chain picker used. Strips too
    large to search exhaustively (the step cap fires) fall back to a greedy
    first-fit pairing: a wider but still rule-legal ordering, never a silent
    refusal."""
    if len(ndevs) != len(pdevs):
        raise PlaceError(f"{len(ndevs)} NMOS vs {len(pdevs)} PMOS devices: gate columns cannot pair up")
    if sorted(d[3] for d in ndevs) != sorted(d[3] for d in pdevs):
        raise PlaceError("no NMOS/PMOS strip orderings share one gate-net sequence (gate nets cannot align in columns)")
    best = None
    for budget in range(min(len(ndevs), 9)):
        cand = _pairings(ndevs, pdevs, budget, cap=300_000)
        if cand is None:
            break
        # At the first successful budget, every candidate breaks the same number of columns.
        for a, abrk, b, bbrk in cand:
            key = (len(abrk) + len(bbrk),
                   tuple(i for i, _, _ in a), tuple(i for i, _, _ in b),
                   tuple(l for _, l, _ in a), tuple(l for _, l, _ in b),
                   abrk, bbrk)
            if best is None or key < best[0]:
                best = (key, a, abrk, b, bbrk)
        if best is not None:
            return best[1], best[2], best[3], best[4]
    return _greedy_pairing(ndevs, pdevs)


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
    """A device's fingered geometry, for failure messages.

    The netlist generator has already folded devices on a gate net to the
    gate's shared finger count (design/gen_netlists.py), so the drawn
    fingering is the netlist's own: one geometry, named once."""
    return (f"{d[1].upper()}MOS on gate {d[3]} ({d[6]} finger{'' if d[6] == 1 else 's'} "
            f"of {d[5] // d[6]} nm)")


def _strip_profile(order, devs_, cols_):
    """Drawn finger width per column: the strip's height profile."""
    return [d[5] // d[6] for d in (_dev_at(order, devs_, cols_, c) for c in range(len(cols_)))]


def _runs(prof, brk=()):
    """Maximal spans of equal-height columns as [first column, last column,
    height], also cut at the column boundaries in `brk`: the drawing emits one
    rectangle per span, and a break boundary always ends one."""
    out = []
    for c, h in enumerate(prof):
        if out and out[-1][2] == h and out[-1][1] == c - 1 and c not in brk:
            out[-1][1] = c
        else:
            out.append([c, c, h])
    return out


def _notch_violation(prof, pitch, layers, brk=(), edge=None, bridging=frozenset()):
    """The first rule a valley of `prof` would break, or None.

    `layers` maps a drawn layer name to its (hang_nm, threshold_nm): each of
    that layer's rectangles reaches hang_nm past the node columns it spans, so
    a short run sitting between its two taller neighbours leaves an opening of
    k * pitch - 2 * hang in it, where k counts the columns between those
    neighbours. The opening is legal when it is <= 0 (the neighbours'
    rectangles overlap and the layer merges, leaving no notch there at all) or
    >= threshold; strictly between is the layer's forbidden band. Legality is
    therefore non-monotone in the pitch. Per strip the caller passes exactly
    the layers drawn there that have a space-or-notch rule: activ on both
    strips, psd and the n-well on the PMOS strip only (the sg13g2 deck models
    no nsd space rule, so the NMOS strip's implant has nothing to violate).

    `brk` names this strip's own diffusion-break boundaries. A layer that
    parts at a break is spaced by the break's own rule-derived width, so a
    valley whose span holds a break is legal by construction for it and is
    skipped; a layer in `bridging` (the n-well: the drawing merges it across
    the break) is still measured, with `edge` -- the caller's x-position
    function of (boundary, hang, right-edge?, layer) -- supplying the real
    gap geometry in place of the k * pitch term. Without `brk` (a strip that
    does not break) the verdict is the original contiguous one.
    Returns (layer, opening, threshold, (first column, last column)) for the
    first valley and layer in the forbidden band, else None."""
    runs = _runs(prof, brk)
    for i, (c0, c1, h) in enumerate(runs):
        left = [r for r in runs[:i] if r[2] > h]
        right = [r for r in runs[i + 1:] if r[2] > h]
        if not left or not right:
            continue  # monotone terrain or a peak: a single concave corner, no notch
        spans_break = any(left[-1][1] < b <= right[0][0] for b in brk)
        for layer, (hang, thr) in layers.items():
            if spans_break and layer not in bridging:
                continue
            if edge is None:
                opening = (right[0][0] - left[-1][1] - 1) * pitch - 2 * hang
            else:
                opening = (edge(right[0][0], hang, False, layer)
                           - edge(left[-1][1] + 1, hang, True, layer))
            if 0 < opening < thr:
                return layer, opening, thr, (c0, c1)
    return None


def layout_cell(cell, proc, lay):
    """Return (Shapes, width_nm, height_nm) for one config cell, or raise PlaceError."""
    R, P = lay["rules"], lay["gate_pitch_nm"]
    H = lay["row_height_nm"]
    c = gn.build(cell, proc)
    # Finger counts come folded from the netlist generator: a poly column
    # crosses both strips, so gn.build has already reconciled the NMOS and
    # PMOS device on one gate net to the gate's shared count (same total
    # width; a width with no equal split on the grid is refused there, naming
    # the gate -- the one divisibility error).
    grid = gn.grid_nm(proc)
    devs = [(i,) + d for i, d in enumerate(c.devices)]  # (i, kind, drain, gate, source, w, ng)
    ndevs = [(i, k, d, g, s, w, ng) for (i, k, d, g, s, w, ng) in devs if k == "n"]
    pdevs = [(i, k, d, g, s, w, ng) for (i, k, d, g, s, w, ng) in devs if k == "p"]
    nord, nbrk, pord, pbrk = order_strips(ndevs, pdevs)
    cols = [(j, k) for j, (i, _, _) in enumerate(nord) for k in range(ndevs[i][6])]  # column -> (position in order, finger)
    pcols = [(j, k) for j, (i, _, _) in enumerate(pord) for k in range(pdevs[i][6])]
    N = len(cols)
    if N != len(pcols):
        raise PlaceError("NMOS and PMOS strips have different column counts")
    # Height profile: devices of different drawn finger widths share a strip, so
    # the strip's channel-facing edge steps from column to column. A valley in
    # it is a re-entrant notch in the merged activ/implant/well polygon, and the
    # space rules there are space-*or-notch* rules: legal only when the shapes
    # merge or the notch opening clears the layer's minimum. Refuse only a
    # valley that falls into some layer's forbidden band, and name the rule it
    # would break; a monotone step or a fully admitted valley is drawn.
    nprof = _strip_profile(nord, ndevs, cols)
    pprof = _strip_profile(pord, pdevs, pcols)
    half_c = R["cont_nm"] // 2
    act_hang = half_c + R["activ_enc_cont_nm"]  # diffusion extent beyond a node-centre
    sd = R["sd_enc_activ_nm"]
    # Diffusion breaks: the column boundaries where a strip's chain ends. Both
    # strips shift by one gap at the union of the two sets (a poly column
    # crosses both strips, so its x must be the same in each). The gap width is
    # rule-derived: activ and the PMOS implant must clear their space minimums
    # across it, with the hang each layer reaches past its node columns. The
    # n-well needs no width from its own rule: the drawing bridges the gap with
    # it (one well, one tap), instead of parting it into wells that would each
    # need a tie. Rounded up to a whole number of gate pitches: node columns are
    # the routing grid (issue #225), so every column after a break must stay on
    # it -- a break cell's post-break pins would otherwise leave the row-4 grid.
    def brk_cols(brk, order, devs_):
        out, j = set(), 0
        for k, (i, _, _) in enumerate(order):
            if k in brk:
                out.add(j)
            j += devs_[i][6]
        return out

    nbrk_c, pbrk_c = brk_cols(nbrk, nord, ndevs), brk_cols(pbrk, pord, pdevs)
    ubrk = sorted(nbrk_c | pbrk_c)
    uset = set(ubrk)
    brk_w = max(R["activ_space_nm"] + 2 * act_hang,
                R["psd_space_nm"] + 2 * (act_hang + sd))
    brk_w = -(-brk_w // P) * P
    # Phase (issue #225): diffusion nodes sit on the routing grid (x = (j + 1) * P,
    # plus one gap per break to the left) and the gates a half pitch between them,
    # so every Metal1 stub on a node, and the rail taps, is on a grid column.
    bx = [P]  # x of node column boundary j; a gap is inserted after a break
    for j in range(N):
        bx.append(bx[j] + P + (brk_w if j in uset else 0))
    W = bx[N] + P
    rail = R["rail_width_nm"]
    vdd, vss = proc["vdd_net"], proc["vss_net"]
    gate_x = [bx[c] + (brk_w if c in uset else 0) + P // 2 for c in range(N)]

    def strip_edges(brkc):
        """Layer-rectangle x edges at column boundaries for one strip: a layer
        rectangle reaches `hang` past its run's node column. At this strip's
        own break each side hangs off its own node (activ and the implants
        part there, by the gap width); at a break of the *other* strip -- a
        phantom break, this strip's chain continues -- both sides reach to the
        gap's midpoint so the rectangles still merge across it. The n-well
        bridges even this strip's own break, keeping one well per cell."""
        def edge(b, hang, right, layer=False):
            bridge = layer == "nwell"
            if b in brkc and not bridge:
                pos = bx[b] + (0 if right else brk_w)
            elif b in uset:
                pos = bx[b] + brk_w // 2
            else:
                pos = bx[b]
            return pos + hang if right else pos - hang
        return edge

    notch_layers = {
        "n": {"activ": (act_hang, R["activ_space_nm"])},
        "p": {"activ": (act_hang, R["activ_space_nm"]),
              "psd": (act_hang + sd, R["psd_space_nm"]),
              "nwell": (act_hang + R["nwell_enc_pactiv_nm"], R["nwell_space_nm"])},
    }
    for kind, order, devs_, cols_, prof, brkc in (
            ("N", nord, ndevs, cols, nprof, nbrk_c), ("P", pord, pdevs, pcols, pprof, pbrk_c)):
        hit = _notch_violation(prof, P, notch_layers[kind.lower()], brk=brkc,
                               edge=strip_edges(brkc), bridging=frozenset(("nwell",)))
        if hit:
            layer, opening, thr, (c0, c1) = hit
            raise PlaceError(
                f"{kind}MOS strip height profile {prof} nm notches over columns {c0}..{c1}, leaving an "
                f"opening of {opening} nm in {layer} between the taller runs, under the {thr} nm {layer}.space "
                f"minimum (space-or-notch rule); the short device is {_dev_desc(_dev_at(order, devs_, cols_, c0))}")
    n_y0 = lay["n_diff_y0_nm"]
    p_y1 = H - lay["p_diff_top_margin_nm"]
    # Each strip's outer edge is fixed; the channel-facing one steps. Every
    # channel check below reads the *tallest* run, so a short device in the strip
    # cannot loosen a clearance by accident.
    n_y1 = n_y0 + max(nprof)
    p_y0 = p_y1 - max(pprof)
    if p_y0 <= n_y1:
        raise PlaceError(f"row height {H} nm leaves no channel between the NMOS and PMOS strips")
    if P // 2 - R["poly_width_nm"] // 2 < half_c:
        raise PlaceError("gate pitch too small for a contact between two gates")
    S = Shapes()

    # Each strip's diffusion nodes as (net, x, chain, boundary, side): the
    # boundary is the node's column boundary, and side is 'L' or 'R' on the two
    # nodes a this-strip break leaves where one shared node used to be (the
    # column across the gap belongs to the other chain); None elsewhere. A
    # device's F fingers append F boundaries after the head one, alternating
    # l, r, l, ...; a chain shares its boundary nodes, so only a break appends
    # the next chain's head node.
    def strip_nodes(order, devs_, brk):
        brkc = brk_cols(brk, order, devs_)
        out = []
        chain = 0
        jc = 0  # boundary index at the current device's left
        out.append((order[0][1], bx[0], chain, 0, None))
        for k, (i, l, r) in enumerate(order):
            F = devs_[i][6]
            if k in brk:
                chain += 1
                out.append((l, bx[jc] + brk_w, chain, jc, "R"))
            for f in range(1, F + 1):
                b = jc + f
                out.append((l if f % 2 == 0 else r, bx[b], chain, b, "L" if b in brkc else None))
            jc += F
        return out

    nnodes, pnodes = strip_nodes(nord, ndevs, nbrk), strip_nodes(pord, pdevs, pbrk)
    node_xs = sorted({x for nodes_ in (nnodes, pnodes) for (_, x, _, _, _) in nodes_})

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

    # Diffusion, implants, well: one rectangle per run of equal-height columns,
    # cut at this strip's own breaks. Neighbouring runs each reach `act_hang`
    # past the node column they share, so they overlap there and merge into one
    # stepped polygon; the implants and the n-well follow the same step with
    # their own overhang, so one rectangle over the tallest run would
    # over-enclose the short ones and can break the implant space rule against
    # a neighbouring cell. Across a break the activ and implant rectangles part
    # by the gap width (each hanging off its own node); across a phantom break
    # -- the other strip's break, this strip's chain continues -- and for the
    # n-well at any break, they reach to the gap's midpoint and merge.
    ax0, ax1 = bx[0] - act_hang, bx[N] + act_hang
    nwe = R["nwell_enc_pactiv_nm"]
    for strip, prof, brkc in (("n", nprof, nbrk_c), ("p", pprof, pbrk_c)):
        edge = strip_edges(brkc)
        for c0, c1, h in _runs(prof, brkc):
            if strip == "n":
                S.box("activ", edge(c0, act_hang, False), n_y0, edge(c1 + 1, act_hang, True), n_y0 + h)
                S.box("nsd", edge(c0, act_hang + sd, False), n_y0 - sd, edge(c1 + 1, act_hang + sd, True), n_y0 + h + sd)
            else:
                S.box("activ", edge(c0, act_hang, False), p_y1 - h, edge(c1 + 1, act_hang, True), p_y1)
                S.box("psd", edge(c0, act_hang + sd, False), p_y1 - h - sd, edge(c1 + 1, act_hang + sd, True), p_y1 + sd)
                S.box("nwell", edge(c0, act_hang + nwe, False, "nwell"), p_y1 - h - nwe,
                      edge(c1 + 1, act_hang + nwe, True, "nwell"), well_y1 + R["nwell_enc_nactiv_nm"])

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
        for x in node_xs:
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

    net_m1 = {}  # net -> list of (rect, side): one per diffusion node
    for strip, nodes_, order, devs_, cols_, prof, side in (
            ("n", nnodes, nord, ndevs, cols, nprof, "below"),
            ("p", pnodes, pord, pdevs, pcols, pprof, "above")):
        for net, x, chain, b, bside in nodes_:
            # The node's contact stack has to fit inside every neighbouring
            # column of its own chain, so the contact floor is a per-device
            # limit: a device folded short cannot hold a contact even where its
            # taller neighbour could. Sizing from the shorter column also names
            # that device in the failure.
            cs = [cc for cc in (b - 1 if bside != "R" else -1, b if bside != "L" else N)
                  if 0 <= cc < N]
            c = min(cs, key=lambda cc: prof[cc])
            h = prof[c]
            y0, y1 = (n_y0, n_y0 + h) if strip == "n" else (p_y1 - h, p_y1)
            cys = contact_ys(y0, y1, _dev_desc(_dev_at(order, devs_, cols_, c)))
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

    # A gate pad whose net is also driven from diffusion (a multi-stage cell's
    # internal net, e.g. buf's Y_i) must land on that net's route: a labelled
    # island instead is read by extraction as a split net (issue #201).
    driven = {g for g in gates if g in net_m1}
    # Horizontal tracks for signal nets with more than one attachment: every
    # diffusion node is its own island (the channels separate them, so the
    # merged strip polygon does not tie a net's repeated nodes), and each
    # strip is separate diffusion anyway -- so a net attached more than once
    # needs its Metal1 join on a channel track. That includes a net the break
    # splits across chains; the channel-track budget is the named limit it is.
    # A net that needs a gate-pad riser takes the topmost track: the riser runs
    # from the track up to the channel-top pad and must not cross another
    # net's track, so every riser net sits above every non-riser net.
    tracks = {}
    need = [n for n, att in net_m1.items() if n not in (vss, vdd) and len(att) > 1]
    need.sort(key=lambda net: (net in driven, net))
    if len(need) > lay["channel_tracks"]:
        raise PlaceError(f"nets {need} need {len(need)} channel tracks, config allows {lay['channel_tracks']}")
    # Tracks sit at the channel bottom; gate contact pads sit at the channel top.
    track_base = n_y1 - R["activ_enc_cont_nm"] + R["m1_space_nm"]  # clear the NMOS contact stubs
    for t, net in enumerate(need):
        y0 = track_base + t * (mw + R["m1_space_nm"])
        if y0 + mw + R["m1_space_nm"] > gate_pad_y:
            raise PlaceError(f"channel too short for track {t + 1} of net {net}")
        tracks[net] = (y0, y0 + mw)
    trackless = sorted(n for n in driven if n not in tracks)
    if trackless:
        raise PlaceError(f"gate net(s) {trackless} driven from a single diffusion node: "
                         "no channel track to land the gate pad on")
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
    # the first finger/side whose M1 and poly neighbours leave room. A driven
    # gate's Metal1 is a riser from its net's track up to the pad plus the track
    # grown out to meet it, so the pad is a terminal of its net's route
    # (issue #201); an input gate keeps the standalone pad.
    ch_lo, ch_hi = n_y1, p_y0
    grid_ys = sorted((y for y in range((ch_lo // P + 1) * P, ch_hi, P)),
                     key=lambda y: abs(y - (gate_pad_y + half_c)))
    # Driven gates first: their riser has the least freedom, and an input pad's
    # bar must not take the column it needs.
    for pos, g in sorted(enumerate(gates), key=lambda t: (t[1] not in driven, t[0])):
        mine = dev_cols[pos]
        placed = None
        for j in mine:
            for sgn in (-1, 1):
                cx = gate_x[j] + sgn * (R["poly_enc_cont_nm"] + half_c)
                gx_node = gate_x[j] + sgn * (P // 2)  # the node column beside the pad: on the grid
                others = [r for n2, r in m1 if n2 != g]
                if cx - half_c - R["poly_enc_cont_nm"] < 0 or cx + half_c + R["poly_enc_cont_nm"] > W:
                    continue
                ppad = (min(cx - half_c - R["poly_enc_cont_nm"], gate_x[j] - pw // 2), gate_pad_y - R["poly_enc_cont_nm"],
                        max(cx + half_c + R["poly_enc_cont_nm"], gate_x[j] + pw // 2), gate_pad_y - R["poly_enc_cont_nm"] + pad_h)
                # The pad merges with its own column's stripe, but the space
                # rule is blind to nets, so every *other* stripe -- including
                # the other fingers of the same gate, which the pad only sits
                # 55 nm from at the shipped pitch -- must be poly_space clear.
                others_poly = [(gate_x[k] - pw // 2, ppad[1], gate_x[k] + pw // 2, ppad[3])
                               for k in range(N) if k != j] + poly_pads
                if any(_overlap_or_close(ppad, r, R["poly_space_nm"]) for r in others_poly):
                    continue
                pad_rect = (cx - mw // 2, gate_pad_y, cx + mw // 2, gate_pad_y + R["cont_nm"])
                # An input pin's label sits on a grid point (node column x, a grid
                # y in the channel) that the pad's Metal1 reaches by a vertical
                # bar on the node column, just long enough. A driven gate's
                # riser runs from its net's track up to the pad, so the pad
                # stays a terminal of the net's route (issue #201).
                if g in driven:
                    # An internal net's gate label is not a pin: its riser stays
                    # on the pad's own column and the label on the pad centre.
                    # pad_rect is kept alongside the riser on purpose: when the
                    # track lands above the pad (ty0 > gate_pad_y) the riser box
                    # is y-inverted and does not cover it; otherwise the riser
                    # contains pad_rect exactly and the box is a harmless duplicate.
                    ty0, ty1 = tracks[g]
                    xs = [(r[0] + r[2]) // 2 for r, _ in net_m1[g]]
                    cands = [(None, [pad_rect,
                                     (cx - mw // 2, ty0, cx + mw // 2, gate_pad_y + R["cont_nm"]),
                                     (min(xs + [cx]) - mw // 2, ty0, max(xs + [cx]) + mw // 2, ty1)])]
                else:
                    # The bar overshoots the grid y by `e`, as much as the
                    # neighbouring Metal1 allows (down to the grid y itself).
                    bridge = (min(cx, gx_node) - mw // 2, gate_pad_y, max(cx, gx_node) + mw // 2, gate_pad_y + R["cont_nm"])
                    cands = [(gy, [bridge,
                                   (gx_node - mw // 2, min(gate_pad_y, gy - e),
                                    gx_node + mw // 2, max(gate_pad_y + R["cont_nm"], gy + e))])
                             for gy in grid_ys for e in range(mw // 2, -1, -grid)]
                    # Crowded channel (a cell outside the shipped set): the
                    # compact pad, labelled at its centre and so off the grid.
                    # The row-4 test names any shipped cell that lands here.
                    cands.append((None, [pad_rect]))
                for gy, pieces in cands:
                    if all(not _overlap_or_close(piece, r, R["m1_space_nm"]) for piece in pieces for r in others):
                        placed = (j, cx, pieces, ppad, gx_node, gy)
                        break
                if placed:
                    break
            if placed:
                break
        if placed is None:
            if g in driven:
                raise PlaceError(f"no Metal1-clean riser from the track of internal net {g} up to its gate pad "
                                 "(neighbouring stubs/tracks in the way)")
            raise PlaceError(f"no Metal1-clean spot for the gate contact of {g} on a grid point (neighbouring stubs/tracks in the way)")
        j, cx, pieces, ppad, lx, ly = placed
        if ly is None:
            lx, ly = cx, gate_pad_y + half_c
        poly_pads.append(ppad)
        S.box("gatpoly", *ppad)
        S.box("cont", cx - half_c, gate_pad_y, cx + half_c, gate_pad_y + R["cont_nm"])
        for piece in pieces:
            S.box("metal1", *piece)
            m1.append((g, piece))
        S.labels.append(("metal1_label", lx, ly, g))

    # Rails and output/rail labels.
    S.box("metal1", 0, -rail // 2, W, rail // 2)
    S.box("metal1", 0, H - rail // 2, W, H + rail // 2)
    # Tap Metal1: one patch per tap, covering its contacts and merged with its
    # rail, so a band pushed off the rail centre is still tied to the rail.
    for net, cy0, cy1 in taps:
        ry0, ry1 = (-rail // 2, rail // 2) if net == vss else (H - rail // 2, H + rail // 2)
        hang = max(mw // 2, half_c)  # cover the contacts even if M1 is narrower
        patch = (node_xs[0] - hang, min(cy0, ry0), node_xs[-1] + hang, max(cy1, ry1))
        for n2, r in m1:
            if n2 != net and _overlap_or_close(patch, r, R["m1_space_nm"]):
                raise PlaceError(f"{net} tap Metal1 is not {R['m1_space_nm']} nm clear of {n2}")
        S.box("metal1", *patch)
        m1.append((net, patch))
    S.labels.append(("metal1_label", bx[0], 0, vss))
    S.labels.append(("metal1_label", bx[0], H, vdd))
    for pin in sorted(cell["outputs"]):
        if pin not in net_m1:
            raise PlaceError(f"output {pin} has no diffusion node")
        # A grid point of the output's final Metal1 (stubs grown to the track
        # included): its node column is on the grid in x, so only y needs one.
        pts = [(x, y, min(x - r[0], r[2] - x, y - r[1], r[3] - y))
               for n2, r in m1 if n2 == pin
               for x in range(-(-r[0] // P) * P, r[2] + 1, P) for y in range(-(-r[1] // P) * P, r[3] + 1, P)
               if r[0] <= x <= r[2] and r[1] <= y <= r[3]]
        if not pts:
            raise PlaceError(f"output {pin} has no grid point on its Metal1")
        x, y, _ = max(pts, key=lambda t: (t[2], -t[1], -t[0]))
        S.labels.append(("metal1_label", x, y, pin))
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
