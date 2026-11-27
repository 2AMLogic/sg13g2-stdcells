# Work Log

Chronological record of merged PRs and closed issues. Maintained by the Guide role.

### 2026-11-27

- **PR #305**: refactor: count shared diffusion breaks during strip pairing
- **Issue #304** (closed): Count diffusion breaks once per column in the bounded pairing search
- **PR #294**: refactor: share evidence and single-envelope setup in manifest tests
- **Issue #292** (closed): Share manifest evidence wrapper and single-envelope setup in manifests/tests/test_check_attestations.py

### 2026-11-26

- **PR #300**: fix(sim): assemble item 5 requests once and reject an off-corner rail
- **Issue #299** (closed): Share the item 5 transient request builder and check its stimulus voltage against TT
- **PR #287**: feat: attest the add8 stock-library characterization across three corners
- **Issue #177** (closed): T1 item 8 digital: aggregate the add8 baseline delay, area and power into one attested characterization report (rows 10-12 declared unmeasured)
- **PR #296**: refactor(sim): dedupe fixture-mutation helpers in test_check_library
- **Issue #295** (closed): Share record-header, sidecar, and text-replace helpers in sim/tests/test_check_library.py
- **PR #291**: refactor(sim): grade item 5 reports with targets from each request
- **Issue #290** (closed): Reuse item 5 measurement targets when grading simulation reports
- **PR #289**: ci: delegate evidence-sta-fv-reject to the shared flow edge suite
- **Issue #288** (closed): Share STA/FV jq mutation suite between check-ci.sh and flow/test-check-evidence.sh

### 2026-11-24

- **PR #281**: chore(layout): drop unread pin fields, append correction paragraph
- **Issue #62** (closed): Remove two unused layout toolchain fields and append a correction to the bootstrap note
- **PR #214**: fix(sim): make run_klt workdir required, drop leaking mkdtemp fallback
- **Issue #202** (closed): Remove leaking workdir=None mkdtemp fallback in sim/characterize/runner.py:run_klt and pass tmp_path from test_runner_batch_flags.py
- **PR #278**: test: add substrate-tap ERC negative control (missing-tie-substrate-inv1)
- **Issue #232** (closed): ERC: no negative control for the substrate tie, the one tie the grader says rests on a caller assertion
- **PR #187**: Add klt erc supply/tie evidence: T1 item 11 analog MET (groups 4/4)
- **Issue #179** (closed): T1 item 11 analog: run klt erc supply checks on the four generated cells and cite them with their LVS reports
- **PR #276**: refactor: drop the layout-side gate-finger fold duplicated by gen_netlists
- **Issue #272** (closed): gen_layouts' per-gate finger fold is now redundant with the netlist generator's
- **PR #273**: layout: pick each strip independently in the greedy pairing fallback
- **Issue #269** (closed): Simplify greedy strip pairing by choosing each strip independently
- **PR #270**: tests: reuse gen_controls.forced_break for DiffusionBreaks forcing
- **Issue #268** (closed): Share gen_controls.forced_break with DiffusionBreaks in layout tests
- **PR #266**: fix(flow): time the committed routed DEF so STA geometry is re-hashable
- **Issue #235** (closed): Item 5 digital's STA geometry cannot be re-derived from the repo: the timed DEF is uncommitted scratch
- **Issue #181** (closed): T1 item 7 analog: klt pex schematic-vs-extracted delta on the four generated cells
- **PR #267**: feat: cite graded klt pex reports for item 7 after finger reconciliation
- **PR #265**: test: exhaust the pairing space to re-name the folded series stack limit
- **Issue #257** (closed): layout: join the internal node of a folded series stack without crossing the output
- **PR #263**: docs: name both flow-record variables in the CI section
- **Issue #264** (closed): Remove unused extra/notes slot and as_dict from sim/harness BaseExtensions
- **Issue #260** (closed): Share the simulation report setup in manifest list-pin tests
- **PR #262**: refactor(manifests): share report setup in list-pin tests via item5 fixture
- **Issue #255** (closed): README names only FLOW_RECORD, but CI now gates on two flow records
- **PR #254**: fix: require ok status, routed geometry and array corners in evidence gate 4
- **Issue #190** (closed): A degraded klt sta envelope still grades met: neither the evidence gate nor the signoff grader pins status or geometry_source
- **PR #252**: docs: add add8 baseline characterization report for T1 item 8 digital
- **PR #251**: refactor(sim): delegate item-5 function parse/eval to design.gen_netlists
- **Issue #239** (closed): Deduplicate boolean function parser/evaluator in sim/item5/request.py using design/gen_netlists.py
- **PR #248**: feat(sim): record klt pex post-layout deltas as findings for the four cells
- **PR #241**: test: assert merge.treeChecks entries match check-ci.sh stage commands
- **Issue #237** (closed): merge.treeChecks and check-ci.sh stage commands are kept in step only by a comment
- **PR #204**: layout: place multi-chain strips via rule-derived diffusion breaks
- **Issue #169** (closed): layout: place cells that need a diffusion break in gen_layouts.py (XOR/mux, AOI/OAI, AND/OR, even-finger series stacks)

