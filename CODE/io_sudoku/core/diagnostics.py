"""Support bundle: a zip an engineer can send us when something looks wrong.

It holds everything needed to reproduce a problem EXCEPT the customer's data: the TQs,
stage timings, private tracebacks, the configuration and rule pack that were used, and
the readiness verdict.  The original MDB is added only if the caller passes it explicitly.
"""
from __future__ import annotations

import io
import json
import zipfile
from typing import Any

from io_sudoku.core.config import config_to_dict
from io_sudoku.version import __version__


def _tq_dict(t: Any) -> dict[str, Any]:
    return {"id": t.tq_id, "severity": t.severity, "category": t.category, "owner": t.owner, "ref": t.ref,
            "message": t.message, "resolution": t.resolution}


def make_support_bundle(result: Any, input_sha256: str, pack_info: dict[str, Any] | None = None,
                        include_input: bytes | None = None) -> bytes:
    """Zip bytes with manifest, TQs, stage times, tracebacks, config, pack and readiness."""
    tracebacks = (getattr(result, "diagnostics", {}) or {}).get("tracebacks", {}) or {}
    readiness = getattr(result, "readiness", None)
    cfg = getattr(result, "cfg_used", None)
    manifest = {"tool_version": __version__, "input_sha256": input_sha256, "rows": len(getattr(result, "rows", []) or []),
                "kpis": getattr(result, "kpis", {}), "violations": len(getattr(result, "violations", []) or []),
                "quarantined": len(getattr(result, "quarantined", []) or [])}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True, default=str))
        z.writestr("tqs.json", json.dumps([_tq_dict(t) for t in getattr(result, "tqs", []) or []], indent=2))
        z.writestr("stages.json", json.dumps(getattr(result, "stages_ms", {}), indent=2, sort_keys=True))
        text = "\n\n".join(f"=== {stage} ===\n{tb}" for stage, tb in sorted(tracebacks.items())) or "No unexpected errors were recorded.\n"
        z.writestr("tracebacks.txt", text)
        z.writestr("config.json", json.dumps(config_to_dict(cfg) if cfg is not None else {}, indent=2, default=str))
        z.writestr("pack.json", json.dumps(pack_info or {}, indent=2, sort_keys=True, default=str))
        z.writestr("readiness.json", json.dumps({"status": readiness.status if readiness else "unknown",
                                                  "reasons": list(readiness.reasons) if readiness else []}, indent=2))
        if include_input is not None:
            z.writestr("input.xlsx", include_input)
    return buf.getvalue()
