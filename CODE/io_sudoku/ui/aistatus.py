"""The live status of a Helpdesk answer: an animated icon, the step it is on, what it is looking at, and a timer.

Pure logic (it only builds HTML and CSS).  Everything moves with CSS in the browser - the icons, the shimmer, the
label swap and even the ticking timer (a CSS counter) - so it costs the server nothing and never lags: the server
only sends a new status when the step really changes, and a re-drawn timer carries on from the right second.

The steps are real, never decoration:
  thinking / researching / analyzing  the model's OWN thought summaries as they arrive (core.helpdesk.ask_stream);
                                      the label follows the summary's first word, the detail is the summary title
  writing                             the answer text is arriving
  done / error                        'Worked for 4s' / 'Failed after 25s'
"""
from __future__ import annotations

from html import escape

STATES = ("thinking", "researching", "analyzing", "writing", "done", "error")
LABELS = {"thinking": "Thinking", "researching": "Researching", "analyzing": "Analyzing", "writing": "Writing"}
_PHASES = (
    ("researching", ("research", "search", "look", "check", "review", "read", "find", "locat", "examin", "investigat",
                     "explor", "gather", "consult", "scan", "recall", "retriev")),
    ("analyzing", ("analy", "assess", "evaluat", "compar", "calculat", "interpret", "consider", "determin", "weigh",
                   "diagnos", "verif", "reason", "understand", "clarif", "identif", "map", "connect", "trac", "pinpoint")),
    ("writing", ("draft", "writ", "formulat", "structur", "compos", "craft", "phras", "summar", "outlin", "prepar",
                 "finaliz", "refin", "polish", "respond", "answer")),
)

# points along the wave at eased arc length, so the pen tip stays on the ink as it draws (from the design)
_WAVE_X = (3, 3.05, 3.18, 3.42, 3.78, 4.42, 5.26, 5.83, 6.29, 6.84, 7.76, 8.67, 9.22, 9.68, 10.25, 11.09, 11.72, 12.09,
           12.33, 12.46, 12.5)
_WAVE_Y = (19, 18.88, 18.58, 18.1, 17.51, 17, 17.36, 18.25, 19.29, 20.33, 21.02, 20.32, 19.27, 18.24, 17.35, 17, 17.52,
           18.11, 18.6, 18.9, 19)
_WAVE_P = (0, 0.007, 0.028, 0.061, 0.104, 0.156, 0.216, 0.282, 0.352, 0.425, 0.5, 0.575, 0.648, 0.718, 0.784, 0.844,
           0.896, 0.939, 0.972, 0.993, 1)
_DRAW_END, _HOLD_END = 0.7, 0.85


def phase(title: str) -> str:
    """The step a thought summary is about, from its first word ('Checking the cable' -> researching)."""
    first = (str(title or "").strip().split() or [""])[0].casefold()
    for name, stems in _PHASES:
        if any(first.startswith(stem) for stem in stems):
            return name
    return "thinking"


