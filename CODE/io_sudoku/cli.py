"""Command line interface:  python -m io_sudoku <command> ...

  solve MDB --out DIR [--pack P] [--rev 00] [--template T]   allocate an MDB
  revise REV_A MDB_B --out DIR [--rev B] [--pack P]          Rev B with Rev A's positions kept
  audit ALLOCATION --out DIR                                 health-check any allocation workbook
  selftest [--update-golden]                                 check the tool works here

Exit codes: 0 outputs written, 1 the input could not be read (one-line message, no traceback),
2 bad arguments.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Callable


def _read(path: str) -> bytes | None:
    try:
        return Path(path).read_bytes()
    except Exception:  # noqa: BLE001
        print(f"Cannot read the file '{path}'. Check the path and try again.")
        return None


def _pack_and_cfg(pack_path: str | None):
    from io_sudoku.core.config import load_config
    from io_sudoku.core.rulepack import apply_pack, default_pack, pack_from_dict

    pack = default_pack()
    if pack_path:
        try:
            pack = pack_from_dict(json.loads(Path(pack_path).read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            print(f"The rule pack '{pack_path}' could not be read; the default pack VIT-2026 is used.")
    return pack, apply_pack(pack, load_config())


def _write(out: Path, name: str, data: bytes | str, written: list[str]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    written.append(name)


def _common_outputs(result: Any, data: bytes, pack: Any, args: argparse.Namespace, rev: str, written: list[str]) -> dict[str, Any]:
    """Files every command writes: allocation, TQ register, parts, trace, summary, drawings, manifest."""
    from io_sudoku.core.allocio import allocation_bytes, load_template
    from io_sudoku.core.bom import parts_report_bytes
    from io_sudoku.core.elevation import elevation_html
    from io_sudoku.core.manifest import build_manifest
    from io_sudoku.core.readiness import suffix
    from io_sudoku.core.report import tq_register_bytes
    from io_sudoku.core.summary_html import build_summary_html
    from io_sudoku.core.tq import TQLog
    from io_sudoku.core.trace import trace_bytes

    out = Path(args.out)
    template = None
    if getattr(args, "template", None):
        template_bytes = _read(args.template)
        template = load_template(template_bytes, TQLog()) if template_bytes else None
    manifest = build_manifest(data, pack, result)
    status = result.readiness.status if result.readiness else "BLOCKED"
    if result.rows:
        log = TQLog()
        payload, report = allocation_bytes(result.rows, template, log)
        _write(out, f"IO_Allocation_{rev}{suffix(status)}{report.filename_ext}", payload, written)
        _write(out, "Parts_and_Cables.xlsx", parts_report_bytes(result.rows, result.cfg_used), written)
        _write(out, "Decision_Trace.xlsx", trace_bytes(result), written)
        _write(out, "Cabinet_Drawings.html", elevation_html(result.rows), written)
    _write(out, "TQ_Register.xlsx", tq_register_bytes(result.tqs, result.quarantined, None, result.assumptions), written)
    _write(out, "Summary.html", build_summary_html(result, manifest, result.readiness, result.assumptions), written)
    _write(out, "Run_Manifest.json", json.dumps(manifest, indent=2, sort_keys=True, default=str), written)
    return manifest


def _solve(args: argparse.Namespace) -> int:
    from io_sudoku.core.pipeline import solve

    data = _read(args.mdb)
    if data is None:
        return 1
    pack, cfg = _pack_and_cfg(args.pack)
    started = time.perf_counter()
    result = solve(data, cfg, args.rev)
    seconds = time.perf_counter() - started
    written: list[str] = []
    _common_outputs(result, data, pack, args, args.rev, written)
    status = result.readiness.status if result.readiness else "BLOCKED"
    print(f"{status}: {len(result.rows)} rows, {result.kpis.get('field', 0)} field signals, "
          f"{len(result.tqs)} TQs, {len(result.quarantined)} set aside, solved in {seconds:.1f} s")
    print("Written to " + str(Path(args.out)) + ": " + ", ".join(written))
    if not result.rows:
        print("Nothing could be allocated: see TQ_Register.xlsx for why.")
        return 1
    if status == "BLOCKED":
        print("Every error must be fixed before this allocation can be issued: see TQ_Register.xlsx.")
    return 0


def _rows_of_rev_a(data: bytes) -> list[dict[str, Any]]:
    from io_sudoku.core.allocio import looks_like_allocation, read_allocation
    from io_sudoku.core.workspace import import_workspace

    if data[:2] == b"PK":
        try:
            if "allocation.xlsx" in zipfile.ZipFile(BytesIO(data)).namelist():
                state, _ = import_workspace(data)
                return state.rows if state else []
        except Exception:  # noqa: BLE001
            pass
    rows = read_allocation(data)
    return rows if looks_like_allocation(rows) else []


def _revise(args: argparse.Namespace) -> int:
    from io_sudoku.core.report import impact_report_bytes
    from io_sudoku.core.redline import redline_bytes
    from io_sudoku.core.revision import solve_incremental

    a_data, b_data = _read(args.rev_a), _read(args.mdb_b)
    if a_data is None or b_data is None:
        return 1
    rows_a = _rows_of_rev_a(a_data)
    if not rows_a:
        print(f"'{args.rev_a}' is not an IO Allocation or workspace file. Check it and try again.")
        return 1
    pack, cfg = _pack_and_cfg(args.pack)
    result, report = solve_incremental(b_data, rows_a, cfg, args.rev)
    written: list[str] = []
    _common_outputs(result, b_data, pack, args, args.rev, written)
    out = Path(args.out)
    _write(out, "Revision_Impact.xlsx", impact_report_bytes(report, rows_a, result.rows), written)
    if result.rows:
        red, _ = redline_bytes(result.rows, report)
        _write(out, f"IO_Allocation_{args.rev}_REDLINE.xlsx", red, written)
    counts = report.counts
    print(f"{report.mode}: Added {counts['Added']}, Deleted {counts['Deleted']}, Moved {counts['Moved']}, "
          f"Renamed {counts['Renamed']}, unchanged {report.unchanged}")
    print("Written to " + str(out) + ": " + ", ".join(written))
    return 0 if result.rows else 1


def _audit(args: argparse.Namespace) -> int:
    from io_sudoku.core.healthcheck import audit_allocation, health_html, health_report_bytes

    data = _read(args.allocation)
    if data is None:
        return 1
    report = audit_allocation(data)
    if report.rows == 0:
        print(f"'{args.allocation}' could not be read as an IO Allocation workbook.")
        return 1
    written: list[str] = []
    out = Path(args.out)
    _write(out, "Health_Check.xlsx", health_report_bytes(report), written)
    _write(out, "Health_Check.html", health_html(report), written)
    broken = ", ".join(f"{k} x{v}" for k, v in report.by_rule.items()) or "none"
    print(f"Health score {report.score}/100; rules broken: {broken}")
    print("Written to " + str(out) + ": " + ", ".join(written))
    return 0


def _selftest(args: argparse.Namespace) -> int:
    from io_sudoku.core.pipeline import output_hash
    from io_sudoku.core.selftest import run_selftest
    from io_sudoku.samples import GOLDEN_PATH, load_sample_result

    report = run_selftest()
    for name, passed, detail in report.checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
    print(f"Self-test {'passed' if report.ok else 'FAILED'} in {report.ms} ms")
    if args.update_golden:
        result = load_sample_result()
        if result.violations or result.readiness is None or result.readiness.status != "ISSUE-READY":
            print("Not updating the golden value: the sample result is not clean.")
            return 1
        GOLDEN_PATH.write_text(output_hash(result.rows) + "\n", encoding="utf-8")
        print("Golden value updated.")
        return 0
    return 0 if report.ok else 1


COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "solve": _solve, "revise": _revise, "audit": _audit, "selftest": _selftest}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m io_sudoku", description="IO Signal Sudoku - DeltaV IO allocation solver")
    sub = parser.add_subparsers(dest="command")
    s = sub.add_parser("solve", help="allocate an MDB")
    s.add_argument("mdb"); s.add_argument("--out", required=True); s.add_argument("--pack"); s.add_argument("--rev", default="00")
    s.add_argument("--template")
    r = sub.add_parser("revise", help="Rev B with Rev A's positions kept")
    r.add_argument("rev_a"); r.add_argument("mdb_b"); r.add_argument("--out", required=True); r.add_argument("--rev", default="B")
    r.add_argument("--pack"); r.add_argument("--template")
    a = sub.add_parser("audit", help="health-check an allocation workbook")
    a.add_argument("allocation"); a.add_argument("--out", required=True)
    st = sub.add_parser("selftest", help="check the tool works in this environment")
    st.add_argument("--update-golden", action="store_true", help="re-record the golden fingerprint (deliberate only)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:          # argparse exits on bad arguments; report that as exit code 2
        return 2 if exc.code not in (0, None) else 0
    if not args.command or args.command not in COMMANDS:
        parser.print_help()
        return 2
    try:
        return COMMANDS[args.command](args)
    except Exception as exc:  # noqa: BLE001 - never show a traceback to the user
        print(f"The command stopped unexpectedly ({type(exc).__name__}). Please run `selftest` and report this.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