### 2026-11-23

- **PR #259**: docs: record as-built on-grid cell widths and row 10 implication
- **Issue #244** (closed): Record the (columns + 2) cell-width cost of the row-4 grid phasing against row 10's area target
- **PR #258**: docs: measure why buf and folded nand2/nor2 do not place, pin with a fixture
- **PR #253**: ci: replay six-argument STA/FV evidence gate on the committed record
- **Issue #189** (closed): CI never exercises the six-argument STA/FV evidence gate
- **PR #250**: fix: require complete STA constraint_completeness in evidence gate 4
- **Issue #247** (closed): flow/check-evidence.sh gate 4 does not check STA constraint_completeness
- **PR #246**: docs(layout): document klt pin semantics and item 9 analog re-mint sequence
- **Issue #243** (closed): item 9 analog klt pin churns: the attested envelope cannot be re-minted once the workers' klt rolls past pins.tools.klt
- **PR #240**: feat(layout): place every pin label on the 420 nm routing grid
- **Issue #225** (closed): layout: place the 15 off-grid pin labels on the 0.42 µm routing grid across the four shipped cells
- **PR #238**: refactor(sim): remove single-cell characterization mode, one-mode CLI
- **Issue #211** (closed): Remove bootstrap single-cell mode in sim/characterize: build_request, characterize_and_record and SG13G2_INV_1
- **PR #226**: fix(manifests): check pinned-object elements of list evidence entries
- **Issue #220** (closed): manifest-pin CI check skips list-shaped evidence entries, so the eight item-5 citation pins are unguarded in tool-free CI
- **PR #242**: feat(manifests): content-pin check-ci.sh in item 10 hygiene inventory
- **Issue #233** (closed): Consider content-pinning check-ci.sh in the T1 item 10 hygiene inventory
- **PR #236**: docs(roadmap): cite rows 1/2 tests by name, not stale line numbers
- **Issue #229** (closed): ROADMAP rows 1/2 cite stale test line numbers (test_gen_layouts.py:113,127,129,133)
- **PR #234**: ci: run attestation checks on the merge tree before merge
- **Issue #228** (closed): Attestation content-hash gate can go red on main from two green PRs (semantic merge conflict)
- **PR #227**: test: check every pin label against the routing grid and record the off-grid labels
- **Issue #221** (closed): spec row 4 (pin access on the routing grid) has no check and no tracking issue
- **PR #224**: docs(sim): correct the item 5 timing tolerance rationale
- **Issue #222** (closed): sim/item5/request.py's 2 % tolerance rationale quotes a stale worst-case drift (~0.03 %, not the recorded 0.058 %)
- **PR #219**: refactor(manifests): route item10 audit checks through check-ci.sh stages
- **Issue #218** (closed): Route manifests/inventories/item10.json checks through check-ci.sh instead of duplicating CI commands
- **Issue #213** (closed): fix: re-attest item9.analog.attest.json after PR #199 updated design/gen_netlists.py
- **PR #197**: feat(sim): grade T1 item 5 analog met with klt sim row-9 corner evidence
- **Issue #180** (closed): T1 item 5 analog: commit klt sim corner evidence for the four generated cells with a declared spec-row set
- **PR #195**: refactor: share one forced_strip_profile context manager between gen_controls and ForcedNotch
- **Issue #192** (closed): Share the notch profile override between DRC controls and layout tests
- **PR #191**: docs: link roadmap evidence grade to the committed signoff report
- **Issue #188** (closed): Link the roadmap evidence grade to the committed signoff report
- **PR #186**: feat: add multi-corner STA and functional-verification evidence to the add8 flow (T1 item 5 digital)
- **Issue #175** (closed): T1 item 5 digital: add klt sta and klt functional-verification to the add8 flow and cite both
- **PR #212**: docs: give the signoff-manifest and characterization tails their own headings in layout/README.md
- **Issue #208** (closed): layout/README.md: the LVS-evidence section's tail outlines signoff-manifest and characterization records as part of the #42/#73 LVS result
- **PR #207**: docs: give the recorded LVS result its own heading in layout/README.md
- **Issue #206** (closed): layout/README.md: the #198 re-verification subsection outlines the LVS signoff result under itself
- **PR #203**: fix: route a diffusion-driven gate as a terminal of its net's Metal1 track
- **Issue #201** (closed): layout: generated buffer leaves its internal gate disconnected from the Metal1 track
- **PR #193**: feat: pin IHP-Open-PDK in characterization records and attest T1 item 9 analog

