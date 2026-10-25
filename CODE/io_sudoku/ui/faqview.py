"""An earlier Helpdesk conversation shown as questions and answers: tap a question, its answer springs open.

Pure logic: it builds one small self-contained page (HTML, CSS and a few lines of JavaScript) that the Helpdesk shows
in a frame.  Opening and closing an answer happens entirely in the browser - no re-run of the app - so it is instant.
Read-only: it shows what was said; it never asks the AI again.

Safe by construction: every word of a question or an answer is HTML-escaped first; only **bold**, *italics*, `code`
and simple lists are then turned into tags.  Links, images and raw HTML in an answer are shown as plain text.
"""
from __future__ import annotations

import re
from html import escape
from typing import Any

ACCENT = "#1f6feb"           # the answer bubble (white text on it is easy to read)
HEIGHT = 440                 # px of the frame; a longer log scrolls inside it

_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])|(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])")
_CODE = re.compile(r"`([^`]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_BULLET = re.compile(r"^\s*[-*•]\s+(.*)$")
_NUMBER = re.compile(r"^\s*\d+[.)]\s+(.*)$")


def _inline(text: str) -> str:
    text = _LINK.sub(r"\1", text)
    safe = escape(text)
    safe = _CODE.sub(r"<code>\1</code>", safe)
    safe = _BOLD.sub(r"<strong>\1</strong>", safe)
    return _ITALIC.sub(lambda m: f"<em>{m.group(1) or m.group(2)}</em>", safe)


def safe_markdown(text: str) -> str:
    """A small, safe subset of markdown as HTML: paragraphs, line breaks, bullet and numbered lists, bold, italics."""
    out: list[str] = []
    para: list[str] = []
    kind: str | None = None
    items: list[str] = []

    def flush_para() -> None:
        if para:
            out.append("<p>" + "<br>".join(_inline(x) for x in para) + "</p>")
            para.clear()

    def flush_list() -> None:
        nonlocal kind
        if items:
            out.append(f"<{kind}>" + "".join(f"<li>{_inline(x)}</li>" for x in items) + f"</{kind}>")
            items.clear()
        kind = None
    for line in str(text or "").replace("\r\n", "\n").split("\n"):
        bullet, number = _BULLET.match(line), _NUMBER.match(line)
        if bullet or number:
            flush_para()
            want = "ul" if bullet else "ol"
            if kind != want:
                flush_list()
                kind = want
            items.append((bullet or number).group(1))
        elif not line.strip():
            flush_para()
            flush_list()
        else:
            flush_list()
            para.append(line.strip())
    flush_para()
    flush_list()
    return "".join(out) or "<p></p>"


def pairs(messages: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """(question, answer) of a conversation, in order; a question with no answer yet gets a note."""
    out: list[tuple[str, str]] = []
    question: str | None = None
    for m in messages or []:
        if m.get("role") == "user":
            if question is not None:
                out.append((question, "No answer was given to this question."))
            question = str(m.get("text") or "")
        elif question is not None:
            out.append((question, str(m.get("text") or "")))
            question = None
    if question is not None:
        out.append((question, "No answer was given to this question."))
    return out


# a 3 x 3 Sudoku grid: the Helpdesk's own mark
_MARK = ('<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden="true">'
         + "".join(f'<rect x="{3 + c * 6.5}" y="{3 + r * 6.5}" width="5" height="5" rx="1.4" '
                   f'opacity="{1 if (r + c) % 2 == 0 else 0.45}"/>' for r in range(3) for c in range(3)) + "</svg>")

_PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
:root{color-scheme:dark;--accent:@ACCENT@}
html,body{margin:0;padding:0;background:transparent}
body{font:15px/1.4 "Source Sans Pro","Source Sans 3",system-ui,-apple-system,"Segoe UI",sans-serif;color:#e6edf3;
  overflow-y:auto;overscroll-behavior:contain;-webkit-font-smoothing:antialiased}
.faq{display:flex;flex-direction:column;padding:4px 6px 18px}
.q{align-self:flex-start;max-width:85%;margin-top:12px;border:0;cursor:pointer;text-align:left;font:inherit;
  letter-spacing:-.01em;color:#e6edf3;background:#262626;border-radius:18px 18px 18px 6px;padding:10px 16px;
  transition:background-color .2s ease,box-shadow .2s ease,transform .15s ease;-webkit-tap-highlight-color:transparent}
.q:first-child{margin-top:4px}
.q:hover{background:#2e2e2e}
.q:active{transform:scale(.97)}
.q[aria-expanded=true]{background:#333}
.q:focus-visible{outline:none;box-shadow:0 0 0 2px rgba(134,133,147,.55)}
.wrap{display:grid;grid-template-rows:0fr;transition:grid-template-rows .4s cubic-bezier(.2,.8,.2,1)}
.wrap.open{grid-template-rows:1fr}
.inner{min-height:0;overflow:hidden}
.a{display:flex;align-items:flex-end;justify-content:flex-end;gap:8px;padding-top:10px;opacity:0;
  transform:translateY(12px) scale(.6);transform-origin:100% 100%;
  transition:opacity .16s cubic-bezier(.4,0,1,1),transform .16s cubic-bezier(.4,0,1,1)}
.wrap.open .a{opacity:1;transform:none;transition:opacity .25s ease,transform .42s cubic-bezier(.34,1.56,.64,1)}
.bubble{max-width:85%;background:var(--accent);color:#fff;border-radius:18px 18px 6px 18px;padding:10px 16px;
  line-height:1.45;letter-spacing:-.01em;overflow-wrap:anywhere}
.bubble p{margin:0 0 .5em}.bubble p:last-child{margin:0}
.bubble ul,.bubble ol{margin:.2em 0 .5em 1.2em;padding:0}.bubble li{margin:.15em 0}
.bubble code{background:rgba(255,255,255,.18);border-radius:4px;padding:0 4px;font-size:.92em}
.avatar{flex:0 0 32px;width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;
  background:rgba(255,255,255,.07);color:var(--accent);box-shadow:0 12px 32px -12px rgba(0,0,0,.5)}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
</style></head><body><div class="faq" id="faq">@ITEMS@</div><script>
(function () {
  var root = document.getElementById("faq");
  var questions = Array.prototype.slice.call(root.querySelectorAll(".q"));
  function close(q) {
    q.setAttribute("aria-expanded", "false");
    document.getElementById(q.getAttribute("aria-controls")).classList.remove("open");
  }
  function toggle(q) {
    var open = q.getAttribute("aria-expanded") === "true";
    questions.forEach(close);
    if (open) { return; }
    q.setAttribute("aria-expanded", "true");
    var wrap = document.getElementById(q.getAttribute("aria-controls"));
    wrap.classList.add("open");
    setTimeout(function () {
      var box = wrap.getBoundingClientRect();
      if (box.bottom > window.innerHeight) {
        wrap.scrollIntoView({block: "nearest", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"});
      }
    }, 420);
  }
  var steps = {ArrowDown: function (i) { return i + 1; }, ArrowUp: function (i) { return i - 1; },
               Home: function () { return 0; }, End: function (i, last) { return last; }};
  root.addEventListener("click", function (e) {
    var q = e.target.closest(".q");
    if (q) { toggle(q); }
  });
  root.addEventListener("keydown", function (e) {
    var step = steps[e.key];
    if (!step || !e.target.classList.contains("q")) { return; }
    e.preventDefault();
    var next = step(questions.indexOf(e.target), questions.length - 1);
    questions[(next + questions.length) % questions.length].focus();
  });
})();
</script></body></html>"""


def faq_page(messages: list[dict[str, Any]], accent: str = ACCENT) -> str:
    """The page for one earlier conversation (empty string when it has no question yet)."""
    items = []
    for i, (question, answer) in enumerate(pairs(messages)):
        items.append(f'<button type="button" class="q" id="q{i}" aria-expanded="false" aria-controls="a{i}">'
                     f'{escape(question)}</button>'
                     f'<div class="wrap" id="a{i}" role="region" aria-labelledby="q{i}"><div class="inner"><div class="a">'
                     f'<div class="bubble">{safe_markdown(answer)}</div><span class="avatar">{_MARK}</span></div></div></div>')
    if not items:
        return ""
    safe_accent = accent if re.fullmatch(r"#[0-9a-fA-F]{6}", accent or "") else ACCENT
    return _PAGE.replace("@ACCENT@", safe_accent).replace("@ITEMS@", "".join(items))