def elapsed_text(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s}s" if s < 60 else f"{s // 60}m {s % 60:02d}s"


def _wave_keyframes() -> str:
    """The pen and the ink of the 'writing' icon, drawn together (keyframes made from the design's points)."""
    pen, ink = [], []
    last = len(_WAVE_P) - 1
    for i, (x, y, p) in enumerate(zip(_WAVE_X, _WAVE_Y, _WAVE_P)):
        at = round(i / last * _DRAW_END * 100, 2)
        pen.append(f"{at}%{{transform:translate({x}px,{y}px)}}")
        ink.append(f"{at}%{{stroke-dashoffset:{round(1 - p, 3)};opacity:1}}")
    pen.append(f"{_HOLD_END * 100}%{{transform:translate({_WAVE_X[-1]}px,{_WAVE_Y[-1]}px)}}")
    pen.append(f"100%{{transform:translate({_WAVE_X[0]}px,{_WAVE_Y[0]}px)}}")
    ink.append(f"{_HOLD_END * 100}%{{stroke-dashoffset:0;opacity:1}}")
    ink.append("100%{stroke-dashoffset:0;opacity:0}")
    return "@keyframes aist-pen{" + "".join(pen) + "}@keyframes aist-ink{" + "".join(ink) + "}"


CSS = """
@property --aist-t{syntax:'<integer>';inherits:false;initial-value:0}
@property --aist-m{syntax:'<integer>';inherits:false;initial-value:0}
@property --aist-s{syntax:'<integer>';inherits:false;initial-value:0}
.aist{display:flex;align-items:center;gap:8px;min-height:32px;font-size:14px;color:#e6edf3;line-height:1.2}
.aist-icon{position:relative;display:flex;flex:0 0 20px;width:20px;height:20px;align-items:center;justify-content:center;
  color:#9a99a6;animation:aist-icon-in .55s cubic-bezier(.34,1.56,.64,1) both}
.aist-icon svg{width:18px;height:18px;overflow:visible}
.aist-icon svg *{transform-box:fill-box;transform-origin:center}
.aist-row{display:flex;align-items:center;gap:6px;min-width:0;white-space:nowrap;overflow:hidden}
.aist-label,.aist-detail{animation:aist-swap .5s cubic-bezier(.2,.9,.3,1.12) both}
.aist-label{font-weight:600}
.aist-detail{color:rgba(154,153,166,.8);font-weight:500;overflow:hidden;text-overflow:ellipsis;max-width:230px}
.aist[data-active] .aist-label{background:linear-gradient(90deg,#9a99a6 40%,#ffffff 50%,#9a99a6 60%);
  background-size:250% 100%;-webkit-background-clip:text;background-clip:text;color:transparent;
  animation:aist-swap .5s cubic-bezier(.2,.9,.3,1.12) both,aist-shine 1.6s linear infinite}
.aist:not([data-active]) .aist-label{color:#9a99a6}
.aist[data-state=error] .aist-label{color:#ff7b72}
.aist-timer{color:rgba(154,153,166,.75);font-weight:500;font-variant-numeric:tabular-nums;
  --aist-m:calc((var(--aist-t) - 30) / 60);--aist-s:calc(var(--aist-t) - var(--aist-m) * 60);
  counter-reset:aist-m var(--aist-m) aist-s var(--aist-s);
  animation:aist-count 3600s steps(3600,end) var(--aist-from,0s) both}
.aist-timer .aist-short::after{content:counter(aist-s) "s"}
.aist-timer .aist-long::after{content:counter(aist-m) "m " counter(aist-s,decimal-leading-zero) "s"}
.aist-timer .aist-short,.aist-timer .aist-long{display:inline-block;overflow:hidden;vertical-align:bottom}
.aist-timer .aist-short{animation:aist-hide 1ms step-end var(--aist-minute,60s) both}
.aist-timer .aist-long{max-width:0;animation:aist-show 1ms step-end var(--aist-minute,60s) both}
@keyframes aist-count{from{--aist-t:0}to{--aist-t:3600}}
@keyframes aist-hide{to{max-width:0}}
@keyframes aist-show{to{max-width:8em}}
@keyframes aist-shine{from{background-position:100% 0}to{background-position:0% 0}}
@keyframes aist-swap{from{opacity:0;transform:translateY(8px);filter:blur(4px)}to{opacity:1;transform:none;filter:none}}
@keyframes aist-icon-in{from{opacity:0;transform:scale(.5) rotate(-30deg);filter:blur(4px)}
  to{opacity:1;transform:none;filter:none}}
@keyframes aist-spark{0%{transform:rotate(0) scale(1)}50%{transform:rotate(45deg) scale(.8)}100%{transform:rotate(90deg) scale(1)}}
@keyframes aist-twinkle{0%,100%{transform:scale(.4);opacity:.3}50%{transform:scale(1);opacity:1}}
@keyframes aist-orbit{0%{transform:translate(0,-2px)}25%{transform:translate(2px,0)}50%{transform:translate(0,2px)}
  75%{transform:translate(-2px,0)}100%{transform:translate(0,-2px)}}
@keyframes aist-bar{0%,100%{transform:scaleY(.45)}50%{transform:scaleY(1)}}
@keyframes aist-tick{from{stroke-dashoffset:1}to{stroke-dashoffset:0}}
@keyframes aist-shake{0%,100%{transform:translateX(0)}20%{transform:translateX(-3px)}40%{transform:translateX(3px)}
  60%{transform:translateX(-2px)}80%{transform:translateX(2px)}}
@keyframes aist-dot{0%,100%{transform:scale(1);opacity:1}50%{transform:scale(.7);opacity:.5}}
""" + _wave_keyframes() + """
.aist .spark{animation:aist-spark 2.4s ease-in-out infinite alternate}
.aist .twinkle{animation:aist-twinkle 1.2s ease-in-out infinite}
.aist .lens{animation:aist-orbit 2s linear infinite}
.aist .bar{transform-origin:50% 100%!important;animation:aist-bar .9s ease-in-out infinite}
.aist .bar:nth-child(2){animation-delay:.15s}.aist .bar:nth-child(3){animation-delay:.3s}
.aist .ink{stroke-dasharray:1 2;animation:aist-ink 2.4s linear infinite}
.aist .pen{transform-box:view-box!important;transform-origin:0 0!important;animation:aist-pen 2.4s linear infinite}
.aist .tick{stroke-dasharray:1 2;animation:aist-tick .6s cubic-bezier(.3,0,.2,1) .1s both}
.aist .cross{animation:aist-shake .45s ease .1s both}
.aist .dot{animation:aist-dot 1.2s ease-in-out infinite}
.aist.static *,.aist.static{animation:none!important}
.aist.static .aist-label{background:none!important;color:#9a99a6!important}
.aist-log{margin:0 0 4px}
.aist-log summary{list-style:none;cursor:pointer;width:fit-content;border-radius:6px}
.aist-log summary::-webkit-details-marker{display:none}
.aist-log summary:focus-visible{outline:2px solid rgba(154,153,166,.5);outline-offset:2px}
.aist-log ol{margin:2px 0 6px 28px;padding:0;color:#9a99a6;font-size:13px;line-height:1.5}
@media (prefers-reduced-motion:reduce){
  .aist-icon,.aist-label,.aist-detail,.aist .spark,.aist .twinkle,.aist .lens,.aist .bar,.aist .ink,.aist .pen,
  .aist .tick,.aist .cross,.aist .dot{animation:none!important}
  .aist[data-active] .aist-label{animation:none!important;background:none;color:#9a99a6}
  .aist .ink,.aist .tick{stroke-dashoffset:0}
}
"""

_STROKE = 'fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"'
_PEN = ("M3.78181 16.3092L3 21L7.69086 20.2182C8.50544 20.0825 9.25725 19.6956 9.84119 19.1116L20.4198 8.53288C21.1934 "
        "7.75922 21.1934 6.5049 20.4197 5.73126L18.2687 3.58024C17.495 2.80658 16.2406 2.80659 15.4669 3.58027L4.88841 "
        "14.159C4.30447 14.7429 3.91757 15.4947 3.78181 16.3092Z")
_ICONS = {
    "thinking": ('<svg viewBox="0 0 24 24"><path class="spark" fill="currentColor" d="M11 5Q12 12 19 13Q12 14 11 21Q10 14 '
                 '3 13Q10 12 11 5Z"/><path class="twinkle" fill="currentColor" d="M18 2Q18.4 4.6 21 5Q18.4 5.4 18 8Q17.6 '
                 '5.4 15 5Q17.6 4.6 18 2Z"/></svg>'),
    "researching": (f'<svg viewBox="0 0 24 24"><g class="lens"><circle {_STROKE} cx="10.5" cy="10.5" r="5.5" '
                    f'stroke-width="2.25"/><path {_STROKE} d="M14.75 14.75L19 19" stroke-width="2.5"/></g></svg>'),
    "analyzing": (f'<svg viewBox="0 0 24 24"><g><line class="bar" {_STROKE} x1="6" x2="6" y1="6" y2="19" stroke-width="3"/>'
                  f'<line class="bar" {_STROKE} x1="12" x2="12" y1="6" y2="19" stroke-width="3"/>'
                  f'<line class="bar" {_STROKE} x1="18" x2="18" y1="6" y2="19" stroke-width="3"/></g></svg>'),
    "writing": (f'<svg viewBox="0 0 24 24"><g transform="translate(-1.2 -2)"><path class="ink" pathLength="1" {_STROKE} '
                f'stroke-width="2.25" d="M3 19C4.11 16.3 5.06 16.3 6.17 19C7.27 21.7 8.22 21.7 9.33 19C10.44 16.3 11.39 '
                f'16.3 12.5 19"/><g class="pen"><path fill="currentColor" transform="scale(0.66) translate(-3 -21)" '
                f'd="{_PEN}"/></g></g></svg>'),
    "done": f'<svg viewBox="0 0 24 24"><path class="tick" pathLength="1" {_STROKE} stroke-width="2.5" d="M5 12.5L10 17.5L19 7"/></svg>',
    "error": (f'<svg viewBox="0 0 24 24" style="color:#ff7b72"><path class="cross" {_STROKE} stroke-width="2.5" '
              f'd="M7 7L17 17M17 7L7 17"/></svg>'),
}
_DOT = '<svg viewBox="0 0 24 24"><circle class="dot" cx="12" cy="12" r="5" fill="currentColor"/></svg>'


def status_html(state: str, detail: str = "", elapsed: float | None = None, *, static: bool = False) -> str:
    """One status line.  Active states (thinking ... writing) shimmer and show a timer that starts at `elapsed`
    seconds and keeps ticking in the browser; done/error show 'Worked for 4s' / 'Failed after 4s'.  `static` = no
    movement at all (for answers in the history)."""
    active = state not in ("done", "error")
    secs = None if elapsed is None else max(0, int(elapsed))
    if state == "done":
        label = f"Worked for {elapsed_text(secs)}" if secs is not None else "Done"
    elif state == "error":
        label = f"Failed after {elapsed_text(secs)}" if secs is not None else "Failed"
    else:
        label = LABELS.get(state, state.title())
    icon = _ICONS.get(state, _DOT)
    detail_html = f'<span class="aist-detail" title="{escape(detail)}">{escape(detail)}</span>' if detail else ""
    timer = ""
    if active and secs is not None:
        # a negative start makes the CSS clock carry on from the right second when the status is re-drawn
        timer = (f'<span class="aist-timer" aria-hidden="true" style="--aist-from:-{secs}s;--aist-minute:{60 - secs}s">'
                 '<span class="aist-short"></span><span class="aist-long"></span></span>')
    flags = (" data-active" if active else "")
    return (f'<div class="aist{" static" if static else ""}" role="status" aria-live="polite" data-state="{escape(state)}"'
            f'{flags}><span class="aist-icon" aria-hidden="true">{icon}</span><span class="aist-row">'
            f'<span class="aist-label">{escape(label)}</span>{detail_html}{timer}</span></div>')


def timer_html(start: float = 0) -> str:
    """The ticking clock on its own, drawn ONCE when an answer starts: changing the step never re-draws it, so it never
    jumps (the server and the browser never have to agree on the time).  `start` = seconds already gone."""
    secs = max(0, int(start))
    return (f'<div class="aist" data-active><span class="aist-timer" aria-hidden="true" style="--aist-from:-{secs}s;'
            f'--aist-minute:{60 - secs}s"><span class="aist-short"></span><span class="aist-long"></span></span></div>')


def history_html(seconds: float | None, steps: list[str] | None, ok: bool = True) -> str:
    """The quiet line above an earlier answer: 'Worked for 4s', which opens to the steps the model thought through."""
    line = status_html("done" if ok else "error", "", seconds, static=True)
    if not steps:
        return line
    items = "".join(f"<li>{escape(s)}</li>" for s in steps)
    return f'<details class="aist-log"><summary>{line}</summary><ol>{items}</ol></details>'
