from __future__ import annotations

import io

import openpyxl
import pytest

from io_sudoku.core import allocio
from io_sudoku.core.allocio import (
    CANONICAL_COLUMNS, TemplateSpec, build_allocation, load_template, read_allocation, rows_to_dataframe,
    write_allocation,
)
from io_sudoku.core.tq import TQLog


@pytest.fixture(scope="module")
def sample(alloc_path):
    return read_allocation(alloc_path)


def test_canonical_columns():
    assert len(CANONICAL_COLUMNS) == 76
    assert CANONICAL_COLUMNS[0] == "Sr. No." and CANONICAL_COLUMNS[-1] == "Section / Sub Unit"
    assert "\n" in CANONICAL_COLUMNS[72] and "\n" in CANONICAL_COLUMNS[73]
    assert CANONICAL_COLUMNS == allocio._FALLBACK_COLUMNS            # built-in copy matches the file


def test_sample_reads_1152_rows_with_all_columns(sample):
    assert len(sample) == 1152
    assert all(list(r) == CANONICAL_COLUMNS for r in sample)
    assert sample[0]["Tag Name"] == "320-EJA  -01001-T"             # internal spaces kept
    assert all(v != " -" for r in sample for v in r.values())        # ' -' quirk normalised


def test_round_trip_is_exact(sample):
    data, report = build_allocation(sample)
    assert report.path_kind == "template" and report.verified and report.rows == 1152
    assert read_allocation(data) == sample


def test_short_row_is_padded_and_zero_rows_work():
    data, report = build_allocation([{"Tag Name": "X-1", "Channel_No": 3}])
    back = read_allocation(data)
    assert len(back) == 1 and back[0]["Tag Name"] == "X-1" and back[0]["Channel_No"] == 3
    assert back[0]["Remarks"] == "-" and list(back[0]) == CANONICAL_COLUMNS
    data, report = build_allocation([])
    assert report.verified and read_allocation(data) == []
    wb = openpyxl.load_workbook(io.BytesIO(data))
    assert wb.worksheets[0].max_column == 76


def test_large_output_uses_streaming_writer(sample):
    rows = [dict(sample[i % 1152], **{"Sr. No.": i + 1}) for i in range(6000)]
    data, report = build_allocation(rows)
    assert report.path_kind == "write_only" and report.verified
    back = read_allocation(data)
    assert len(back) == 6000 and back[5999]["Sr. No."] == 6000


def _template_bytes(headers):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "IO Assignment"
    ws.append(headers)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_79_column_template_with_odd_headers(sample):
    headers = list(CANONICAL_COLUMNS)
    headers[2] = "Tag\nName"                                         # line break in a header
    headers[10] = "LOCATION"                                         # different case
    headers += ["Extra A", "Extra B", "Extra C"]
    log = TQLog()
    spec = load_template(_template_bytes(headers), log)
    assert spec.source == "uploaded" and len(spec.columns) == 79
    data, report = build_allocation(sample[:20], spec, log)
    assert report.verified and sorted(report.filled_columns) == ["Extra A", "Extra B", "Extra C"]
    wb = openpyxl.load_workbook(io.BytesIO(data))
    ws = wb.worksheets[0]
    assert ws.max_column == 79
    assert ws.cell(2, 3).value == sample[0]["Tag Name"] and ws.cell(2, 11).value == sample[0]["Location"]
    assert [ws.cell(2, c).value for c in (77, 78, 79)] == ["-", "-", "-"]
    assert len(log.of("TEMPLATE-EXTRA-COLUMN")) == 3
    assert read_allocation(data, spec)[0]["Tag Name"] == sample[0]["Tag Name"]


def test_template_missing_columns_are_dropped_with_a_warning(sample):
    headers = [h for h in CANONICAL_COLUMNS if h not in ("Remarks", "Loop Name")]
    log = TQLog()
    spec = load_template(_template_bytes(headers), log)
    _, report = build_allocation(sample[:5], spec, log)
    assert sorted(report.dropped_columns) == ["Loop Name", "Remarks"]
    assert len(log.of("TEMPLATE-COLUMN-MISSING")) == 2 and report.verified


