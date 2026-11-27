"""Plumbing shared by the ``klt``-driving sim runners.

One home for the host rule and the version probe, so the runners cannot drift
apart on either.
"""

from __future__ import annotations

import subprocess

#: Host rule: every batch ``klt`` submit must wait up to this long for fleet
#: capacity instead of failing the step on ``batch_no_capacity``. ``klt``
#: rejects the flag on ``--backend local``, so it is added for batch submits
#: only.
BATCH_CAPACITY_WAIT_S = 600


def klt_version() -> str:
    try:
        out = subprocess.run(["klt", "--version"], capture_output=True, text=True, check=False)
    except FileNotFoundError:  # tool-free environments (CI) have no klt
        return "unavailable"
    return (out.stdout or out.stderr).strip() or "unknown"
