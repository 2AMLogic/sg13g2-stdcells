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

Current snapshot, 2026-11-23, measured at `396de0f` (this PR's head, with
`origin/main` at `cc907ef` merged in), `klt 0.9.3.dev3562+g4c56d2ca052a`. The
delivering PR changes only `spec/`, so every hash below is also the hash at this
PR's head. **Scope, stated separately:** the *policy* in this record covers four
envelopes (items 1, 2, 9, 10; 16 member pins), because #110 excludes item 8 (the
characterization record, Liberty view and sidecar are a separate lane, #82 /
PR #98). The *measurement* below covers all five envelopes on disk, because
`check_attestations.py` does not exclude item 8.

History, retained and not current: the 2026-11-15 snapshot was measured at
`206dac144633` (19 recorded hashes across 4 envelopes, all matching; committed
T1 count 11 against a fresh 10). Earlier snapshots in #110's body measured at
`ef9e57f` (four drifted member pins) and at its head at filing (two). Every
number in this section was re-measured at the head above, not copied forward.

### Envelope member pins vs the tree

```
$ python3 manifests/check_attestations.py
check_attestations: 23 recorded hashes across 5 envelopes all match the tree
(exit 0)
```

The five-envelope measurement finds **19 matching member pins** with the loop
below: 16 in the four policy envelopes plus 3 in item 8's. The checker counts 23
recorded hashes because each inventory-backed envelope also records its
inventory file (items 1, 8, 9 and 10 add `manifests/inventories/<item>.json`),
and the checker deduplicates. Against the 2026-11-15 table, three digests have
moved since: `design/gen_netlists.py`, `.github/workflows/ci.yml` and
`README.md` (rows below carry the current values), each re-minted by an ordinary
edit and re-attestation — the same churn this record is about.

### Committed grade vs fresh grade

```
$ klt signoff --manifest manifests/sg13g2-stdcells.json \
      --check manifests/signoff-report.json
status: drifted                                            (exit 3; read-only)
  items.0.citation.content_hash                      (committed != fresh)
  items.0.citation.artifact_binding.content_hash     (committed != fresh)
  items.0.citation.artifact_binding.members.0.content_hash
                                                     (committed != fresh)
  items.0.citation.artifact_binding.attestation.description
                                                     (committed: absent)
```

Both the committed and the fresh grade give `t1_met_count = 12` with item 1
(`Design sources`) `met`, so today `main` does **not** overstate its T1 count:
the 2026-11-15 gap (committed 11 vs fresh 10, item 1 `met -> unmet`,
`stale_evidence`) was closed by later re-minting and report regeneration. What
remains is a report-citation drift: the committed report still carries item 1's
old citation hashes (for example the `design/gen_netlists.py` member pin
`758eab5f13e4853c…`, now `2fcf40fa59c33608…`), so `--check` exits 3 even though
the count agrees. The 2026-11-15 mechanism is unchanged and is the point for
this record: the report pins the envelope's input digest, so *the re-mint itself
is churn that re-stales a pin*, and regenerating the report follows whoever
re-mints. Regeneration is out of scope for this record's issue (#110).

### Churn history of one predicate pin

`README.md`'s item 10 pin was observed stale at **three distinct (committed,
tree) hash pairs** during this issue's lifetime (one per 2026-11-15 observation
point: the filing, the body's `ef9e57f` table, and the champion's re-measure),
with `fresh_status: pass` every time it was checked — every one of those drifts
came from an ordinary README edit, and every one invalidated an attestation
that was still true. It matched a fourth pair at the 2026-11-15 snapshot and matches a fifth
(`32469df8c38f84ccb`) at this head: the churn continued after the snapshot.

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
hashed at `396de0f` with

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
implementation guidance, re-run at this head; the loop also prints item 8's 3
member pins, which are outside this table).

