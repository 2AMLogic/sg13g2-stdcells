#!/usr/bin/env python3
"""PDK-independent static-CMOS SPICE netlist generator.

Usage: gen_netlists.py --config CONFIG.json [--out DIR] [--check]

Default mode (re)writes one `<cell>.spice` per config cell under --out
(default: `<config dir>/netlists`). `--check` regenerates in memory and exits
1 on any difference against the files on disk (changed, missing, or stray
`.spice` files). Output is deterministic (sorted, no timestamps), so the check
is a byte compare. Exit 2 means the config or a function string is invalid.

The engine holds no PDK constants: supply, geometry, unit widths, finger caps,
device model names, device-name prefixes and rail names all come from the
config's `process` object (contract in design/README.md).

Topology. Each output function is parsed into an AST (`!` `*` `^` `+`) and put
in negation normal form over literals; XOR is expanded to (a*!b)+(!a*b), and a
mux is written the same way with its select literal and complement. The parser
is strict: `*`, `+` and `^` may not be mixed at one nesting level without
parentheses, so no precedence between them is assumed. A literal that appears
inverted gets one shared unit inverter per cell. The remaining function g is
positive in its literals, so static CMOS applies directly: pull-down = g (AND
series, OR parallel), pull-up = the dual, stage output = !g.
  * output is `!g`            -> one inverting stage drives the pin;
  * output is `g` (non-inv.)  -> an inverting stage then an output inverter.

Sizing rule (numbers injected):
  * a device's width is unit * stage_scale * D, where D is the longest series
    path through that device in its own pull network (stack compensation);
  * stage_scale is the cell's drive for the stage that drives the pin; for the
    first stage of a non-inverting cell it is max(1, drive // 2); input
    inverters for inverted literals are unit size;
  * the width is the TOTAL device width, split into `ng` equal fingers, each
    at most finger_max_n / finger_max_p.
"""
import argparse
import difflib
import json
import pathlib
import re
import sys

TOKEN_RE = re.compile(r"\s*(?:([A-Za-z_][A-Za-z0-9_]*)|(.))")
OPS = {"*": "and", "+": "or", "^": "xor"}

PROCESS_KEYS = {
    "supply_v": (int, float),
    "l_nm": int,
    "unit_n_nm": int,
    "unit_p_nm": int,
    "finger_max_n": int,
    "finger_max_p": int,
    "nmos_model": str,
    "pmos_model": str,
    "nmos_prefix": str,
    "pmos_prefix": str,
    "vdd_net": str,
    "vss_net": str,
    "device_params": str,
}


# ---------------------------------------------------------------- parsing
def parse(expr):
    toks = []
    for m in TOKEN_RE.finditer(expr):
        if m.group(1):
            toks.append(("id", m.group(1)))
        elif m.group(2) and m.group(2).strip():
            toks.append((m.group(2), m.group(2)))
    pos = [0]

    def peek():
        return toks[pos[0]][0] if pos[0] < len(toks) else None

    def take(kind):
        if peek() != kind:
            raise ValueError(f"expected {kind!r} in {expr!r}")
        pos[0] += 1
        return toks[pos[0] - 1][1]

    def atom():
        if peek() == "!":
            take("!")
            return ("not", atom())
        if peek() == "(":
            take("(")
            e = chain()
            take(")")
            return e
        return ("var", take("id"))

    def chain():
        first = atom()
        sym = peek()
        if sym not in OPS:
            return first
        items = [first]
        while peek() == sym:
            take(sym)
            items.append(atom())
        if peek() in OPS:
            raise ValueError(f"mixed operators without parentheses in {expr!r}")
        return (OPS[sym], items)

    e = chain()
    if pos[0] != len(toks):
        raise ValueError(f"trailing input in {expr!r}")
    return e


def evaluate(e, env):
    k = e[0]
    if k == "var":
        return env[e[1]]
    if k == "not":
        return 1 - evaluate(e[1], env)
    if k == "and":
        return int(all(evaluate(x, env) for x in e[1]))
    if k == "or":
        return int(any(evaluate(x, env) for x in e[1]))
    r = 0
    for x in e[1]:
        r ^= evaluate(x, env)
    return r


def nnf(e, neg=False):
    """Negation normal form: ('lit', name, inverted) / ('and'|'or', [..])."""
    k = e[0]
    if k == "var":
        return ("lit", e[1], neg)
    if k == "not":
        return nnf(e[1], not neg)
    if k == "xor":
        a = e[1][0]
        for b in e[1][1:]:
            a = ("or", [("and", [a, ("not", b)]), ("and", [("not", a), b])])
        return nnf(a, neg)
    op = k if not neg else ("or" if k == "and" else "and")
    kids = [nnf(x, neg) for x in e[1]]
    flat = []
    for kid in kids:
        flat.extend(kid[1] if kid[0] == op else [kid])
    return flat[0] if len(flat) == 1 else (op, flat)


