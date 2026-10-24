"""Workspace snapshot: the tool's memory on hosts that have no disk.

A workspace is ONE zip holding the allocation, the rule pack, the engineer answers, the
cable pins and a manifest.  Download it at the end of a session, upload it next time, and
it works anywhere a Rev A allocation is accepted - the revision engine can pin Rev B to it.
import_workspace never raises: a damaged file returns (None, 'reason in plain words').
"""
from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass, field
from typing import Any

from io_sudoku.core.allocio import build_allocation, read_allocation
from io_sudoku.core.overrides import Override, overrides_from_json, overrides_to_json
from io_sudoku.core.pipeline import output_hash
from io_sudoku.core.rulepack import RulePack, default_pack, pack_from_dict, pack_to_dict
from io_sudoku.version import __version__

_FIXED_TIME = (2020, 1, 1, 0, 0, 0)       # fixed so the same state always gives the same bytes


@dataclass
class WorkspaceState:
    rows: list[dict[str, Any]] = field(default_factory=list)
    pack: RulePack = field(default_factory=default_pack)
    overrides: list[Override] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)
    rev_label: str = "00"
    pins: dict[str, tuple[str, int]] = field(default_factory=dict)


def export_workspace(result: Any, pack: RulePack, overrides: list[Override], pins: dict[str, tuple[str, int]],
                     mdb_sha256: str, rev_label: str) -> bytes:
    """Zip bytes holding everything needed to continue this project later."""
    rows = list(getattr(result, "rows", []) or [])
    allocation, _ = build_allocation(rows)
    readiness = getattr(result, "readiness", None)
    manifest = {"tool_version": __version__, "mdb_sha256": mdb_sha256, "rev_label": rev_label, "rows": len(rows),
                "output_sha256": output_hash(rows), "readiness": readiness.status if readiness else "unknown"}
    tqs = [{"id": t.tq_id, "severity": t.severity, "ref": t.ref, "message": t.message}
           for t in getattr(result, "tqs", []) or []]
    members = {
        "allocation.xlsx": allocation,
        "pack.json": json.dumps(pack_to_dict(pack), indent=2, sort_keys=True).encode("utf-8"),
        "overrides.json": overrides_to_json(overrides).encode("utf-8"),
        "pins.json": json.dumps({k: [v[0], v[1]] for k, v in sorted(pins.items())}, indent=2).encode("utf-8"),
        "manifest.json": json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"),
        "tqs.json": json.dumps(tqs, indent=2).encode("utf-8"),
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(zipfile.ZipInfo(name, _FIXED_TIME), data)
    return buf.getvalue()


def import_workspace(data: bytes) -> tuple[WorkspaceState | None, str]:
    """(state, '') for a good workspace, or (None, reason) for anything else. Never raises."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = set(z.namelist())
            missing = [n for n in ("allocation.xlsx", "pack.json", "manifest.json") if n not in names]
            if missing:
                return None, "This is not a workspace file: it is missing " + ", ".join(missing) + "."
            rows = read_allocation(z.read("allocation.xlsx"))
            if not rows:
                return None, "The workspace contains no allocation rows."
            manifest = json.loads(z.read("manifest.json"))
            pack = pack_from_dict(json.loads(z.read("pack.json")))
            overrides = overrides_from_json(z.read("overrides.json")) if "overrides.json" in names else []
            pins: dict[str, tuple[str, int]] = {}
            if "pins.json" in names:
                for key, value in dict(json.loads(z.read("pins.json"))).items():
                    pins[str(key)] = (str(value[0]), int(value[1]))
            return WorkspaceState(rows, pack, overrides, dict(manifest), str(manifest.get("rev_label", "00")), pins), ""
    except zipfile.BadZipFile:
        return None, "This file is not a valid workspace (it is not a zip file)."
    except Exception as exc:  # noqa: BLE001
        return None, f"The workspace could not be read ({type(exc).__name__}). Please export it again."
