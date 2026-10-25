"""Project-wide constants for the IO Signal Sudoku solver.

Everything here is a plain fact taken from CLAUDE_RULES.md or from the audited
sample files. Keeping the numbers in ONE place means a reader can check them
against the rulebook in a minute, and no other module has to repeat them.
"""
from __future__ import annotations

# --- Physical hierarchy (CLAUDE_RULES section 3A) ---------------------------------
# A marshalling cabinet holds 4 CIOCs, each CIOC holds 8 baseplates, each baseplate
# holds 12 channels (CHARM slots).  4 x 8 x 12 = 384 slots per cabinet.
SLOTS_PER_BP = 12
BPS_PER_CIOC = 8
CIOCS_PER_CAB = 4
SLOTS_PER_CIOC = SLOTS_PER_BP * BPS_PER_CIOC          # 96
SLOTS_PER_CAB = SLOTS_PER_CIOC * CIOCS_PER_CAB        # 384

# The cabinet-alarm baseplate: ONE baseplate of every marshalling cabinet is kept for Cabinet Alarms.  Which one is a
# PROJECT CHOICE, not a DeltaV rule (the VIT guide: "the first baseplate of each marshalling cabinet was reserved for
# cabinet alarms. This is a project choice"), so it is a rule-pack setting (RulesCfg.alarm_cioc / alarm_bp).  These
# are this project's defaults: CIOC 1, baseplate 1 (CLAUDE_RULES section 3D.1).
ALARM_CIOC = 1
ALARM_BP = 1
ALARM_SLOTS = SLOTS_PER_BP                            # one baseplate: 12 channels of alarms at most

# --- Tag status values (the "Tag Status" column) ----------------------------------
STATUS_FIELD = "Field"
STATUS_ALARM = "Cabinet Alarm"
STATUS_WIRED = "Wired Spare"
STATUS_SLOT = "Spare Slot"

# --- IO types ---------------------------------------------------------------------
IO_TYPES = ("AIR", "AOR", "DIR", "DOR")
# The customer MDB is messy: it uses AI/AO/DI/DO as well as AIR/AOR/DIR/DOR.
BUILTIN_IO_ALIASES = {
    "AI": "AIR", "AO": "AOR", "DI": "DIR", "DO": "DOR",
    "AIR": "AIR", "AOR": "AOR", "DIR": "DIR", "DOR": "DOR",
}
# "I/O Type Name 2" holds the other end of a third-party interface (e.g. DI + DO).
COUNTERPART_PAIRS = frozenset({("DIR", "DOR"), ("AIR", "AOR")})

# --- Hardware profiles (see data/catalog.json) -------------------------------------
PROFILES = ("AIR_2W", "AIR_4W", "AIR_RTD", "AOR", "DIR", "DOR_T01", "DOR_T02")
SPARE_DESC = {"AIR": "SPARE AI", "AOR": "SPARE AO", "DIR": "SPARE DI", "DOR": "SPARE DO"}

# --- Cables -----------------------------------------------------------------------
STANDARD_CABLE_SIZES = (6, 12, 24, 36, 48, 72, 96)
MAX_CABLE_PAIRS = 96                                  # one CIOC = 96 channels

# --- Safety limits (graceful failure instead of a hang) -----------------------------
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_DATA_ROWS = 200_000
MAX_CABINETS = 200
FAST_WRITE_THRESHOLD = 5000                           # above this use the streaming writer

SEVERITIES = ("error", "warning", "info")
REVISION_CATEGORIES = ("Added", "Deleted", "Moved", "Renamed")
