"""sim/harness — PVT corner definitions, the evidence schema, and record ids.

The local-ngspice runner half of the scaffold was removed (#21); simulation
goes through ``klt`` (see ``sim/characterize``). See ``README.md``.
"""

from __future__ import annotations

#: Bump when a change here would make an existing extension (corner additions,
#: evidence subclass) worth re-checking against this package.
HARNESS_VERSION = "1.1.0"

#: Where this package was distilled from — read for reference, never vendored.
UPSTREAM_PATTERN = "https://github.com/2AMLogic/gf180-sar-adc/tree/main/sim/harness"

__all__ = ["HARNESS_VERSION", "UPSTREAM_PATTERN"]