def test_plus_minus_header_pairs_are_not_merged(sample):
    rows = [dict(sample[0])]
    rows[0]["Relay Contact (+)"], rows[0]["Relay Contact (-)"] = "plus", "minus"
    rows[0][CANONICAL_COLUMNS[72]], rows[0][CANONICAL_COLUMNS[73]] = "tbplus", "tbminus"
    back = read_allocation(build_allocation(rows)[0])[0]
    assert (back["Relay Contact (+)"], back["Relay Contact (-)"]) == ("plus", "minus")
    assert (back[CANONICAL_COLUMNS[72]], back[CANONICAL_COLUMNS[73]]) == ("tbplus", "tbminus")


def test_garbage_template_falls_back_to_bundled():
    for junk in (b"garbage", b"", b"PK\x03\x04broken"):
        log = TQLog()
        spec = load_template(junk, log)
        assert spec.source == "bundled" and len(spec.columns) == 76 and log.has("TEMPLATE-FALLBACK")
    assert load_template(None).source == "bundled"


def test_formula_text_is_stored_as_text(sample):
    rows = [dict(sample[0], **{"Tag Name": '=HYPERLINK("http://x")'})]
    data, _ = build_allocation(rows)
    assert read_allocation(data)[0]["Tag Name"] == '=HYPERLINK("http://x")'
    ws = openpyxl.load_workbook(io.BytesIO(data)).worksheets[0]
    assert ws.cell(2, 3).data_type == "s"
    data_b, report = build_allocation([dict(rows[0])] * 1, None)
    big, rep = build_allocation([dict(rows[0])] * 6000)
    assert rep.path_kind == "write_only"
    ws = openpyxl.load_workbook(io.BytesIO(big), read_only=True).worksheets[0]
    first = next(ws.iter_rows(min_row=2, max_row=2))
    assert first[2].value == '=HYPERLINK("http://x")' and first[2].data_type == "s"


def test_writer_ladder_falls_back_when_a_writer_corrupts_output(sample, monkeypatch):
    real = allocio._write_xlsx_template

    def corrupt(table, template):
        return real(table[:-1], template)          # silently drops the last row

    monkeypatch.setattr(allocio, "_write_xlsx_template", corrupt)
    data, report = build_allocation(sample[:30])
    assert report.path_kind == "write_only" and report.verified
    assert len(read_allocation(data)) == 30


def test_everything_failing_ends_in_csv(sample, monkeypatch):
    def boom(table, template):
        raise RuntimeError("boom")

    monkeypatch.setattr(allocio, "_write_xlsx_template", boom)
    monkeypatch.setattr(allocio, "_write_xlsx_stream", boom)
    log = TQLog()
    rows = [dict(sample[0], **{"Tag Name": "=cmd"}), dict(sample[1])]
    data, report = build_allocation(rows, None, log)
    assert report.path_kind == "csv" and report.filename_ext == ".csv" and report.content_type == "text/csv"
    assert log.has("OUTPUT-FALLBACK-CSV")
    text = data.decode("utf-8-sig")
    assert text.splitlines()[0].startswith("Sr. No.,Revision No,Tag Name")
    assert "'=cmd" in text                                   # formula neutralised
    assert len(read_allocation(data)) == 2


def test_unwritable_target_never_raises(sample, tmp_path):
    log = TQLog()
    report = write_allocation(sample[:3], tmp_path / "no_such_dir" / "x.xlsx", None, log)
    assert report.verified is False and log.has("OUTPUT-FALLBACK-CSV")
    good = tmp_path / "ok.xlsx"
    report = write_allocation(sample[:3], good)
    assert report.verified and len(read_allocation(good)) == 3
    buf = io.BytesIO()
    assert write_allocation(sample[:3], buf).verified and len(read_allocation(buf.getvalue())) == 3


def test_reader_never_raises():
    assert read_allocation(b"x") == []
    assert read_allocation(b"") == []
    assert read_allocation(b"PK\x03\x04junk") == []
    assert read_allocation("/definitely/not/here.xlsx") == []
    assert read_allocation(12345) == []        # type: ignore[arg-type]


def test_dataframe_is_object_typed(sample):
    df = rows_to_dataframe(sample[:5])
    assert list(df.columns) == CANONICAL_COLUMNS and len(df) == 5
    assert all(str(t) == "object" for t in df.dtypes)
