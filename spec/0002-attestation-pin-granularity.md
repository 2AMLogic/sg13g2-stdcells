# 0002 — Attestation pin granularity

Status: proposed

Issue: #110. This record is ratified by its own PR being reviewed and merged with
both reviewer keys (`ratification/ee-key/`, `ratification/market-key/`), neither
held by an author of the PR or the design. The `Status:` line above is flipped to
`RATIFIED` in that PR after both keys post and before merge (`CLAUDE.md`).

## Question

Should a `klt signoff --attest` envelope bind every inventory input by byte hash,
when the check that accompanies the input is a predicate whose truth does not
depend on the file's bytes? While the drift was silent this was a hygiene
question; PR #112's CI gate (`check_attestations.py`, merged in `206dac1`) makes
pin drift loud and **blocking**, so the cost of a coarser-than-needed pin is now
paid on every ordinary edit to a pinned file.

## Measured state at this PR's head

Dated snapshot, 2026-11-15, measured at `206dac144633` (the worktree head this
record was written in). The delivering PR changes only `spec/`, so every hash
below is also the hash at this PR's head. Earlier snapshots in #110's body
measured at `ef9e57f` (four drifted member pins) and at its head at filing
(two); both are history, not current state — re-measured here, not copied
forward.

### Envelope member pins vs the tree

```
$ python3 manifests/check_attestations.py
check_attestations: 19 recorded hashes across 4 envelopes all match the tree
(exit 0)
```

All 16 envelope member pins match the tree at this head — the checker counts 19
recorded hashes because each envelope also records its inventory file (items 1,
9 and 10 add `manifests/inventories/<item>.json`; item 2's provenance input
list duplicates its own pins), and the checker deduplicates. PR #112's
re-attestations cleared the member drift its curation measured; the gate is
green.

### Committed grade vs fresh grade

```
$ klt signoff --manifest manifests/sg13g2-stdcells.json \
      --check manifests/signoff-report.json
status: drifted                                            (exit 3; read-only)
  items.0.status    committed: met    fresh: unmet
  items.0.reason    fresh: stale_evidence
  t1_met_count      committed: 11     fresh: 10
```

`main` overstates its own T1 count by **one** item today: the committed
`manifests/signoff-report.txt:6` reads `T1: 11/22 items met`; a fresh grade of
the same tree reads 10, with item 1 (`Design sources`) flipping `met -> unmet`,
reason `stale_evidence`. The cause is the report↔evidence binding, not an
envelope↔tree pin: item 1's envelope was re-minted in `5e419cc` after the last
report regeneration (`fdedc4c`), and #105's edits to `design/gen_netlists.py`
and `layout/example_config.json` moved two members of its input set. Regenerating
the report follows whoever re-mints and is out of scope for this record's issue
(#110); it is recorded here because it is a third instance of the same shape —
the report pins the envelope's input digest, so *the re-mint itself is churn
that re-stales a pin*. Even a byte-pinned system maintained perfectly leaves
the committed grade overstated between the re-mint and the report regeneration.

### Churn history of one predicate pin

`README.md`'s item 10 pin was observed stale at **three distinct (committed,
tree) hash pairs** during this issue's lifetime (one per 2026-11-15 observation
point: the filing, the body's `ef9e57f` table, and the champion's re-measure),
with `fresh_status: pass` every time it was checked — every one of those drifts
came from an ordinary README edit, and every one invalidated an attestation
that was still true. The pin currently matches at a fourth pair.

## Classification of every pinned path

Two classes:

- **content-bearing** — the bytes *are* the evidence: the accompanying check
  compares those exact bytes against a generator's output (or the artifact was
  itself measured). An edit to the file is exactly what must stale the
  attestation.
- **predicate-bearing** — the check verifies a property whose truth does not
  depend on the file's exact bytes: an existence/shape/hygiene predicate over a
  repo document, a recognized-licence check, or an input whose *output* the
  check verifies. The byte pin asserts strictly more than the check verifies.

