"""Cell-characterization evidence: the validated per-arc record fields.

One timing/energy arc of one cell at one corner, with the provenance of the
numbers (how they were obtained, and on which netlist). ``validate()`` rejects
a record that is missing a field or states an out-of-range value;
``render_lines()`` gives the Markdown bullets the record renderer embeds.
"""

from __future__ import annotations

from dataclasses import dataclass

SENSES: tuple[str, ...] = ("positive_unate", "negative_unate", "non_unate")


class EvidenceFormatError(ValueError):
    """A record would not conform to the evidence schema."""


@dataclass
class CharacterizationExtensions:
    """Cell-characterization evidence: one timing/energy arc at one corner.

    Every field below except ``arc_when`` (empty = unconditional arc) is
    required. ``data_provenance`` says how the numbers were obtained (e.g.
    "simulated"); ``netlist_provenance`` says which netlist they were measured
    on.
    """

    data_provenance: str = ""
    cell: str = ""
    arc_related_pin: str = ""
    arc_when: str = ""
    arc_sense: str = ""
    input_slew_ns: float | None = None
    output_load_pf: float | None = None
    delay_ns: float | None = None
    transition_ns: float | None = None
    energy_pj: float | None = None
    corner: str = ""
    netlist_provenance: str = ""

    _REQUIRED_TEXT = (
        "data_provenance",
        "cell",
        "arc_related_pin",
        "arc_sense",
        "corner",
        "netlist_provenance",
    )
    _REQUIRED_NUM = ("input_slew_ns", "output_load_pf", "delay_ns", "transition_ns", "energy_pj")

    def validate(self) -> None:
        """Raise :class:`EvidenceFormatError` if the record would not conform."""
        from .corners import CHAR_CORNER_PVT

        problems: list[str] = [f"{n} is required" for n in self._REQUIRED_TEXT if not getattr(self, n)]
        problems += [f"{n} is required" for n in self._REQUIRED_NUM if getattr(self, n) is None]
        if self.arc_sense and self.arc_sense not in SENSES:
            problems.append(f"arc_sense {self.arc_sense!r} is not one of {', '.join(SENSES)}")
        if self.corner and self.corner not in CHAR_CORNER_PVT:
            problems.append(
                f"corner {self.corner!r} is not a characterization corner "
                f"({', '.join(CHAR_CORNER_PVT)})"
            )
        for n in ("input_slew_ns", "output_load_pf", "delay_ns", "transition_ns"):
            v = getattr(self, n)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v < 0:
                problems.append(f"{n} must not be negative")
        for n in self._REQUIRED_NUM:
            v = getattr(self, n)
            if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))):
                problems.append(f"{n} must be a number, got {v!r}")
        if problems:
            raise EvidenceFormatError(
                "record would not conform to the evidence schema:\n  - " + "\n  - ".join(problems)
            )

    def render_lines(self) -> list[str]:
        """The record's Markdown bullets."""
        lines: list[str] = []
        if self.data_provenance:
            lines.append(f"- **Data provenance**: {self.data_provenance}")
        arc = f"{self.arc_related_pin} ({self.arc_sense})"
        if self.arc_when:
            arc += f" when {self.arc_when}"
        lines += [
            f"- **Cell**: {self.cell}",
            f"- **Arc**: {arc}",
            f"- **Corner**: {self.corner}",
            f"- **Input slew / output load**: {self.input_slew_ns} ns / {self.output_load_pf} pF",
            f"- **Delay / transition / energy**: {self.delay_ns} ns / "
            f"{self.transition_ns} ns / {self.energy_pj} pJ",
            f"- **Netlist provenance**: {self.netlist_provenance}",
        ]
        return lines
