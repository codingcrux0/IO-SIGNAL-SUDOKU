"""Run manifest: the fingerprint of one run, so 'same input, same output' can be PROVEN.

It records the SHA-256 of the input file, the rule pack that was used, the engineer answers
and pins, and the SHA-256 of the output rows.  Two runs with the same input and rules always
produce the same output_sha256.  The creation time is stored for humans but is never part of
any hash.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from io_sudoku.core.pipeline import output_hash
from io_sudoku.core.rulepack import RulePack, pack_hash
from io_sudoku.version import __version__


def build_manifest(input_bytes: bytes, pack: RulePack, result: Any) -> dict[str, Any]:
    """Everything needed to reproduce and verify a run."""
    rows = list(getattr(result, "rows", []) or [])
    kpis = dict(getattr(result, "kpis", {}) or {})
    readiness = getattr(result, "readiness", None)
    return {
        "tool_version": __version__,
        "input_sha256": hashlib.sha256(input_bytes or b"").hexdigest(),
        "pack_name": pack.name, "pack_version": pack.version, "pack_hash": pack_hash(pack),
        "overrides_sha256": kpis.get("overrides_sha256", ""), "pins_sha256": kpis.get("pins_sha256", ""),
        "rows": len(rows), "readiness": readiness.status if readiness else "unknown",
        "kpis": kpis, "output_sha256": output_hash(rows),
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
