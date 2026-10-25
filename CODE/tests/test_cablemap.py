"""Cables first on Cabinet Layout: each field cable as a bar on its CIOC and baseplate, opened into its signals."""
from io_sudoku.core import cablemap
from io_sudoku.samples import load_sample_result
from io_sudoku.ui import ui_logic


def _rows():
    return load_sample_result().rows


def test_every_cabled_channel_is_in_exactly_one_cable_bar():
    rows = _rows()
    for cabinet in ui_logic.cabinet_names(rows):
        slots = cablemap._slots(rows, cabinet)
        cabled = sum(1 for bps in slots.values() for chans in bps.values() for sl, _ in chans.values() if sl.cable != "-")
        in_bars = sum(len(it.slots) for bps in slots.values() for chans in bps.values()
                      for it in cablemap.runs_of(chans) if isinstance(it, cablemap.Run))
        assert cabled == in_bars > 0


def test_a_cable_over_two_baseplates_is_two_bars_with_its_pair_numbers():
    rows = _rows()
    table = cablemap.cable_table(rows, ui_logic.cabinet_names(rows))
    big = next(t for t in table if t["Cable"] == "500-CE-LP-0003-A")
    assert big["Baseplates"] == "BP 3–4" and big["CHARMs"] == "25–48" and big["Pairs"] == 24
    page = cablemap.cable_page(rows, [big["Cabinet"]])
    assert page.count('data-name="500-ce-lp-0003-a"') == 2
    assert "pairs 1–12 of 24" in page and "pairs 13–24 of 24" in page and "(1/2)" in page


def test_the_table_lists_each_cable_once_with_where_it_goes():
    rows = _rows()
    table = cablemap.cable_table(rows, ui_logic.cabinet_names(rows))
    cables = {str(r["Field Cable No"]) for r in rows if str(r.get("Field Cable No") or "-").strip() not in ("", "-", "None")}
    assert sorted(t["Cable"] for t in table) == sorted(cables)
    first = next(t for t in table if t["Cable"] == "500-CE-0013")
    assert (first["Side"], first["Baseplates"], first["Signals"], first["Wired Spares"]) == ("Front", "BP 2", 4, 2)


def test_opening_a_cable_shows_its_signals_and_each_links_to_rule_check():
    rows = _rows()
    cabinet = ui_logic.cabinet_names(rows)[0]
    page = cablemap.cable_page(rows, [cabinet])
    ours = [r for r in rows if r["Electronic/ Marshalling Cabinet"] == cabinet and r.get("Field Cable No") not in (None, "", "-")]
    assert page.count('class="detail"') == len({r["Field Cable No"] for r in ours})       # one signal list per cable
    assert page.count("<tbody><tr") == page.count('class="detail"')
    assert page.count('<tr data-slot="') == len(ours)                                      # every pair, clickable
    assert "__iosgCell" in page and "hidden" in page                                       # closed until clicked


def test_text_is_escaped():
    rows = [dict(r) for r in _rows()]
    row = next(r for r in rows if r.get("Field Cable No") == "500-CE-0013")
    row["Tag Name"] = "<script>alert(1)</script>"
    page = cablemap.cable_page(rows, [row["Electronic/ Marshalling Cabinet"]])
    assert "<script>alert(1)" not in page and "&lt;script&gt;" in page
