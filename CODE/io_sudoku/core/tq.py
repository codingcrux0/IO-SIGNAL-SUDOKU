"""Technical Queries (TQs): the tool's way of asking a human instead of crashing.

Whenever data is missing, ambiguous or out of scope, a module calls TQLog.add(...)
with a TQ id.  The id decides the severity, category, owner and the default
suggested fix.  Nothing is ever dropped silently.

TQ-TEXT GATE (CLAUDE_RULES section 6.2): all TQ wording lives in THIS file only
(CATALOGUE resolutions + MESSAGES), so it can be rewritten in one place once
`skills/human-writing.md` is supplied.  Interim tone rules: a clear question, then
the suggested fix; plain words, active voice, second person, name the tag/cable/pair.
Tests assert ids, severities and refs - never exact wording.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator


@dataclass(frozen=True)
class TQSpec:
    severity: str    # 'error' | 'warning' | 'info'
    category: str
    owner: str       # who should answer: Instrument / Electrical / Process / Engineering / System
    resolution: str  # default suggested fix


def _rows() -> list[tuple[str, str, str, str, str]]:
    # (id, severity, category, owner, default resolution)
    return [
        ("UNREADABLE-FILE", "error", "File", "Engineering", "Re-save the file as .xlsx and upload it again."),
        ("UNSUPPORTED-FORMAT", "error", "File", "Engineering", "Open the file in Excel and save it as .xlsx (Excel Workbook)."),
        ("FILE-TOO-LARGE", "error", "File", "Engineering", "Split the MDB or remove unused sheets (limit 50 MB)."),
        ("TOO-MANY-ROWS", "error", "File", "Engineering", "Split the MDB (limit 200,000 rows)."),
        ("MISSING-COLUMN", "error", "File", "Engineering", "Add the column or map it in the column-mapping table."),
        ("COLUMN-FUZZY-MATCHED", "info", "File", "Engineering", "Confirm the guessed column mapping."),
        ("MULTI-SHEET-USED", "info", "File", "Engineering", "Confirm all listed sheets belong to this MDB."),
        ("DELETED-IN-MDB", "info", "Data", "Instrument", "No action: the row marked DELETED was excluded."),
        ("BLANK-TAG", "error", "Data", "Instrument", "Provide the tag number."),
        ("DUPLICATE-TAG", "error", "Data", "Instrument", "Make the tag numbers unique."),
        ("MISSING-IO-TYPE", "error", "Data", "Instrument", "Provide the IO type (AIR, AOR, DIR or DOR)."),
        ("UNKNOWN-IO-TYPE", "error", "Data", "Instrument", "Correct the IO type or add an approved alias rule."),
        ("IO-TYPE-CONFLICT", "warning", "Data", "Instrument", "Confirm which IO type is wired to DeltaV."),
        ("IO-TYPE2-NOTED", "info", "Data", "Instrument", "Confirm the second IO type is only the counterpart of the interface."),
        ("MISSING-CABLE", "error", "Data", "Instrument", "Provide the multipair cable number."),
        ("MISSING-PAIR", "error", "Data", "Instrument", "Provide the pair number."),
        ("DUPLICATE-PAIR", "error", "Data", "Instrument", "Give each signal its own pair."),
        ("PAIR-BEYOND-CABLE", "error", "Data", "Instrument", "Correct the pair number or the cable size."),
        ("BAD-CABLE-SIZE", "error", "Data", "Instrument", "Provide the cable size (for example 24PX1MM2...)."),
        ("CABLE-SIZE-INFERRED", "warning", "Data", "Instrument", "Confirm the inferred cable size."),
        ("CABLE-SIZE-CONFLICT", "error", "Data", "Instrument", "Use one size for all rows of a cable."),
        ("CABLE-SIZE-ROUNDED", "info", "Data", "Instrument", "No action: the non-standard size was rounded up for placement."),
        ("CABLE-TOO-LARGE", "error", "Capacity", "Engineering", "Split the cable (a CIOC holds at most 96 pairs)."),
        ("UNSUPPORTED-SEGREGATION", "error", "Segregation", "Process", "Confirm the meaning of this segregation code."),
        ("MIXED-SEGREGATION", "error", "Segregation", "Process", "Separate the A and B signals into different cables."),
        ("IS-SIGNAL-UNSUPPORTED", "error", "Scope", "Engineering", "Intrinsically safe signals need their own design; allocate them manually."),
        ("OUT-OF-SCOPE-SIGNAL", "error", "Scope", "Engineering", "IRC and MCC signals need Emerson design rules; allocate them manually."),
        ("MISSING-SIGNAL-LEVEL", "warning", "Hardware", "Electrical", "Provide the signal level; 2-Wire was assumed."),
        ("UNKNOWN-DOR-DUTY", "warning", "Hardware", "Electrical", "Confirm the digital output load; a standard output was assumed."),
        ("HIGH-CURRENT-VERIFY", "info", "Hardware", "Electrical", "Verify load, inrush current, fuse and injected power."),
        ("RTD-FIELD-SIGNAL", "warning", "Hardware", "Electrical", "RTD input was mapped to SE4303T01 per the project rule; confirm."),
        ("NO-CABINET-FOR-ROOM", "error", "Topology", "Engineering", "Add the technical room to the topology."),
        ("TOPOLOGY-INFERRED", "warning", "Topology", "Engineering", "Confirm the inferred cabinet and controller names."),
        ("GROUP-SPANS-ROOMS", "error", "Topology", "Engineering", "Confirm the technical room of the cables that share logic."),
        ("CABINET-AUTO-ADDED", "warning", "Capacity", "Engineering", "Confirm the additional cabinet and its alarms."),
        ("AFFINITY-SPLIT", "warning", "Capacity", "Engineering", "Confirm the cables of one logic group may span cabinets."),
        ("SEGREGATION-PREFERENCE-RELAXED", "info", "Segregation", "Process", "No action: the hard A/B rule is still met."),
        ("FUTURE-SPACE-MISS", "error", "Capacity", "Engineering", "Add a cabinet: the 10% future space could not be kept."),
        ("CAPACITY-OVERFLOW", "error", "Capacity", "Engineering", "Add cabinets or enable auto-expansion."),
        ("PIN-UNSATISFIABLE", "warning", "Capacity", "Engineering", "Choose another CIOC for this cable."),
        ("ALARM-UNKNOWN-KIND", "error", "Topology", "Electrical", "Use the -T, -AC or -DC tag suffix for cabinet alarms."),
        ("NO-CABINET-FOR-ALARM", "error", "Topology", "Electrical", "Correct the equipment (cabinet) name of the alarm."),
        ("ALARM-OVERFLOW", "error", "Topology", "Electrical", "A cabinet can take at most 12 alarms on its alarm baseplate."),
        ("ALARMS-MISSING-FOR-CABINET", "warning", "Topology", "Electrical", "Add the diagnostic alarm rows for this cabinet."),
        ("SPARE-SHORTFALL", "error", "Spares", "Engineering", "Add spare pairs or a spare cable to reach the 10% wired spares."),
        ("SECTION-UNDERIVABLE", "info", "Data", "Instrument", "No action: Section / Sub Unit was left as '-'."),
        ("TEMPLATE-FALLBACK", "warning", "Output", "System", "The bundled template was used."),
        ("TEMPLATE-EXTRA-COLUMN", "info", "Output", "System", "No action: the extra template column was filled with '-'."),
        ("TEMPLATE-COLUMN-MISSING", "warning", "Output", "System", "The template has no such column; it was dropped."),
        ("OUTPUT-FALLBACK-CSV", "warning", "Output", "System", "The Excel file could not be verified; a CSV copy was written instead."),
        ("OVERRIDE-APPLIED", "info", "Override", "Engineering", "No action: the engineer's answer was applied."),
        ("OVERRIDE-NO-MATCH", "warning", "Override", "Engineering", "Check the tag in the answer file."),
        ("OVERRIDE-INVALID", "warning", "Override", "Engineering", "Correct the answer value."),
        ("REV-A-UNPARSEABLE", "warning", "Revision", "Engineering", "Positions were not pinned; the revisions were only compared."),
        ("REVISION-AMBIGUOUS", "warning", "Revision", "Engineering", "A tag appears twice in one revision; the first was kept."),
        ("INTERNAL", "error", "System", "System", "Download the support bundle and report this."),
    ]


CATALOGUE: dict[str, TQSpec] = {
    tq_id: TQSpec(sev, cat, owner, res) for tq_id, sev, cat, owner, res in _rows()
}

# Question text used when the caller gives no specific message. {ref} = tag / cable / cabinet.
MESSAGES: dict[str, str] = {
    "UNREADABLE-FILE": "The file could not be opened as an Excel or CSV table. Can you upload it again?",
    "UNSUPPORTED-FORMAT": "This looks like an old .xls file. Can you save it as .xlsx and upload it again?",
    "FILE-TOO-LARGE": "The file is larger than 50 MB. Can you split it?",
    "TOO-MANY-ROWS": "The file has more than 200,000 rows. Can you split it?",
    "MISSING-COLUMN": "No column was found for {ref}. Which column holds it?",
    "COLUMN-FUZZY-MATCHED": "The column for {ref} was guessed from a similar header. Is that right?",
    "MULTI-SHEET-USED": "More than one sheet looks like an MDB. Do all of them belong to this project?",
    "DELETED-IN-MDB": "Tag {ref} is marked DELETED, so it was left out of the allocation.",
    "BLANK-TAG": "A row has no tag number ({ref}). What is the tag?",
    "DUPLICATE-TAG": "Tag {ref} appears more than once. Which row is correct?",
    "MISSING-IO-TYPE": "Tag {ref} has no IO type. Is it AIR, AOR, DIR or DOR?",
    "UNKNOWN-IO-TYPE": "Tag {ref} has an IO type the tool does not know. Which of AIR, AOR, DIR or DOR is it?",
    "IO-TYPE-CONFLICT": "Tag {ref} lists two IO types that are not a normal pair. Which one is wired to DeltaV?",
    "IO-TYPE2-NOTED": "{ref} list a second IO type. Only the first type was allocated; is the second just the other end of the interface?",
    "MISSING-CABLE": "Tag {ref} has no cable number. Which multipair cable carries it?",
    "MISSING-PAIR": "Tag {ref} has no pair number. Which pair carries it?",
    "DUPLICATE-PAIR": "Tag {ref} shares a cable pair with another signal. Which pair is correct?",
    "PAIR-BEYOND-CABLE": "Tag {ref} uses a pair number that does not exist in its cable. Is the pair or the cable size wrong?",
    "BAD-CABLE-SIZE": "Cable {ref} has no readable size. What is its pair count?",
    "CABLE-SIZE-INFERRED": "Cable {ref} has no size, so one was inferred from its highest pair number. Is that right?",
    "CABLE-SIZE-CONFLICT": "Cable {ref} is listed with different sizes. Which size is correct?",
    "CABLE-SIZE-ROUNDED": "Cable {ref} has a non-standard size, so it was rounded up to fit whole baseplates.",
    "CABLE-TOO-LARGE": "Cable {ref} has more than 96 pairs, which is more than one CIOC can take. Can it be split?",
    "UNSUPPORTED-SEGREGATION": "Tag {ref} has a segregation code the tool does not know. What does it mean?",
    "MIXED-SEGREGATION": "Cable {ref} carries both A and B signals. Can they move to separate cables?",
    "IS-SIGNAL-UNSUPPORTED": "Tag {ref} is intrinsically safe, which is out of scope for this tool. Who will allocate it?",
    "OUT-OF-SCOPE-SIGNAL": "Tag {ref} is an IRC or MCC signal, which is out of scope for this tool. Who will allocate it?",
    "MISSING-SIGNAL-LEVEL": "Tag {ref} has no signal level, so 2-Wire was assumed. Is that right?",
    "UNKNOWN-DOR-DUTY": "Tag {ref} is a digital output with no load description, so a standard output was assumed. What does it drive?",
    "HIGH-CURRENT-VERIFY": "Cable {ref} carries high-current outputs. Have the load, inrush current, fuse and injected power been checked?",
    "RTD-FIELD-SIGNAL": "Tag {ref} is an RTD input, but the project rule maps analog inputs to SE4303T01. Is that right?",
    "NO-CABINET-FOR-ROOM": "Technical room {ref} has no cabinet in the topology. Which cabinets serve it?",
    "TOPOLOGY-INFERRED": "Cabinets for technical room {ref} were inferred from names. Are they correct?",
    "GROUP-SPANS-ROOMS": "Cables that share logic with {ref} sit in different technical rooms. Which room is right?",
    "CABINET-AUTO-ADDED": "Cabinet {ref} was added because the existing ones were full. Is that acceptable?",
    "AFFINITY-SPLIT": "The cables of one logic group ({ref}) had to be split across cabinets. Is that acceptable?",
    "SEGREGATION-PREFERENCE-RELAXED": "Cable {ref} went to its second-choice CIOC pair. The A/B rule is still met.",
    "FUTURE-SPACE-MISS": "Cabinet {ref} has less than the required future space. Can another cabinet be added?",
    "CAPACITY-OVERFLOW": "Cable {ref} did not fit in any cabinet. Can cabinets be added?",
    "PIN-UNSATISFIABLE": "Cable {ref} could not be placed where you asked without breaking a rule. Which other CIOC can it use?",
    "ALARM-UNKNOWN-KIND": "Alarm {ref} does not end in -T, -AC or -DC. Which alarm is it?",
    "NO-CABINET-FOR-ALARM": "Alarm {ref} names a cabinet that is not in the topology. Which cabinet is it?",
    "ALARM-OVERFLOW": "Cabinet {ref} has more than 12 alarms for its single alarm baseplate. Which can be dropped?",
    "ALARMS-MISSING-FOR-CABINET": "No diagnostic alarm rows were found for {ref}. Can you add them?",
    "SPARE-SHORTFALL": "{ref} has too few free pairs for the 10% wired spares. Can spare pairs or a spare cable be added?",
    "SECTION-UNDERIVABLE": "Section / Sub Unit could not be worked out for some tags and was left as '-'.",
    "TEMPLATE-FALLBACK": "The template file could not be read, so the bundled template was used.",
    "TEMPLATE-EXTRA-COLUMN": "The template has a column ({ref}) this tool does not produce; it was filled with '-'.",
    "TEMPLATE-COLUMN-MISSING": "The template has no column for {ref}, so that data was left out.",
    "OUTPUT-FALLBACK-CSV": "The Excel output could not be verified ({ref}), so a CSV copy was written.",
    "OVERRIDE-APPLIED": "The engineer's answer for {ref} was applied.",
    "OVERRIDE-NO-MATCH": "An answer was given for tag {ref}, but no such tag exists. Is the tag spelled correctly?",
    "OVERRIDE-INVALID": "The answer for {ref} is not allowed. Can you correct it?",
    "REV-A-UNPARSEABLE": "Revision A could not be mapped to the cabinets, so positions were not pinned.",
    "REVISION-AMBIGUOUS": "Tag {ref} appears twice in one revision. Which row is correct?",
    "INTERNAL": "The tool hit an unexpected problem in {ref}. Please download the support bundle and report it.",
}


@dataclass(frozen=True)
class TQ:
    tq_id: str
    severity: str
    category: str
    owner: str
    ref: str          # what it is about: a tag, cable, cabinet, column ...
    message: str      # the question to the engineer
    resolution: str   # the suggested fix


class TQLog:
    """Collects TQs in the order they are raised. add() never raises."""

    def __init__(self) -> None:
        self._items: list[TQ] = []

    def add(self, tq_id: str, ref: str = "", message: str | None = None) -> TQ:
        spec = CATALOGUE.get(tq_id)
        ref = "" if ref is None else str(ref)
        if spec is None:  # unknown id: keep the run going, record it as INTERNAL
            spec = CATALOGUE["INTERNAL"]
            text = f"Unknown TQ id '{tq_id}' for {ref}." + (f" {message}" if message else "")
            tq = TQ("INTERNAL", spec.severity, spec.category, spec.owner, ref, text, spec.resolution)
        else:
            if message is None:
                template = MESSAGES.get(tq_id, spec.resolution)
                message = template.replace("{ref}", ref if ref else "(none)")
            tq = TQ(tq_id, spec.severity, spec.category, spec.owner, ref, str(message), spec.resolution)
        self._items.append(tq)
        return tq

    def extend(self, tqs: Iterable[TQ]) -> None:
        self._items.extend(tqs)

    def items(self) -> list[TQ]:
        return list(self._items)

    def __iter__(self) -> Iterator[TQ]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def has(self, tq_id: str) -> bool:
        return any(t.tq_id == tq_id for t in self._items)

    def of(self, tq_id: str) -> list[TQ]:
        return [t for t in self._items if t.tq_id == tq_id]

    def has_once(self, tq_id: str, ref: str) -> bool:
        """True if this (id, ref) was already logged - used for 'once per cable' TQs."""
        return any(t.tq_id == tq_id and t.ref == ref for t in self._items)

    def count_by_severity(self) -> dict[str, int]:
        counts = {"error": 0, "warning": 0, "info": 0}
        for t in self._items:
            counts[t.severity] = counts.get(t.severity, 0) + 1
        return counts