All 16 member pins across the four envelopes
(`manifests/envelopes/{item1.analog,item2.analog,item9.digital,item10}.attest.json`),
hashed at `206dac144633` with

```bash
for f in manifests/envelopes/*.json; do python3 -I -c "
import json,sys,hashlib,pathlib
d=json.load(open(sys.argv[1]))
for c in d['attestation']['checks']:
    p,h=c.get('path'),c.get('content_hash')
    if p and h:
        fresh='sha256:'+hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
        print(('MATCH' if fresh==h else 'DRIFT'), p, h[:24], fresh[:24])
" "$f"; done
```

(the two commands this section and the previous one summarize are #110's own
implementation guidance, re-run at this head).

| envelope | pinned path | pin (sha256:…) | class | why |
|---|---|---|---|---|
| item1.analog | `design/gen_netlists.py` | `758eab5f13e4853cd` | predicate-bearing | the evidence is the relation generator+config → committed netlists (`gen_netlists.py --check` passes iff the netlists match its output); #105's edit to the generator left all four netlists matching while staling the pin |
| item1.analog | `layout/example_config.json` | `a9431e088eebbca9b` | predicate-bearing | same relation, as the config input to it |
| item1.analog | `layout/lvs/netlists/sg13g2_inv_1.spice` | `65aa1e3c6e10bc76c` | content-bearing | the attested design source itself; the check regenerates and compares these bytes |
| item1.analog | `layout/lvs/netlists/sg13g2_inv_2.spice` | `da42c9d5d4790a03f` | content-bearing | as above |
| item1.analog | `layout/lvs/netlists/sg13g2_inv_4.spice` | `f350f0e6257207c94` | content-bearing | as above |
| item1.analog | `layout/lvs/netlists/sg13g2_nand2_1.spice` | `1fc9770ab7c6d2a87` | content-bearing | as above |
| item2.analog | `layout/gds/sg13g2_inv_1.gds` | `91c226f6336a7fb8e` | content-bearing | the attested layout artifact; the DRC/LVS evidence was produced from these bytes |
| item2.analog | `layout/gds/sg13g2_inv_2.gds` | `b7f96fccc399bc987` | content-bearing | as above |
| item2.analog | `layout/gds/sg13g2_inv_4.gds` | `e6d2fc1fb4b6a0a0f` | content-bearing | as above |
| item2.analog | `layout/gds/sg13g2_nand2_1.gds` | `9bef3c012a6e531bb` | content-bearing | as above |
| item9.digital | `verification/test_add8.py` | `095bf6541170ee425` | predicate-bearing | the evidence is behavioral — the declared testbench passes on this tree (the cold start runs it; cocotb fails on a failing test) — not the file's bytes; a formatting edit stales the pin and changes nothing verified |
| item9.digital | `verification/Makefile` | `c9e504120822d2c10` | predicate-bearing | drives the same behavioral check |
| item9.digital | `verification/cold_start.sh` | `7bf48dc164e2f6fc6` | predicate-bearing | provisions and runs it |
| item10 | `.github/workflows/ci.yml` | `77d86e39b749ba4ec` | predicate-bearing | none of the inventory's three checks (`netlists-fresh`, `layouts-fresh`, `flow-evidence-accepts-committed-record`) reads it; the envelope names it via a path-bearing hygiene check (the workflow exists and names the gates) plus the hash |
| item10 | `README.md` | `13f8c6ec4f089bf5f` | predicate-bearing | hygiene predicate (exists, passes the hygiene gate); the highest-churn pin, stale at three observed hash pairs during this issue's lifetime, `fresh_status: pass` every time |
| item10 | `LICENSE` | `cfc7749b96f63bd31` | predicate-bearing | recognized-licence predicate; near-frozen in practice, so the churn cost is low — but the pin still over-asserts |

Count: **8 predicate-bearing, 8 content-bearing** — even, and the
content-bearing set is exactly the generated artifacts (4 LVS netlists, 4 GDS).
For item 9 the nuance is honest: a *substantive* testbench edit does change what
is attested — but that is caught by re-running the check (which is the
attestation), not by the byte pin; the pin's extra assertion is the formatting.