### 2026-11-22

- **PR #200**: docs(layout): document isolated re-verification of committed LVS reports
- **Issue #198** (closed): Document how to reproduce the committed LVS checks and diagnose deck drift
- **PR #199**: fix: compare generated netlists byte-for-byte and gate LVS --check on the generator
- **Issue #196** (closed): Reuse the generator freshness check for LVS reference netlists

### 2026-11-21

- **PR #185**: feat: verify document pins for digital item 6 signoff
- **Issue #174** (closed): T1 item 6 digital: record not_applicable for the add8 partition by citing the ratified spec table directly, and teach check_attestations.py the form

### 2026-11-18

- **Issue #159** (closed, not planned): Trim merge-lap narrative from layout/README.md: history already in git, WORK_LOG and the signoff report

### 2026-11-17

- **PR #165**: check_library: report an empty provenance stamp instead of passing fresh
- **Issue #154** (closed): check_library: an empty provenance stamp reports fresh on both sides
- **PR #146**: fix(sim): pass --wait-for-capacity on batch klt characterize submits
- **Issue #142** (closed): sim/characterize: run_klt never passes --wait-for-capacity on a batch klt characterize submit
- **Issue #115** (closed): Report upstream: generate-agents-md.sh is shipped into installed .loom/scripts/, where it cannot run

### 2026-11-16