def split_output_inversion(e):
    neg = False
    while e[0] == "not":
        neg, e = not neg, e[1]
    return neg, e


# ---------------------------------------------------------------- networks
def depth_for(t, kind):
    """Series depth of a subtree in the n (AND series) or p (OR series) network."""
    if t[0] == "lit":
        return 1
    ds = [depth_for(x, kind) for x in t[1]]
    series = (t[0] == "and") == (kind == "n")
    return sum(ds) if series else max(ds)


class Cell:
    def __init__(self, name, proc):
        self.name = name
        self.proc = proc
        self.devices = []  # (kind, drain, gate, source, w_nm, ng)
        self.counter = 0

    def node(self, hint="n"):
        self.counter += 1
        return f"{hint}{self.counter}"

    def add(self, kind, d, g, s, w_nm):
        cap = self.proc["finger_max_n"] if kind == "n" else self.proc["finger_max_p"]
        ng = 1
        while w_nm % (10 * ng) or w_nm // ng > cap:
            ng += 1
            if ng > w_nm // GRID_NM:
                raise ValueError(f"no finger split of {w_nm} nm fits finger cap {cap} nm on the {GRID_NM} nm grid")
        self.devices.append((kind, d, g, s, w_nm, ng))

    def network(self, tree, kind, top, bot, signal, unit, scale, outside=0):
        """Emit tree between top and bot. `kind` n: AND=series; p: AND=parallel."""
        if tree[0] == "lit":
            self.add(kind, top, signal(tree), bot, unit * scale * (outside + 1))
            return
        series = (tree[0] == "and") == (kind == "n")
        kids = tree[1]
        if not series:
            for k in kids:
                self.network(k, kind, top, bot, signal, unit, scale, outside)
            return
        ds = [depth_for(k, kind) for k in kids]
        nodes = [top] + [self.node() for _ in kids[:-1]] + [bot]
        for i, k in enumerate(kids):
            others = sum(ds) - ds[i]
            self.network(k, kind, nodes[i], nodes[i + 1], signal, unit, scale, outside + others)

    def stage(self, g, out, signal, scale):
        p = self.proc
        self.network(g, "n", out, p["vss_net"], signal, p["unit_n_nm"], scale)
        self.network(g, "p", out, p["vdd_net"], signal, p["unit_p_nm"], scale)

    def inverter(self, a, y, scale):
        p = self.proc
        self.add("n", y, a, p["vss_net"], p["unit_n_nm"] * scale)
        self.add("p", y, a, p["vdd_net"], p["unit_p_nm"] * scale)