## Policy

**Recommended: (b) — pin only content-bearing paths; record predicate-bearing
inputs without a hash** (name plus the check that verifies them). This is the
only option that stops the churn instead of scheduling it: a predicate-bearing
edit stops touching the envelope at all, and a re-mint is needed exactly when
the evidence's bytes — the generated artifacts — actually moved, which is also
when the checks themselves flag it. It needs a schema change in
`klt signoff --attest` (the envelope is the tool's output, never hand-edited),
filed as 2AMLogic/klayout-tools#5831.

Rejected alternatives, one line each:

- **(a) keep byte pins everywhere and re-mint on churn** (the post-#112 status
  quo) — rejected as the target policy: every re-mint re-runs predicates that
  measurably still pass and changes nothing verified; `README.md` alone drifted
  three times during this issue's lifetime.
- **(c) automate the re-mint on merge** — rejected: `.github/workflows/ci.yml`
  is tool-free by constraint (`ci.yml:1`), so the automaton must live off-CI and
  would mint evidence on a trigger with no one reviewing the re-run; it also
  hides the moment the envelope changes behind machinery.
- **shrink the item 10 inventory to stop naming the churny files** — rejected:
  that trades away the predicate itself (the attestation would stop claiming
  README/workflow hygiene at all), which is worse than re-minting for them.
- **hand-edit the committed envelopes to drop the hashes** — rejected: the
  envelope is `klt signoff --attest` output, generated never hand-edited, so the
  change can only come from the inventory schema upstream (#5831).

### Interim, until the upstream schema lands

(a) remains the operative practice — a tool-gap hold, not an endorsement; this
record changes no manifest and relaxes nothing. What #112 changed is that the
churn is no longer *silent*: the gate names the stale envelope on every PR that
touches a pinned path.

## CI consequence of the recommendation

`.github/workflows/ci.yml:1` reads `# Tool-free CI: stdlib Python + pytest + jq
only. No klt, ngspice or PDK.`, and #112's gate step
(`./check-ci.sh attestations` → `python3 manifests/check_attestations.py`)
compares recorded hashes to the tree. Under the interim (a):

- **Trigger**: any commit editing a pinned path turns the gate red on that PR;
  the checker's output names the stale envelope.
- **Who re-mints**: anyone on a klt-capable host (the sweep hosts have `klt`;
  the CI runner never will). Mechanically: `klt signoff --attest <item>
  --inventory <inventory> --check <envelope>` for each affected envelope, then
  regenerate `manifests/signoff-report.{json,txt}` — the report regeneration
  must follow the re-mint, or the committed grade stays overstated (item 1
  today, measured above).
- **What turns `main` red meanwhile**: after a merge that moved a pinned path,
  `main`'s own tree fails the gate until a klt-capable re-mint lands; a one-line
  README typo keeps `main` red until then. No CI job can clear it — the runner
  has no `klt`.

Under (b), once #5831 lands upstream and inventories are re-authored: predicate
pins disappear from the gate's input entirely, so those triggers vanish;
only edits to the generated artifacts require a re-mint, and those are edits the
checks themselves would flag anyway.

## Related records and issues

- #110 — this record's issue, with the measured drift history this record
  re-verified at its own head.
- #103 / PR #112 — the loud gate (merged `206dac1`); its gate is correct under
  either policy, and its gate, checker and items 9/10 re-attestations are out of
  scope here.
- #82 / PR #98 — the same shape on item 8's Liberty-view config pin; cited as
  the second data point for the argument, a separate lane.
- 2AMLogic/klayout-tools#5831 — the generic upstream gap (an attestation
  inventory binds a content hash to a check whose predicate does not depend on
  the file's bytes); the schema change (b) needs.
- Format model: `spec/0001-target-specification.md` (this repo's
  decision-record shape, including its provenance caveat practice).
