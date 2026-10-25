"""The assumptions register: every default the tool applied that a senior engineer should confirm.

Reviewers always ask "what did you assume?".  Instead of burying the answer in code, the
list lives here and is printed in the TQ register and the summary report.  Entries marked
conditional (A05, A11) only appear when they actually applied to the run.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Assumption:
    id: str
    text: str
    source: str        # where the assumption comes from
    confirm_by: str    # 'Senior engineer' | 'Project lead' | 'Client'


ASSUMPTIONS: tuple[Assumption, ...] = (
    Assumption("A01", "The Service Description of a field signal is taken from the MDB column 'Tag Service 1 and 2'.",
               "Checked against the client's sample allocation: identical for every tag.", "Senior engineer"),
    Assumption("A02", "A second IO type on a row (for example DI + DO or AI + AO) is the other end of a third-party "
               "interface; only the first type is allocated as a channel.", "Seen in the client's sample MDB (HVAC interface rows).",
               "Project lead"),
    Assumption("A03", "The 10% wired-spare quota is counted on Field signals only, per IO type, per controller.",
               "Project allocation rules, section 3D.3 (wired spares).", "Senior engineer"),
    Assumption("A04", "Cabinet alarms are not counted as field signals for the spare quota and use only the project's "
               "cabinet-alarm baseplate (CIOC 1, baseplate 1 unless the rule pack says otherwise). This is a project choice, "
               "not a DeltaV rule.",
               "Project allocation rules, section 3D.1 (cabinet alarms), the VIT allocation guide, and the client's sample "
               "allocation.", "Senior engineer"),
    Assumption("A05", "Section / Sub Unit is worked out from the tag number by a simple rule table; it is informational only.",
               "Seen in the client's sample allocation (not a fixed formula).", "Senior engineer"),
    Assumption("A06", "Revision No is '00' on a first run; later revisions stamp only the changed rows with the revision label.",
               "Convention of the client's sample allocation.", "Project lead"),
    Assumption("A07", "Cabinets that receive no signal and no alarm are not listed in the output.",
               "IO Sudoku design decision.", "Project lead"),
    Assumption("A08", "Cables of 6 pairs or fewer are half-baseplate aligned (channel 1 or 7), so two can share a baseplate.",
               "Seen in the client's sample allocation.", "Senior engineer"),
    Assumption("A09", "Cable sizes above 6 pairs are rounded up to a multiple of 12 channels (whole baseplates).",
               "IO Sudoku design decision.", "Senior engineer"),
    Assumption("A10", "Segregation A and A-CONTROL form one family and B and B-ALARM another; C, D and E are unrestricted. "
               "The two families never share a CIOC.", "Project allocation rules, section 3D.2 (segregation), and the DeltaV allocation guideline.", "Project lead"),
    Assumption("A11", "Cabinet, system cabinet and controller names for some technical rooms were inferred from the MDB, "
               "not read from the configured topology.", "Worked out from the MDB because the configured topology had no entry.", "Senior engineer"),
    Assumption("A12", "Default project rules (pack VIT-2026): cabinet alarms on CIOC 1, baseplate 1, 10% wired spares "
               "(rounded up), 10% future space, the last 4 baseplates of CIOC 4 kept empty (at least 3 must be empty).", "Project allocation rules, section 3D.3, and the default rule pack VIT-2026.", "Client"),
)


def applicable_assumptions(result: Any) -> list[Assumption]:
    """The assumptions that applied to this run (A05 needs Field rows, A11 needs topology inference)."""
    rows = getattr(result, "rows", []) or []
    tqs = getattr(result, "tqs", []) or []
    has_field = any(r.get("Tag Status") == "Field" for r in rows)
    inferred = any(t.tq_id == "TOPOLOGY-INFERRED" for t in tqs)
    chosen = []
    for item in ASSUMPTIONS:
        if item.id == "A05" and not has_field:
            continue
        if item.id == "A11" and not inferred:
            continue
        chosen.append(item)
    return chosen