def build(cell, proc):
    c = Cell(cell["name"], proc)
    drive = cell["drive"]
    inverted = {}  # input pin -> inverted-literal node (shared per cell)

    def signal(lit):
        _, name, inv = lit
        if not inv:
            return name
        if name not in inverted:
            inverted[name] = f"{name}_b"
            c.inverter(name, inverted[name], 1)
        return inverted[name]

    for pin, fn in sorted(cell["outputs"].items()):
        out_neg, inner = split_output_inversion(parse(fn))
        g = nnf(inner)
        if out_neg:
            c.stage(g, pin, signal, drive)
        else:
            mid = f"{pin}_i"
            c.stage(g, mid, signal, max(1, drive // 2))
            c.inverter(mid, pin, drive)
    return c


# ---------------------------------------------------------------- config
GRID_NM = 10  # finger-width grid, nm


def validate(config):
    """Raise ValueError on a malformed config; return it unchanged."""
    proc = config.get("process")
    if not isinstance(proc, dict):
        raise ValueError("config needs a 'process' object")
    for key, typ in PROCESS_KEYS.items():
        if key not in proc or isinstance(proc[key], bool) or not isinstance(proc[key], typ):
            raise ValueError(f"process.{key} missing or wrong type")
    for key in ("l_nm", "unit_n_nm", "unit_p_nm", "finger_max_n", "finger_max_p"):
        if proc[key] <= 0:
            raise ValueError(f"process.{key} must be positive")
    for key in ("unit_n_nm", "unit_p_nm"):
        if proc[key] % GRID_NM:
            raise ValueError(f"process.{key} must be a multiple of the {GRID_NM} nm grid")
    try:
        proc["device_params"].format(w=1, l=1, ng=1)
    except (KeyError, IndexError, ValueError) as e:
        raise ValueError(f"process.device_params must use only {{w}} {{l}} {{ng}}: {e}")
    cells = config.get("cells")
    if not isinstance(cells, list) or not cells:
        raise ValueError("config needs a non-empty 'cells' list")
    seen = set()
    for c in cells:
        for key in ("name", "family", "drive", "inputs", "outputs"):
            if key not in c:
                raise ValueError(f"cell {c.get('name', '?')!r} missing {key!r}")
        if c["name"] in seen:
            raise ValueError(f"duplicate cell {c['name']!r}")
        seen.add(c["name"])
        if not isinstance(c["drive"], int) or c["drive"] < 1:
            raise ValueError(f"cell {c['name']!r}: drive must be an int >= 1")
        if not c["outputs"]:
            raise ValueError(f"cell {c['name']!r}: no outputs")
        for pin, fn in c["outputs"].items():
            used = set()
            _collect(parse(fn), used)
            if used - set(c["inputs"]):
                raise ValueError(f"cell {c['name']!r}: {pin} uses undeclared {sorted(used - set(c['inputs']))}")
    return config


def _collect(e, acc):
    if e[0] == "var":
        acc.add(e[1])
    elif e[0] == "not":
        _collect(e[1], acc)
    else:
        for x in e[1]:
            _collect(x, acc)


# ---------------------------------------------------------------- emission
def render(cell, proc, config_name):
    c = build(cell, proc)
    ins = cell["inputs"]
    outs = sorted(cell["outputs"])
    out = [
        f"* {cell['name']} -- generated by design/gen_netlists.py from {config_name}; do not edit.",
        f"* family {cell['family']}, drive {cell['drive']}, L={proc['l_nm']}n, supply {proc['supply_v']:.2f} V.",
    ]
    for p in outs:
        out.append(f"* {p} = {cell['outputs'][p]}")
    out.append(f".subckt {cell['name']} {' '.join(ins + outs)} {proc['vdd_net']} {proc['vss_net']}")
    nn = pp = 0
    for kind, d, g, s, w, ng in c.devices:
        if kind == "n":
            tag, model, bulk, nn = f"{proc['nmos_prefix']}{nn}", proc["nmos_model"], proc["vss_net"], nn + 1
        else:
            tag, model, bulk, pp = f"{proc['pmos_prefix']}{pp}", proc["pmos_model"], proc["vdd_net"], pp + 1
        params = proc["device_params"].format(w=f"{w}n", l=f"{proc['l_nm']}n", ng=ng)
        out.append(f"{tag} {d} {g} {s} {bulk} {model} {params}")
    out.append(f".ends {cell['name']}")
    return "\n".join(out) + "\n"


def generate(config, config_name="config"):
    validate(config)
    return {f"{c['name']}.spice": render(c, config["process"], config_name) for c in config["cells"]}


def check(files, outdir):
    errs = []
    on_disk = {p.name for p in outdir.glob("*.spice")} if outdir.is_dir() else set()
    for name, text in sorted(files.items()):
        path = outdir / name
        if name not in on_disk:
            errs.append(f"missing: {path}")
        elif path.read_text() != text:
            diff = difflib.unified_diff(
                path.read_text().splitlines(), text.splitlines(), f"{name} (committed)", f"{name} (regenerated)", lineterm="", n=0
            )
            errs.append(f"stale: {path}\n" + "\n".join(diff))
    for name in sorted(on_disk - set(files)):
        errs.append(f"stray: {outdir / name} is not in the config")
    return errs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", required=True, help="cell/process config JSON (see design/README.md)")
    ap.add_argument("--out", help="netlist directory (default: <config dir>/netlists)")
    ap.add_argument("--check", action="store_true", help="fail if committed netlists differ from regenerated ones")
    a = ap.parse_args(argv)
    cfg_path = pathlib.Path(a.config)
    try:
        files = generate(json.loads(cfg_path.read_text()), cfg_path.name)
    except (ValueError, OSError) as e:
        print(f"gen_netlists: invalid config {cfg_path}: {e}", file=sys.stderr)
        return 2
    outdir = pathlib.Path(a.out) if a.out else cfg_path.resolve().parent / "netlists"
    if a.check:
        errs = check(files, outdir)
        for e in errs:
            print(e, file=sys.stderr)
        if errs:
            print(f"gen_netlists: {len(errs)} netlist(s) out of date; run design/gen_netlists.py", file=sys.stderr)
            return 1
        print(f"gen_netlists: {len(files)} netlists fresh")
        return 0
    outdir.mkdir(parents=True, exist_ok=True)
    for stale in outdir.glob("*.spice"):
        if stale.name not in files:
            stale.unlink()
    for name, text in files.items():
        (outdir / name).write_text(text)
    print(f"gen_netlists: wrote {len(files)} netlists to {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