- **PR #151**: fix: reap characterize_and_record's klt scratch dir via caller-owned workdir
- **Issue #149** (closed): sim: run_klt leaves an unreaped /tmp scratch dir when called without workdir
- **PR #155**: docs: point ROADMAP Liberty row at the current characterize record
- **PR #153**: check_library: flag a sidecar repo_commit that disagrees with the record's stamp
- **PR #148**: fix: derive the Liberty view name from the characterization corner
- **Issue #147** (closed): check_library never relates the sidecar's repo_commit to the record stamp, so a sidecar repointed at another tree's record passes
- **Issue #144** (closed): ROADMAP.md still cites superseded (dirty) record 20261115-171205-3462cc8 in the present tense
- **Issue #143** (closed): Liberty library name and default view path are hard-coded to tt, so --corner ff|ss cannot produce a correctly-named library view
- **PR #150**: test: pin characterize_library's capture-before-write provenance ordering
- **PR #145**: fix: fail check_library on dirty provenance stamps
- **PR #141**: feat: add --corner selection to the sim.characterize CLI
- **PR #139**: fix: guard non-object JSON top level in check_attestations --manifest mode
- **PR #135**: fix: make manifest-pins fail on zero pins and unreadable manifests
- **PR #98**: fix: regenerate the TT Liberty view's provenance against the current config (T1 #8 [analog] MET)
- **Issue #140** (closed): Add --corner to the sim.characterize CLI the docs say selects FF/SS
- **Issue #138** (closed): test_runner_provenance pins the shared-snapshot contract but not the capture-before-write ordering it exists to protect
- **Issue #137** (closed): check_attestations --manifest tracebacks on a valid-JSON manifest that is not an object
- **Issue #134** (closed): Committed Liberty evidence on main stamps a dirty tree, and no check can fail on it
- **Issue #129** (closed): manifest-pins stage passes vacuously when a manifest carries zero object pins
- **Issue #124** (closed): test_committed_tree_config_pin_is_fresh docstring names a superseded record id
- **Issue #82** (closed): Liberty view provenance pins a config SHA-256 that no longer matches the tree, blocking T1 item 8

### 2026-11-15

- **PR #131**: sim/characterize: record the simulator version in evidence records and the Liberty sidecar
- **Issue #125** (closed): Characterization records never record the simulator version (ngspice); only klt's is captured
- **PR #128**: ci: gate manifest evidence pins against the envelopes they name
- **PR #127**: docs: record items 1 and 10 fix-round re-attestations in the #103 note
- **PR #122**: check_library: pin the view's declared corner and narrow the freshness claim to what is checked
- **PR #126**: fix: regenerate the recorded notch controls from a committed, CI-checked table
- **PR #118**: layout: record the notch predicate's merged admit (opening <= 0) as a fourth DRC control
- **PR #113**: refactor: fold process section into CHAR_CORNER_PVT, drop unused Corner/FAMILIES/CORNERS layer
- **PR #112**: ci: gate attestation envelopes against the committed files and re-attest items 1, 9 and 10
- **PR #108**: verification: implement the documented RTL_DIR override
- **PR #107**: fix: require cell and corner inside one record block in check_library step 4
- **PR #106**: docs: correct design/ and views/ sub-README summaries to tracked content
- **PR #105**: fix: enforce schema_version == 1 in gen_netlists.validate
- **PR #104**: layout: make the strip-notch refusal pitch-, layer- and strip-aware
- **PR #101**: docs: re-derive ROADMAP snapshot against main @ 176f794
- **PR #100**: fix: require the nsd layer and classify its absence as an exit-2 config error
- **PR #97**: refactor: remove never-read locals, dead CellSpec field and keep_artifacts knob
- **PR #94**: sim/characterize: derive check_library default paths from LIBRARY_NAME and __file__
- **PR #90**: build: hold the CI check list once in check-ci.sh and call it from all three places
- **Issue #130** (closed): Mint the T1 item 8 attestation envelope for the refreshed Liberty view (view is now fresh)
- **Issue #117** (closed): layout/README.md re-attestation note omits item 1 (added in PR #112's fix round)
- **Issue #116** (closed): main's committed signoff report overstates T1 by six partitions (11/22 committed vs 5/22 re-graded)
- **Issue #119** (closed): check_library: the freshness check claims to catch a hand-edited Liberty view but never reads the view's contents
- **Issue #120** (closed): layout: recorded DRC controls have no committed regeneration recipe (the stream's cell-name override is undocumented)
- **Issue #114** (closed): layout: the notch predicate's `opening <= 0` (merged-shapes) admit row has no DRC control behind it
- **Issue #111** (closed): Remove unused generality in sim/harness: corner-matrix kind, extra/notes slot, fs/sf corners
- **Issue #109** (closed): Remove unused Corner/FAMILIES/CORNERS generality in sim/harness/corners.py
- **Issue #103** (closed): T1 item 10 attestation hashes drift silently from the files they attest
- **Issue #102** (closed): check_library: the evidence-record step matches cell and corner as loose substrings, so a record with no tt measurements passes as fresh
- **Issue #96** (closed): ROADMAP: the Now list's item 4 and the blocked entry describe work main has already delivered
- **Issue #95** (closed): Enforce or drop schema_version: both generators advertise a config contract version they never check
- **Issue #89** (closed): verification: the documented RTL_DIR override is read by nothing, so a gate-level run silently tests the behavioral RTL
- **Issue #88** (closed): sim/characterize: derive the Liberty view and records paths in check_library.py instead of retyping them
- **Issue #87** (closed): Sub-READMEs still claim xschem schematics and LEF views the repo does not track
- **Issue #86** (closed): layout: the notch refusal is pitch-independent, but a notch only violates when the opening is narrower than activ_space_nm
- **Issue #81** (closed): Hold the CI check list in one place: ci.yml, package.json and README.md each carry their own copy
- **Issue #80** (closed): gen_layouts: nsd is in OPTIONAL_LAYERS but the tap code requires it, so a missing nsd exits 3 instead of 2
- **Issue #77** (closed): Remove never-read locals, a dead CellSpec field and the keep_artifacts knob in layout/gen_layouts.py and sim/characterize/request.py

