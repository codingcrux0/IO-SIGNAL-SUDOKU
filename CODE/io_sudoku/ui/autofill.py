"""Type-ahead for every search and text box: while you type, the rest of the best match appears in faint grey
right after your letters (press Tab or → to take it), and a short list of other matches opens under the box
(click one, or use ↑ ↓ and Enter).  Dropdowns (select boxes) get the same faint completion from their own list.

How it works, without any server round trip while typing:
  * a view calls offer(key, values) for a text box: the values it can complete (tags, cables, IO types, names ...);
  * at the end of the run render() writes every list into one tiny invisible frame, which hands them to a small
    script installed ONCE in the app page (like the links listener in nav.py);
  * that script draws the faint text and the list on top of the box.  Taking a suggestion types it into the
    box exactly as if you had typed it, so the box works as before (Enter or leaving it still applies it).
The suggestion is only ever shown, never applied by itself.  Lite Mode keeps it (it has no animation).
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

import streamlit as st

RUN_KEY = "_autofill"
MAX_ITEMS = 4000
MAX_LEN = 120


def begin() -> None:
    """Start of a run: no lists yet (each view offers the ones for the boxes it draws)."""
    st.session_state[RUN_KEY] = {}


def offer(key: str, values: Iterable[Any], sep: str | None = None) -> None:
    """Complete the text box with this widget key from `values` (most useful first).  `sep` = the box takes several
    values separated by this character (only the part after the last one is completed)."""
    try:
        seen: dict[str, None] = {}
        for v in values:
            text = str(v).strip() if v is not None else ""
            if text and text not in ("-", "None") and len(text) <= MAX_LEN:
                seen.setdefault(text, None)
                if len(seen) >= MAX_ITEMS:
                    break
        if seen:
            lists = st.session_state.setdefault(RUN_KEY, {})
            lists[key] = {"items": list(seen), "sep": sep or ""}
    except Exception:  # noqa: BLE001 - a missing suggestion list never breaks a page
        pass


def page(lists: dict[str, Any]) -> str:
    """The invisible frame: hands the lists to the page script (installing it the first time)."""
    data = json.dumps(lists, ensure_ascii=True, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e")
    return (SCRIPT.replace("__LISTS__", data))


def _rows() -> list[dict[str, Any]]:
    result = st.session_state.get("result")
    return list(getattr(result, "rows", None) or [])


def tags() -> list[str]:
    """Every tag of the allocation on screen (signals first, in the allocation's order)."""
    rows = _rows()
    return [str(r.get("Tag Name")) for r in rows if r.get("Tag Status") in ("Field", "Cabinet Alarm")] + \
        [str(r.get("Tag Name")) for r in rows if r.get("Tag Status") not in ("Field", "Cabinet Alarm")]


def column(name: str) -> list[str]:
    """The values of one allocation column, most common first."""
    from collections import Counter
    counts = Counter(str(r.get(name)).strip() for r in _rows() if str(r.get(name) or "").strip() not in ("", "-", "None"))
    return [v for v, _ in counts.most_common()]


def names() -> list[str]:
    """The names people already used in this session (proposals, review decisions, notes)."""
    s = st.session_state
    out = [str(p.author) for p in s.get("proposals") or []] + [str(r.get("author")) for r in s.get("signal_requests") or []]
    out += [str(e.by) for e in reversed(s.get("review_log") or []) if getattr(e, "by", "")]
    out += [str(n.get("by")) for n in (s.get("tq_notes") or {}).values() if isinstance(n, dict) and n.get("by")]
    out += [str(s.get(k)) for k in ("rule_author", "note_by", "answer_by", "assistant_by") if s.get(k)]
    return [x for x in dict.fromkeys(out) if x and x not in ("None", "Reviewer")]


UNITS = ("V", "VDC", "VAC", "mV", "mA", "A", "°C", "°F", "bar", "barg", "psi", "kPa", "MPa", "Hz", "kHz", "W", "kW",
         "s", "ms", "min", "m", "mm", "%", "m3/h", "t/h", "kg/h", "rpm", "Ω")


def render() -> None:
    """End of the run (in the sidebar): one frame with every list offered in this run."""
    lists = st.session_state.get(RUN_KEY) or {}
    st.iframe(page(lists), height=1)


# The code is run ONCE in the app page's own realm (guard __iosgFill1), so it keeps working while this frame is
# reloaded; every frame load only replaces the lists.
SCRIPT = r"""<!DOCTYPE html><html><body><script type="text/plain" id="code">
var css = d.createElement('style');
css.textContent = '.iosg-ghost{position:fixed;z-index:999990;pointer-events:none;white-space:pre;overflow:hidden;' +
  'color:transparent;background:transparent}' +
  '.iosg-ghost b{font-weight:inherit;color:rgba(139,148,158,.55)}' +
  '.iosg-sugg{position:fixed;z-index:999991;margin:0;padding:4px;list-style:none;background:#161b22;' +
  'border:1px solid #30363d;border-radius:8px;box-shadow:0 8px 24px rgba(1,4,9,.55);max-height:232px;overflow:auto;' +
  'font-size:14px;color:#c9d1d9}' +
  '.iosg-sugg li{padding:6px 10px;border-radius:6px;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}' +
  '.iosg-sugg li.on,.iosg-sugg li:hover{background:#1f6feb33;color:#e6edf3}' +
  '.iosg-sugg li span{color:#8b949e}' +
  '.iosg-sugg .hint{padding:4px 10px 2px;font-size:11px;color:#6e7681;cursor:default}';
d.head.appendChild(css);
var ghost = d.createElement('div'); ghost.className = 'iosg-ghost'; ghost.setAttribute('aria-hidden', 'true');
var typed = d.createElement('span'), rest = d.createElement('b');
ghost.appendChild(typed); ghost.appendChild(rest);
var list = d.createElement('ul'); list.className = 'iosg-sugg'; list.setAttribute('role', 'listbox');
var state = {input: null, matches: [], on: -1, completion: '', select: false};
var hideAll = function () { ghost.remove(); list.remove(); state.matches = []; state.on = -1; state.completion = ''; };
var keyOf = function (el) {
  var box = el.closest('[class*="st-key-"]'); if (!box) return null;
  var m = /(?:^|\s)st-key-(\S+)/.exec(box.className); return m ? m[1] : null;
};
var isSelect = function (el) { return el.getAttribute('role') === 'combobox' || !!el.closest('[data-baseweb="select"]'); };
var setValue = function (el, v) {
  var set = Object.getOwnPropertyDescriptor(w.HTMLInputElement.prototype, 'value').set;
  set.call(el, v); el.dispatchEvent(new w.Event('input', {bubbles: true}));
};
var place = function (el) {
  var r = el.getBoundingClientRect(), cs = w.getComputedStyle(el);
  ['fontFamily', 'fontSize', 'fontWeight', 'letterSpacing', 'paddingLeft', 'paddingRight', 'lineHeight', 'textIndent'].forEach(function (p) { ghost.style[p] = cs[p]; });
  ghost.style.left = r.left + 'px'; ghost.style.top = r.top + 'px'; ghost.style.width = r.width + 'px'; ghost.style.height = r.height + 'px';
  ghost.style.paddingTop = cs.paddingTop; ghost.style.paddingBottom = cs.paddingBottom; ghost.style.borderLeft = cs.borderLeftWidth + ' solid transparent';
  ghost.style.boxSizing = cs.boxSizing;
  var bar = el.closest('[data-baseweb="input"],[data-baseweb="select"]') || el, br = bar.getBoundingClientRect();
  list.style.left = br.left + 'px'; list.style.top = (br.bottom + 4) + 'px'; list.style.minWidth = br.width + 'px';
  list.style.maxWidth = Math.max(br.width, 320) + 'px';
};
var token = function (value, sep) {
  if (!sep) return {head: '', part: value};
  var i = value.lastIndexOf(sep); if (i < 0) return {head: '', part: value};
  var after = value.slice(i + 1), lead = after.length - after.replace(/^\s+/, '').length;
  return {head: value.slice(0, i + 1 + lead), part: after.slice(lead)};
};
var esc = function (t) { return t.replace(/[&<>"]/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]; }); };
var findMatches = function (items, part) {
  var low = part.toLowerCase(), starts = [], inside = [];
  for (var i = 0; i < items.length && starts.length < 60; i++) {
    var t = items[i], tl = t.toLowerCase();
    if (tl === low) continue;
    if (tl.indexOf(low) === 0) starts.push(t); else if (inside.length < 30 && tl.indexOf(low) > 0) inside.push(t);
  }
  return {starts: starts, all: starts.concat(inside)};
};
var drawList = function (part) {
  list.innerHTML = '';
  if (!state.matches.length || state.select) { list.remove(); return; }
  var head = d.createElement('li'); head.className = 'hint'; head.textContent = 'Tab or → takes the grey text · ↑ ↓ and Enter pick one';
  list.appendChild(head);
  state.matches.slice(0, 8).forEach(function (m, i) {
    var li = d.createElement('li'); li.setAttribute('role', 'option'); if (i === state.on) li.className = 'on';
    var at = m.toLowerCase().indexOf(part.toLowerCase());
    li.innerHTML = at < 0 ? esc(m) : esc(m.slice(0, at)) + '<strong>' + esc(m.slice(at, at + part.length)) + '</strong><span>' + esc(m.slice(at + part.length)) + '</span>';
    li.addEventListener('mousedown', function (e) { e.preventDefault(); take(m, true); });
    list.appendChild(li);
  });
  if (!list.isConnected) d.body.appendChild(list);
};
var selectOptions = function (el) {
  var own = el && el.getAttribute('aria-controls') ? d.getElementById(el.getAttribute('aria-controls')) : null;
  var opts = own ? own.querySelectorAll('[role="option"]') : d.querySelectorAll('[role="listbox"] [role="option"]');
  var out = []; for (var i = 0; i < opts.length; i++) { var t = (opts[i].textContent || '').trim(); if (t) out.push({text: t, el: opts[i]}); }
  return out;
};
var update = function (el) {
  state.input = el; state.select = isSelect(el);
  var value = el.value || '', items = null, sep = '';
  if (state.select) {
    items = selectOptions(el);
  } else {
    var entry = (w.__iosgFillLists || {})[keyOf(el)];
    if (!entry) { hideAll(); return; }
    items = entry.items; sep = entry.sep;
  }
  var t = token(value, sep);
  if (!t.part || (el.selectionStart !== value.length)) { hideAll(); return; }
  var low = t.part.toLowerCase(), first = null;
  if (state.select) {
    for (var i = 0; i < items.length; i++) { if (items[i].text.toLowerCase().indexOf(low) === 0 && items[i].text.length > t.part.length) { first = items[i]; break; } }
    state.matches = first ? [first.text] : []; state.option = first ? first.el : null;
    state.completion = first ? first.text.slice(t.part.length) : '';
  } else {
    var found = findMatches(items, t.part);
    state.matches = found.all; state.on = -1;
    state.completion = found.starts.length ? found.starts[0].slice(t.part.length) : '';
    state.head = t.head; state.part = t.part;
  }
  if (!state.completion && !state.matches.length) { hideAll(); return; }
  place(el);
  typed.textContent = value; rest.textContent = state.completion;
  var overflow = el.scrollWidth > el.clientWidth + 1;
  if (state.completion && !overflow) { if (!ghost.isConnected) d.body.appendChild(ghost); } else { ghost.remove(); }
  drawList(t.part);
};
var commit = function (el) {
  setTimeout(function () { el.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true})); }, 0);
};
var take = function (text, andCommit) {
  var el = state.input; if (!el) return;
  if (state.select) {
    var opt = state.option; hideAll();
    if (opt) opt.click();
    return;
  }
  setValue(el, (state.head || '') + text); hideAll();
  if (andCommit) commit(el); else update(el);
};
d.addEventListener('input', function (e) {
  var el = e.target; if (!el || el.tagName !== 'INPUT' || (el.type && el.type !== 'text' && el.type !== 'search')) return;
  setTimeout(function () { update(el); if (isSelect(el)) setTimeout(function () { if (d.activeElement === el) update(el); }, 120); }, 0);
}, true);
d.addEventListener('keydown', function (e) {
  var el = e.target; if (el !== state.input) return;
  if (e.key === 'Escape') { hideAll(); return; }
  var atEnd = el.selectionStart === (el.value || '').length;
  if ((e.key === 'Tab' && !e.shiftKey || (e.key === 'ArrowRight' && atEnd)) && state.completion && ghost.isConnected) {
    e.preventDefault(); e.stopPropagation();
    if (state.select) { take(null, false); return; }
    take((state.part || '') + state.completion, false); return;
  }
  if (state.select || !list.isConnected) return;
  var n = Math.min(state.matches.length, 8);
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    state.on = state.on < 0 ? (e.key === 'ArrowDown' ? 0 : n - 1) : (state.on + (e.key === 'ArrowDown' ? 1 : n - 1)) % n;
    drawList(state.part || ''); return;
  }
  if (e.key === 'Enter' && state.on >= 0) { e.preventDefault(); e.stopPropagation(); take(state.matches[state.on], true); }
}, true);
d.addEventListener('focusout', function (e) { if (e.target === state.input) setTimeout(function () { if (d.activeElement !== state.input) hideAll(); }, 0); }, true);
d.addEventListener('scroll', function () { if (state.input && (ghost.isConnected || list.isConnected)) place(state.input); }, true);
w.addEventListener('resize', function () { if (state.input && ghost.isConnected) place(state.input); });
</script><script>(function(){
var w, d;
try { w = window.parent; d = w.document; } catch (e) { return; }
w.__iosgFillLists = __LISTS__;
if (w.__iosgFill1) { return; }
try { (new w.Function('d', 'w', document.getElementById('code').textContent))(d, w); w.__iosgFill1 = true; } catch (e) {}
})();</script></body></html>"""
