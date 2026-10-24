from __future__ import annotations

import io

import openpyxl
import pytest

from io_sudoku.core.allocio import build_allocation
from io_sudoku.core.healthcheck import audit_allocation, health_html, health_report_bytes, scorecard
from io_sudoku.core.pipeline import solve


@pytest.fixture(scope="module")
def human(alloc_path):
    return audit_allocation(alloc_path)


@pytest.fixture(scope="module")
def machine(mdb_path):
    return solve(mdb_path)


def test_the_human_sample_is_red_on_the_spare_rule(human):
    assert human.rows == 1152 and len(human.cabinets) == 3
    assert human.by_rule["V10"] >= 1 and human.score < 100
    short = [x for x in human.spare_table if x["Status"] == "SHORT"]
    assert any(x["Controller"] == "P30DPK320102" and x["IO Type"] == "AIR" for x in short)
    assert human.status_counts["Field"] == 177 and human.status_counts["Wired Spare"] == 22


def test_the_score_formula(human):
    errors = [v for v in human.violations if v.severity == "error"]
    warning_rules = {v.rule for v in human.violations if v.severity == "warning"}
    expected = 100 - 15 * len({v.rule for v in errors}) - 3 * len(warning_rules) - min(25, len(errors) // 4)
    assert human.score == max(0, min(100, expected))


def test_our_own_output_audits_perfectly(machine):
    data, _ = build_allocation(machine.rows)
    r = audit_allocation(data)
    assert r.by_rule == {} and r.score == 100 and all(x["Status"] == "OK" for x in r.spare_table)
    assert all(f["Future space %"] >= 10 and f["Empty end baseplates"] >= 3 for f in r.future_space)


def test_scorecard_has_the_eight_metrics(human, machine):
    card = scorecard(human, machine, 0.8)
    assert [c["Metric"] for c in card] == ["Rules broken", "Total violations", "Wired-spare compliance (%)", "Cabinets used",
                                           "Lowest future space (%)", "Fewest empty end baseplates", "TQs raised", "Time taken"]
    by = {c["Metric"]: c for c in card}
    assert by["Rules broken"]["Human allocation"] == "V10" and by["Rules broken"]["IO Sudoku"] == "none"
    assert by["Wired-spare compliance (%)"]["IO Sudoku"] == 100.0 and by["Wired-spare compliance (%)"]["Human allocation"] < 100
    assert by["Time taken"]["IO Sudoku"] == "0.8 s" and by["TQs raised"]["Human allocation"] == "-"


@pytest.mark.parametrize("junk", [b"garbage", b"", b"PK\x03\x04junk"])
def test_garbage_gives_an_empty_report_not_an_exception(junk):
    r = audit_allocation(junk)
    assert r.rows == 0 and r.score == 0 and r.notes
    assert health_html(r) and health_report_bytes(r)


def test_workbook_and_html(human, machine):
    card = scorecard(human, machine, 1.0)
    wb = openpyxl.load_workbook(io.BytesIO(health_report_bytes(human, card)))
    assert wb.sheetnames == ["Summary", "Violations", "Spares", "Future Space", "Scorecard"]
    html = health_html(human, card)
    assert "Human vs IO Sudoku" in html and "V10" in html
    for forbidden in ("http", "<script", "<link"):
        assert forbidden not in html


def test_html_escapes_text(human):
    human2 = audit_allocation(b"x")
    human2.notes.append("<script>alert(1)</script>")
    assert "<script" not in health_html(human2) and "&lt;script&gt;" in health_html(human2)
