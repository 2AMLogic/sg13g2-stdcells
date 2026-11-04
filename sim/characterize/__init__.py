"""Per-cell characterization driver: builds a ``klt characterize`` request and
records the raw per-arc measurements as append-only evidence.

This package never writes Liberty. ``klt characterize`` owns the Liberty side;
the ``.lib`` it emits stays in its scratch directory and is not an artifact of
this repo (no ``.lib`` is committed until the library has cells of its own).
"""