| envelope | pinned path | pin (sha256:…) | class | why |
|---|---|---|---|---|
| item1.analog | `design/gen_netlists.py` | `2fcf40fa59c33608b` | predicate-bearing | the evidence is the relation generator+config → committed netlists (`gen_netlists.py --check` passes iff the netlists match its output); #105's edit to the generator left all four netlists matching while staling the pin |
| item1.analog | `layout/example_config.json` | `a9431e088eebbca9b` | predicate-bearing | same relation, as the config input to it |
| item1.analog | `layout/lvs/netlists/sg13g2_inv_1.spice` | `65aa1e3c6e10bc76c` | content-bearing | the attested design source itself; the check regenerates and compares these bytes |
| item1.analog | `layout/lvs/netlists/sg13g2_inv_2.spice` | `da42c9d5d4790a03f` | content-bearing | as above |
| item1.analog | `layout/lvs/netlists/sg13g2_inv_4.spice` | `f350f0e6257207c94` | content-bearing | as above |
| item1.analog | `layout/lvs/netlists/sg13g2_nand2_1.spice` | `1fc9770ab7c6d2a87` | content-bearing | as above |
| item2.analog | `layout/gds/sg13g2_inv_1.gds` | `91c226f6336a7fb8e` | content-bearing | the attested layout artifact; the DRC/LVS evidence was produced from these bytes |
| item2.analog | `layout/gds/sg13g2_inv_2.gds` | `b7f96fccc399bc987` | content-bearing | as above |
| item2.analog | `layout/gds/sg13g2_inv_4.gds` | `e6d2fc1fb4b6a0a0f` | content-bearing | as above |
| item2.analog | `layout/gds/sg13g2_nand2_1.gds` | `9bef3c012a6e531bb` | content-bearing | as above |
| item9.digital | `verification/test_add8.py` | `095bf6541170ee425` | content-bearing | the file is the bench. The digest identifies the exact bench bytes that were reviewed; the item's `cold_start` command (`sh verification/cold_start.sh`, `timeout_s` 1800) separately verifies their behavior, and it **does run** under `--check` (the inventory does not declare `local_only`; measured below). Two different guarantees, both kept: an edit to the bench stales the pin even if the rerun still passes, which is the point of reviewing bench bytes |
| item9.digital | `verification/Makefile` | `c9e504120822d2c10` | content-bearing | drives the same bench; same two guarantees |
| item9.digital | `verification/cold_start.sh` | `7bf48dc164e2f6fc6` | content-bearing | provisions and runs the bench, and is itself the command the rerun executes; same two guarantees |
| item10 | `.github/workflows/ci.yml` | `e362c2ca3e291e380` | predicate-bearing | none of the inventory's three checks (`netlists-fresh`, `layouts-fresh`, `flow-evidence-accepts-committed-record`) reads it; the envelope names it via a path-bearing hygiene check (the workflow exists and names the gates) plus the hash. A presence-only entry would drop the hash, so gutting a gate in this file would no longer be caught by the pin, and nothing the inventory runs reads it. Upstream's canonical-YAML binding (`"attest": "yaml"`, klayout-tools#5862) removes that cost for this file; see Policy, "The `ci.yml` pin" |
| item10 | `README.md` | `32469df8c38f84ccb` | predicate-bearing | hygiene predicate (exists, passes the hygiene gate; the inventory defines no such gate beyond the file's presence, so this predicate is weaker than its name); the highest-churn pin, stale at three observed hash pairs during this issue's lifetime, `fresh_status: pass` every time. Upstream also documents moving the churning content into an uninventoried file (klayout-tools#5603; see the rejected alternatives) |
| item10 | `LICENSE` | `cfc7749b96f63bd31` | predicate-bearing | recognized-licence predicate (the inventory does not define "recognized"; presence is what upstream's presence-only entry would assert); near-frozen in practice, so the churn cost is low — but the pin still over-asserts |

Count: **5 predicate-bearing, 11 content-bearing**. The content-bearing set is
the generated artifacts (4 LVS netlists, 4 GDS) plus the 3 item 9 bench files,
which are content-bearing because the digest identifies the reviewed bench
bytes, a guarantee the cold-start rerun does not give (the rerun checks
behavior, not which bytes were reviewed). The
predicate-bearing set is the 2 item 1 inputs and the 3 item 10 hygiene files.

## Policy

**Recommended: (b) — pin content-bearing paths; record predicate-bearing
inputs without a hash** (name plus the check that verifies them). This is the
only option that stops the churn instead of scheduling it: an edit to one of
the three item 10 hygiene files stops touching the envelope at all. A re-mint
is still needed whenever any byte-pinned path changes: the 4 netlists and 4 GDS
(the generated artifacts), the 3 item 9 bench files (`verification/test_add8.py`,
`verification/Makefile`, `verification/cold_start.sh`; an edit stales the pin
even if the bench still passes), and the 2 item 1 sources (a generator edit
that leaves its netlists byte-identical still stales the pin). It needs a
schema change in `klt signoff --attest` (the envelope is the tool's output,
never hand-edited), tracked as 2AMLogic/klayout-tools#5615. **Upstream status (2026-11-23):** the
presence-only `hygiene` implementation merged on 2026-11-17
([klayout-tools#6216](https://github.com/2AMLogic/klayout-tools/pull/6216)). The
remaining step is local: this repo's `manifests/inventories/item10.json` still
lists the three hygiene files as bare strings (`README.md`, `LICENSE`,
`.github/workflows/ci.yml`), so they are still content-hashed. Adoption means
re-authoring that inventory in the presence-only form and re-minting
`manifests/envelopes/item10.attest.json` on a klt-capable host. That is a
manifest change outside this PR, which touches only `spec/`.

**The item 10 `hygiene` schema is three-valued, not binary.** Beyond a bare
path (byte-hashed), upstream's `signoff.md` for the `klt` on this host
(`klt 0.9.3.dev3644+gbc2cf7bc6f90`) documents a
`{"path", "attest": "presence"|"content"|"yaml", "select"?}` object, with
`"yaml"` added by klayout-tools#5862 (closed as completed 2026-11-18, one day
after #5615). The `yaml` binding hashes the canonical representation of the
selected YAML content, so a comment-only, whitespace-only, key-reorder or
anchor/alias refactor is not drift, but a change to the workflow's gates is.
Upstream names `.github/workflows/ci.yml` as the motivating case: presence
"could not catch a `continue-on-error: true` added to the signoff job, a
removed step or a changed command".

### The `ci.yml` pin

For `.github/workflows/ci.yml` the recommendation is **`attest: "yaml"`, not
presence-only**, adopted together with a follow-up to
`manifests/check_attestations.py` (see the CI consequence). `yaml` is strictly
better than presence on the merits this record argues: it keeps the gate-gutting
coverage that presence gives up, and still does not stale on comment or
formatting edits. Until that follow-up lands, adopting `yaml` would turn
`main` red in tool-free CI. The Judge measured this by driving the committed
`item10.attest.json` through the repo's own `verify_records()` with the `ci.yml`
entry rewritten into the shape current `klt` emits (`attest: "yaml"`,
`hash_algorithm: "sha256-canonical-yaml-v1"`, the raw digest moved to
`raw_content_hash`): `unique=4 mismatches=1`, the `ci.yml` entry expected
`784f0cd1b8b4e284`, actual `e362c2ca3e291e38` (reported in review on 2026-11-23,
not re-run here). `collect_records()` takes every `attestation.checks[]` entry
with both `path` and `content_hash` and compares it to `sha256(raw bytes)`
without reading `attest` or `hash_algorithm`. Upstream's own grading-time
consumer, `signoff.py` `_attested_check_members()`, already excludes
`attest: "yaml"` checks and routes them to
`signoff_attest_canonical_yaml.rehash_checks`, so the gap is local to this
repo's tool-free checker. Presence-only for `ci.yml` is the fallback if the
follow-up is declined, with the gate-gutting cost stated in "What the adoption
gives up and gains". `README.md` and `LICENSE` take presence-only either way.

### Scope: what upstream will actually accept

Upstream (2AMLogic/klayout-tools#5615) accepts a presence-only entry (and, per
#5862, a canonical-YAML entry) for the item 10 `hygiene` field only —
"the motivating case and the only one where the property is meaningful" — and
refuses item 1 `sources` and item 9 `testbenches` outright (an
`AttestationError` naming the accepted set). This record's own filing of the
gap, 2AMLogic/klayout-tools#5831, was closed as a duplicate of #5615, so
#5615 is the live route and its scoping is upstream's measurement, not a
position this record can argue away by re-stating its classification. Policy
(b) is therefore implementable upstream for **3 of the 5 predicate-bearing
pins** (`README.md`, `LICENSE`, `.github/workflows/ci.yml`) and refused for
the 2 item 1 pins (and for item 9, whose pins are content-bearing here). The two upstream reasons, which this record
adopts rather than rebuts:

- **Item 1 `sources` — the option would silently not work.** The manifest
  input binding (`signoff_attest_input.py` `input_binding()`) is not
  key-driven: it reads `normalized["sources"]` and hashes each path itself,
  ignoring the check dict, so a presence-only source's bytes would still be
  folded into the input-set digest the manifest pins — the same binding whose
  re-mint/re-stale sequence is measured above. #5615 records this as a hard
  constraint on any future extension.
- **Item 9 `testbenches` — arguably the wrong semantics.** "The file *is* the
  bench." The classification here rests on two separate guarantees, not on one
  being a fallback for the other. The **byte pin** identifies the bench bytes
  that were reviewed: an edit stales it whether or not the bench still passes.
  The **cold-start rerun** verifies behavior: the committed inventory declares
  `argv` (`sh verification/cold_start.sh`) and `timeout_s` (1800) and does **not**
  declare `local_only`, so `klt signoff --attest 9 --inventory
  manifests/inventories/item9.digital.json --check
  manifests/envelopes/item9.digital.attest.json` runs it. Version-independent
  fact: the fresh attestation records the `cold_start` command with
  `exit_status: 0` and `passed: true`, so `--check` ran it. One earlier run, by
  review `7088916259` under `klt 0.9.2.dev111+g978f7464fae1`, printed
  `cold_start ok in 11.0s` and exited 0 with `status: match`; under
  `klt 0.9.3.dev3644+gbc2cf7bc6f90` the same command exits 3 with
  `status: drifted`, because that `klt` mints three extra `dependency_binding`
  checks and an `attestation.description` that the committed envelope, minted by
  an older `klt`, does not carry. That is tool-version drift, not tree drift;
  `fresh_status` is `pass` either way. A check that a `local_only` declaration would make
  `--check` skip (`_skipped_check`, `--skip-local-only`) would leave the hashes
  as the only live binding; this inventory does not do that today, so that
  stronger argument is **not** the one this record relies on. If the inventory
  ever gains `local_only`, the pins become the only live binding and the
  classification gets stronger, not weaker. Dropping the pins in either case
  would lose the reviewed-bytes guarantee, which the rerun cannot give.

**Stated precisely, then: (b) means the 11 content-bearing paths (4 netlists,
4 GDS, 3 item 9 bench files) keep byte pins, the 3 item 10 hygiene pins leave
byte-pinning: `README.md` and `LICENSE` become presence-only, and `ci.yml`
becomes canonical-YAML-bound (`attest: "yaml"`) once the checker follow-up
above lands, presence-only otherwise (upstream #5615 closed as completed on
2026-11-17 and #5862 on 2026-11-18; local adoption of the inventory form is the
remaining step), and the 2 item 1
predicate pins stay byte-pinned** — for them, (a) below
is not an interim but the standing practice until #5615 is extended upstream
(an item-1 extension belongs as a follow-up on top of #5615, since it needs
the `input_binding()` change). Their churn is bounded in practice: item 1's
inputs move only when the generator or its config change — exactly when the
evidence genuinely must be re-minted. Item 9's three files are content-bearing
and keep their pins on the merits (reviewed-bytes identity, separate from the
rerun's behavioral check), not as a tool-gap hold.

Rejected alternatives, one line each:

- **(a) keep byte pins everywhere and re-mint on churn** (the post-#112 status
  quo) — rejected as the target policy for the hygiene pins: every re-mint
  re-runs predicates that measurably still pass and changes nothing verified;
  `README.md` alone drifted three times during this issue's lifetime. For the
  item 1 and item 9 pins it remains the practice, for two different reasons.
  Item 1: a schema limitation, since upstream's input binding hashes the
  sources regardless, so presence-only cannot work there yet. Item 9: a
  deliberate guarantee, since the byte pin records which bench bytes were
  reviewed, which the cold-start rerun cannot give.
- **(c) automate the re-mint on merge** — rejected: `.github/workflows/ci.yml`
  is tool-free by constraint (`ci.yml:1`), so the automaton must live off-CI and
  would mint evidence on a trigger with no one reviewing the re-run; it also
  hides the moment the envelope changes behind machinery.
- **shrink the item 10 inventory to stop naming the churny files** — rejected:
  that trades away the predicate itself (the attestation would stop claiming
  README/workflow hygiene at all), which is worse than re-minting for them.
- **keep the file listed but move the churning content out of it** (upstream's
  "stable by construction" guidance, klayout-tools#5603: keep the content in an
  uninventoried file such as `STATUS.md` and link to it) — not adopted for
  `README.md`: it changes what the README is for rather than how it is pinned,
  and is a content decision outside this record. It is a different alternative
  from the one above, since it keeps the predicate. Available to a later record.
- **presence-only for `ci.yml`** — the fallback, not the recommendation: it
  gives up gate-gutting coverage that `attest: "yaml"` keeps. Chosen only if the
  `check_attestations.py` follow-up is declined.
- **hand-edit the committed envelopes to drop the hashes** — rejected: the
  envelope is `klt signoff --attest` output, generated never hand-edited, so the
  change comes from re-authoring the inventory in the presence-only form (the
  schema shipped upstream via #5615) and re-minting with `klt signoff --attest`.
- **declare presence-only entries in the item 1 / item 9 inventories anyway** —
  not a choice this record can make: #5615's schema accepts the key on
  `hygiene` only and errors elsewhere, and no inventory form expresses it
  today.

### Interim, until item 10's inventory adopts the presence-only form

(a) remains the operative practice everywhere until the local adoption step
lands; for item 10 it is a hold, not an endorsement. This
record changes no manifest and relaxes nothing. What #112
changed is that the churn is no longer *silent*: the gate names the stale
envelope on every PR that touches a pinned path. Adopting the merged #5615
form in item 10's inventory ends this interim for the 3 item 10 hygiene pins
only. The 2 item 1 pins stay byte-pinned because of a schema limitation, until
#5615 is extended upstream. The 3 item 9 pins stay byte-pinned by design, for
the reviewed-bytes guarantee (see the policy's scope).

## CI consequence of the recommendation

`.github/workflows/ci.yml:1` reads `# Tool-free CI: stdlib Python + pytest + jq
only. No klt, ngspice or PDK.`, and #112's gate step
(`./check-ci.sh attestations` → `python3 manifests/check_attestations.py`)
compares recorded hashes to the tree. Under the interim (a):

- **Trigger**: any commit editing a pinned path turns the gate red on that PR;
  the checker's output names the stale envelope.
- **Who re-mints**: anyone on a klt-capable host (the sweep hosts have `klt`;
  the CI runner never will). Mechanically, for an inventory-backed item: `klt
  signoff --attest <item> --inventory <inventory> -o <envelope>` writes the
  envelope. (`--check <envelope>` is **not** a repair command: `klt signoff
  --help` says it re-attests and exits 0 only if the envelope still
  reproduces, 3 otherwise, "never rewriting it".) Then update any manifest
  evidence pin that names the envelope: `klt signoff --repin` is the mechanical
  half of that step (klayout-tools#5527), rewriting only pins whose live hash
  the grader re-derived (`./check-ci.sh manifest-pins` checks
  those bindings separately and reports nine matching pins at this head), then
  regenerate both formats, `manifests/signoff-report.json` and
  `manifests/signoff-report.txt`, then verify with `klt signoff --manifest
  manifests/sg13g2-stdcells.json --check manifests/signoff-report.json`.
  `--check` accepts only the JSON report; passing the `.txt` exits 1 with
  `klt signoff: request 'manifests/signoff-report.txt' is not valid JSON:
  Expecting value: line 1 column 1 (char 0)`. The report regeneration must follow the
  re-mint, or the committed report keeps stale citation hashes (item 1 today,
  measured above).
- **What turns `main` red meanwhile**: after a merge that moved a pinned path,
  `main`'s own tree fails the gate until a klt-capable re-mint lands; a one-line
  README typo keeps `main` red until then. No CI job can clear it — the runner
  has no `klt`.

Under (b), now that #5615 and #5862 have merged upstream and once item 10's
inventory is re-authored: the `README.md` and `LICENSE` pins disappear from the
gate's and grader's input, so their triggers vanish. The `ci.yml` entry, if
bound with `attest: "yaml"`, stays in the gate's input under a different
algorithm: **`check_attestations.py` must first learn
`sha256-canonical-yaml-v1`, or skip entries whose `hash_algorithm` it does not
recognise**, otherwise it reports a false drift on `ci.yml` and `main` goes red
(measured above). That checker change is a follow-up to this record and, like
the inventory change, outside this PR. Recomputing canonical YAML would need a
YAML parser, which the tool-free gate (`ci.yml:1`, stdlib only) does not have,
so the cheaper variant is to skip unrecognised algorithms and leave the
canonical-YAML check to `klt signoff --attest 10 … --check` and to `--manifest`
grading. A re-mint is still
required for an edit to any of the 13 remaining byte-pinned paths: the 4
netlists and 4 GDS, the 3 item 9 bench files (including a
`verification/test_add8.py` edit that leaves the bench passing), and the 2 item
1 sources (including a generator edit that leaves its netlists identical).
Their triggers remain (policy scope above).

**What the adoption gives up and gains.** The gain is avoided re-mints: a byte
edit to `README.md`, `LICENSE` or `ci.yml` no longer stales a pin. The cost is
twofold. First, byte coverage of the files: under presence-only, a gutted
`ci.yml` (or edited `README.md` / `LICENSE`) no longer stales a pin, and no
check in the inventory reads them. With `attest: "yaml"` on `ci.yml` the
gate-gutting part of that cost does not arise for that file, but the tool-free
gate does not check it until the checker follow-up lands. Second, the hash gate loses a second opportunity to catch a
deletion between attestation runs. Deletion detection is existing coverage, not
a gain: an attestation rerun already checks existence. The Judge ran
`verify_records` with all three hygiene files missing and the inventory present:
the committed (hash-bearing) envelope reported 3 missing files across 4 checked
hashes, while an otherwise equivalent presence-only fixture reported zero
mismatches and checked only the inventory hash (reported in review on
2026-11-23, not re-run here). The tool-free hash stage
(`check_attestations.py`) therefore stops reporting a deleted hygiene file once
the hashes are gone, and a presence-only deletion is no longer caught by the
hash gate between attestation runs. It is caught only when someone reruns
`klt signoff --attest 10 … --check` or re-mints, not on every PR. The
inventory does not define "recognized" licence or "passes the hygiene gate", so
presence is all the predicate asserts.

A third consumer of the stamped hash, worth naming because the interim pays it
today and (b) must disarm it too: at `--manifest` grading time,
`signoff.py`'s `_attested_check_members()` / `_attested_checks_refusal()`
(#4197 in klayout-tools) re-hashes every `present` check that recorded a
`sha256:` hash — all items, item 10 included — and grades a drifted file
`stale_evidence`. An ordinary README edit therefore does not merely turn the
CI gate red on that PR; it leaves the committed manifest row red at the next
grading even where `--check` is not run. #5615's fix (omit the
`content_hash` key, stamp `"attest": "presence"`) disarms this consumer and
the `--check` diff together, because both are key-driven.

## Related records and issues

- #110 — this record's issue, with the measured drift history this record
  re-verified at its own head.
- #103 / PR #112 — the loud gate (merged `206dac1`); its gate is correct under
  either policy, and its gate, checker and items 9/10 re-attestations are out of
  scope here.
- #82 / PR #98 — the same shape on item 8's Liberty-view config pin; cited as
  the second data point for the argument, a separate lane.
- 2AMLogic/klayout-tools#5615 — the upstream gap: an inventory could only
  enumerate bare-path entries, so a presence-only input could not be declared and
  every entry was content-hashed and diffed. The schema change (b) needs;
  implemented for `hygiene` by klayout-tools#6216 (merged 2026-11-17), and the
  item 10 `hygiene`-only scoping (b) adopts is its curatorial verdict.
- 2AMLogic/klayout-tools#5862 — the canonical-YAML inventory mode
  (`"attest": "yaml"`, optional `select`), closed as completed 2026-11-18; the
  third value of the item 10 `hygiene` schema and the recommended binding for
  `ci.yml` (see "The `ci.yml` pin").
- 2AMLogic/klayout-tools#5831 — this record's original generic filing of the
  same gap (an attestation inventory binds a content hash to a check whose
  predicate does not depend on the file's bytes), closed as a duplicate of
  #5615; kept named so the friction-protocol trail stays intact.
- Format model: `spec/0001-target-specification.md` (this repo's
  decision-record shape, including its provenance caveat practice).
