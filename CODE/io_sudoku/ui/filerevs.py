"""Saved file revisions: every version of the INPUT file in this session, so any of them can be used again.

Pure logic (no widgets), like history.py.  history.py keeps every ALLOCATION; this keeps every FILE:
  * the file you uploaded (or the sample),
  * the file after each saved edit on Edit File (one revision per Save),
  * a new signal added on the Rules page,
  * the Suggested Fixed File of Preflight, once you choose to use it,
  * each Rev B MDB you compared on the Revision page.
A revision stores only a fingerprint; the bytes live once in the session's `blobs` (one copy per fingerprint).
The same file is never stored twice: saving a version that already exists only selects it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MAX_FILE_REVS = 30
KINDS = {"upload": "Uploaded", "edit": "Edited", "signal": "New signal", "suggested": "Suggested fix",
         "revision": "Rev B", "sample": "Sample"}


@dataclass
class FileRev:
    id: int
    name: str                 # 'Uploaded', 'Edit 3', 'Suggested Fix 1' ...
    kind: str                 # a key of KINDS
    file_name: str            # the file's own name (kept when it is used again)
    sha: str                  # fingerprint of the bytes (the bytes are in the session's blobs)
    origin_sha: str           # fingerprint of the file it started from (the upload), for Delete All Changes
    created: str              # display only
    note: str = ""            # what changed, in a few words
    edit_log: list[dict[str, Any]] = field(default_factory=list)   # the Your Changes list of this version

    @property
    def label(self) -> str:
        return f"{self.name} · {self.file_name} · {self.created}" + (f" · {self.note}" if self.note else "")


def next_name(revs: list[FileRev], kind: str) -> str:
    """'Uploaded', then 'Edit 1', 'Edit 2' ... per kind (numbers are never reused)."""
    base = {"upload": "Uploaded", "sample": "Sample Data", "edit": "Edit", "signal": "New Signal",
            "suggested": "Suggested Fix", "revision": "Rev B File"}.get(kind, "File")
    if kind in ("upload", "sample") and not any(r.name == base for r in revs):
        return base
    used = {r.name for r in revs}
    n = sum(1 for r in revs if r.kind == kind) + 1
    while f"{base} {n}" in used:
        n += 1
    return f"{base} {n}"


def add(revs: list[FileRev], *, kind: str, file_name: str, sha: str, origin_sha: str, created: str, note: str = "",
        edit_log: list[dict[str, Any]] | None = None, name: str | None = None) -> tuple[list[FileRev], FileRev]:
    """The list with this file version added, and the revision that holds it.  A version already in the list is not
    added again (its revision is returned).  Beyond MAX_FILE_REVS the oldest go first, but never an upload that a
    later revision started from."""
    same = next((r for r in revs if r.sha == sha), None)
    if same is not None:
        return revs, same
    rev = FileRev(id=max((r.id for r in revs), default=0) + 1, name=name or next_name(revs, kind), kind=kind,
                  file_name=file_name or "MDB", sha=sha, origin_sha=origin_sha or sha, created=created, note=note,
                  edit_log=[dict(x) for x in (edit_log or [])])
    out = list(revs) + [rev]
    while len(out) > MAX_FILE_REVS:
        origins = {r.origin_sha for r in out}
        drop = next((r for r in out if r.sha not in origins or r.kind not in ("upload", "sample")), out[0])
        out = [r for r in out if r is not drop]
    return out, rev


def change_note(edits: list[Any]) -> str:
    """'row 12 “IO Type”: AI → AIR' for one change, '5 cells changed' for more."""
    if not edits:
        return ""
    if len(edits) == 1:
        e = edits[0]
        old = "" if e.old is None else str(e.old)
        new = "" if e.new is None else str(e.new)
        return f"row {e.row} “{e.header}”: {old or '(empty)'} → {new or '(empty)'}"[:120]
    return f"{len(edits):,} cells changed"


def shas(revs: list[FileRev]) -> set[str]:
    """Every fingerprint the revisions need kept (their own files and the uploads they started from)."""
    return {r.sha for r in revs} | {r.origin_sha for r in revs}
