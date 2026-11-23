"""Per-cell characterization driver: builds a ``klt characterize`` request and
records the raw per-arc measurements as append-only evidence.

One flow: ``python3 -m sim.characterize`` characterizes this repo's generated
cells (``layout/example_config.json``) in one ``cells`` request and hands klt
``--lib``, so klt writes the committed corner-named view under ``views/``
(``sg13g2_stdcells_tt_1p20v_25c.lib`` at the default corner; the name is
derived per corner from ``sim.harness.corners.CHAR_CORNER_PVT``); this package
writes that view's ``.lib.provenance`` sidecar beside it and the matching
evidence record. Liberty formatting is always klt's, never this package's.
"""