### 2026-11-14

- **PR #93**: chore: remove stale ngspice-harness gitignore rules and duplicate flow/build entry
- **PR #85**: feat: step the diffusion outline so one strip can hold mixed finger widths
- **PR #72**: docs: roadmap as of 2026-11-13
- **Issue #91** (closed): Remove .gitignore rules left over from the removed local-ngspice harness half, and the duplicate flow scratch-dir entry
- **Issue #74** (closed): layout: place devices of different finger widths in one diffusion strip (and2, or2, a21oi, o21ai)
- **PR #84**: docs: state the recorded cell evidence in the README Status block
- **PR #83**: feat: cite the cocotb testbench and hygiene inventory for T1 items 9 and 10
- **PR #79**: feat: generate well and substrate taps, closing analog LVS on all four cells
- **Issue #76** (closed): README: bring the Status section and repo-layout tree in line with what is on main
- **Issue #75** (closed): manifests: cite the committed Liberty view, cocotb testbench and hygiene inventory for T1 items 8, 9, 10 and regrade
- **Issue #73** (closed): layout: draw well and substrate taps in gen_layouts.py and re-run LVS on the four cells

### 2026-11-13

- **PR #71**: ci: pin pytest to 9.2.0 and split the harness README's dependency claim
- **PR #68**: build: point check:ci and test at the real CI commands, collapse four test runs into one
- **PR #67**: chore: gate the committed SG13G2 netlists in CI, drop the demo placeholders
- **PR #63**: refactor(characterize): one cell-entry builder, and docs that match the committed .lib
- **Issue #70** (closed): Pin the pytest version CI installs and fix the 'no third-party dependencies' contradiction in sim/harness/README.md
- **Issue #66** (closed): Wire package.json check scripts to the real CI commands: they print 'No checks configured' and exit 0
- **Issue #65** (closed): Remove committed demo_* placeholder netlists from design/netlists and gate the real cell netlists in CI instead
- **Issue #58** (closed): Deduplicate cell-entry building in sim/characterize/request.py and fix stale 'no cells / writes no Liberty' docs
- **PR #61**: refactor(sim/harness): drop the unused tb.json manifest adapter
- **Issue #54** (closed): Remove unused from_manifest and MANIFEST_KEYS from sim/harness/evidence.py

### 2026-11-12

- **PR #53**: refactor(sim): remove unused corner-set registry and PVT grid
- **Issue #51** (closed): Remove unused corner-set registry and PvtPoint grid from sim/harness/corners.py

### 2026-11-10

