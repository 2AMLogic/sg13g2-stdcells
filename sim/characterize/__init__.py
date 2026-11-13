"""Per-cell characterization driver: builds a ``klt characterize`` request and
records the raw per-arc measurements as append-only evidence.

Two modes, and they differ in whether a Liberty view is committed. The default
baseline leg characterizes the PDK's own ``sg13g2_stdcell`` inverter -- the
benchmark denominator of ``spec/0001-target-specification.md`` ("Baseline
Liberty") -- and writes no Liberty at all: it records measurements only.
``--library`` characterizes this repo's generated cells (``layout/example_config.json``)
in one ``cells`` request and hands klt ``--lib``, so klt writes the committed
``views/sg13g2_stdcells_tt_1p20v_25c.lib``; this package writes that view's
``.lib.provenance`` sidecar beside it and the matching evidence record. Liberty
formatting is always klt's, never this package's.
"""