- **PR #50**: refactor(sim): remove unused constants from sim/harness/__init__.py
- **Issue #34** (closed): Remove unused harness constants and test-only corner-set layer in sim/harness

### 2026-11-07

- **PR #46**: feat(layout): LVS runner, recorded LVS reports and analog T1 citations
- **PR #48**: refactor(gen): share check/write/prune logic between generators
- **PR #43**: ci: add tool-free CI workflow and README reproduction commands
- **PR #45**: feat(views): characterize generated cells to a committed TT Liberty view
- **PR #44**: feat(flow): record routed add8 GDS and klt drc evidence for T1 digital items 2, 3
- **Issue #42** (closed): Analog T1 evidence: LVS on generated cells and manifest citations for items 1, 2, 4
- **Issue #47** (closed): Dedupe check/main sync logic shared by gen_netlists.py and gen_layouts.py
- **Issue #38** (closed): No open work toward T1 after #27, and no CI workflow on main
- **Issue #39** (closed): CI workflow on main and T1 item 10 inventory
- **Issue #40** (closed): Characterize generated cells to a committed Liberty view in views/ (spec row 9)
- **Issue #41** (closed): Digital T1 evidence: routed add8 GDS and klt drc report (items 2, 3)

### 2026-11-06

- **PR #36**: feat(layout): place multi-finger devices as adjacent poly columns
- **Issue #35** (closed): layout: place multi-finger devices in gen_layouts.py so drive-2 and 4-input cells lay out
- **PR #32**: refactor(sim): remove dead PVT-grid and sabotage helpers
- **Issue #31** (closed): Remove dead grid helpers left in sim/harness/corners.py after #21
- **PR #29**: refactor(sim): remove unexercised local-ngspice half of sim/harness
- **PR #28**: feat(manifests): add block manifest and graded klt signoff T1 report
- **PR #12**: docs(spec): add target-specification decision record and sync README table
- **Issue #21** (closed): Remove unexercised local-ngspice half of sim/harness (cli, runner, testbench, pdk, toolchain)
- **Issue #27** (closed): manifests: block manifest and first graded klt signoff T1 verdict
- **Issue #1** (closed): Ratify the target specification

### 2026-11-05

- **PR #23**: feat: add config-driven static-CMOS cell layout generator with --check
- **PR #20**: fix: preload psp103.osdi and record first real klt characterize run
- **PR #19**: refactor: route characterization driver through harness corners and validated evidence
- **Issue #22** (closed): Add a config-driven cell layout generator (netlist + process config -> GDS) with --check
- **Issue #17** (closed): Consolidate characterize driver onto harness corners and CharacterizationExtensions
- **Issue #8** (closed): sim: drive klt characterize for a baseline sg13g2_stdcell cell and record evidence
- **Issue #2** (closed): Harness bootstrap

### 2026-11-04

- **PR #18**: feat: reject generator-colliding pin names and add configurable width grid
- **PR #15**: feat: add add8 baseline flow on sg13g2_stdcell with recorded power gates
- **PR #14**: feat: add klt characterize driver and append-only per-arc evidence records
- **PR #13**: feat: add draft characterization corner set and validated characterization evidence
- **PR #11**: feat: add PDK-independent static-CMOS netlist generator
- **PR #10**: feat: add __main__.py so the sim harness runs as a module
- **PR #6**: Resync Loom 0.19.382 → 0.19.1263 ahead of fleet admission
- **Issue #16** (closed): gen_netlists: reject pin names colliding with generated nodes; make width grid a config key
- **Issue #9** (closed): flow: synthesis + place-and-route skeleton and baseline benchmark against sg13g2_stdcell
- **Issue #7** (closed): sim/harness: register characterization corners and validated evidence fields
- **Issue #5** (closed): Land a PDK-independent static-CMOS netlist generator (topology from boolean functions)
- **Issue #4** (closed): sim/harness: no __main__.py, so documented 'python -m sim.harness' fails
