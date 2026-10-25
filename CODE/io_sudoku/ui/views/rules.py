"""Rules: governed rule changes.  Engineers propose, someone verifies (one button), the audit log records it all.

Two kinds of rule can be proposed: Settings (the tunable project values) and Columns And Checks (one column
with a value for each signal and the checks those values must pass; see columns.py).  Every rule shows which CHARM
signals it applies to, and Preview shows what a new pack would change in each signal before it is activated.
The locked rules cannot be changed here at all.  The AI box only drafts a proposal for the same form; it
never touches allocation and never sees your MDB data.  Long explanations sit behind the (i) icons."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import streamlit as st

from io_sudoku.core import advisor, rulechange as rc
from io_sudoku.core import suggestion as sg_mod
from io_sudoku.core.pipeline import solve
from io_sudoku.core.projectrules import project_columns
from io_sudoku.core.rulepack import LOCKED_RULES, pack_from_dict, pack_hash, pack_to_dict, project_choices, validate_pack
from io_sudoku.ui import rulescope, state, ui_logic
from io_sudoku.ui.views import addsignal, columns
from io_sudoku.ui.views._common import ask_first, heading, md_escape

SETTINGS = [k for k in rc.TEMPLATES if k not in rc.PROJECT_TEMPLATES]
GROUPS = {columns.GROUP: [], addsignal.GROUP: []}
GROUP_HELP = ("Columns And Checks is one form for one column: make a new project column (for example Voltage), give "
              "each signal its value (type them per signal, paste them, or fill many at once), and add the checks the "
              "values must pass (for example at most 24 V), each an error or a warning. Checks can also be put on a "
              "column of the allocation itself. Project columns are shown in the app and never written into the locked "
              "76-column allocation, and they never move a signal. Add A Signal puts a new signal into your file "
              "and opens it on Edit File. Engineering Settings (at the bottom, closed) change a project number such "
              "as the spare percentage.")
SETTINGS_TITLE = "Engineering Settings (advanced)"
SETTINGS_HELP = ("These change a number or a name the solver works with, for the whole project: the wired-spare "
                 "percentage per controller, the future space kept free in each cabinet, the empty baseplates at the "
                 "end, which baseplate of every cabinet holds the cabinet alarms, an extra cabinet for a room, a new name for an IO type, a segregation code, an instrument's "
                 "hardware, or a word that marks high-current loads. Unlike a project column, a setting CAN move "
                 "signals, so it is proposed, verified in the Review Queue, previewed and activated like any rule. "
                 "Most projects never need to change them.")
# the text fields of a Settings rule that are about values in the allocation get a dropdown of those values
PICK_FROM = {("instrument_profile", "instrument"): "Instrument type", ("segregation_family", "code"): "Segregation"}
ARG_LABELS = {"io": "IO Type", "match_column": "Look At Column", "match_text": "That Contains", "charm_type": "Must Use CHARM",
              "check_column": "Must Have Filled In", "column": "New Column Name", "value": "Value", "pct": "Percent",
              "alarm_cioc": "CIOC", "alarm_bp": "Baseplate"}
QUEUE, SUGGESTIONS, PREVIEW, ACTIVE = "Review Queue", "Suggested Fixes Waiting For Verification", "Preview And Activate", \
    "Project Rules And Where They Apply"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _rooms() -> list[str]:
    return ui_logic.config_for_pack(st.session_state["pack"]).known_rooms()


@st.cache_data(max_entries=4, show_spinner=False)
def _raw_io(mdb_bytes: bytes, column_text: str, pack_text: str) -> dict[str, str]:
    """{tag key: IO type exactly as written in the file} (an IO alias rule is about the written text)."""
    index = ui_logic.edit_index(mdb_bytes, column_text, pack_text)
    match = index.mapping.get("io_type")
    if match is None or match.index is None:
        return {}
    sheets = {x.name: x for x in ui_logic.editable_sheets(mdb_bytes)}
    out = {}
    for key, (sheet, row) in index.tags.items():
        values = sheets[sheet].row(row) if sheet in sheets else None
        if values is not None and match.index < len(values) and values[match.index] is not None:
            out[key] = str(values[match.index]).strip()
    return out


def _covered(template: str, args: dict) -> list[dict]:
    s = st.session_state
    result = s["result"]
    if result is None:
        return []
    raw = {}
    if template == "io_alias" and s["mdb_bytes"]:
        try:
            raw = _raw_io(s["mdb_bytes"], json.dumps(s["column_overrides"], sort_keys=True), ui_logic.pack_json(s["pack"]))
        except Exception:  # noqa: BLE001 - only the 'where it applies' table is affected
            raw = {}
    return rulescope.applies_to(template, args, result.rows, raw)


def _where_it_applies(template: str, args: dict, key: str) -> None:
    """A '👁 Where It Applies' switch: the CHARM signals this rule covers in the current allocation."""
    if not st.toggle("\U0001F441 Where It Applies", key=f"where_{key}",
                     help=f"The CHARM signals this rule covers in the current allocation: {rulescope.scope_text(template, args)}."):
        return
    if st.session_state["result"] is None:
        st.caption("Run an allocation first to see which signals this rule covers.")
        return
    rows = _covered(template, args)
    lines = rulescope.table(template, args, rows, st.session_state["result"].rows)
    broken = rulescope.broken(lines)
    st.caption(f"{len(lines):,} signals · {rulescope.scope_text(template, args)}"
               + (f" · {broken:,} break it" if broken else "") + (" · the first 500 are listed" if len(lines) >= rulescope.MAX_ROWS else ""))
    if lines:
        st.dataframe(lines, hide_index=True, width="stretch", height=min(320, 38 + 35 * len(lines)))


# --------------------------------------------------------------------------- callbacks
def _propose(template: str) -> None:
    s = st.session_state
    spec = rc.TEMPLATES[template]
    args = {a.name: s.get(f"rf_{template}_{a.name}") for a in spec.args}
    proposal, errors = rc.build_proposal(template, args, s.get("rule_author") or "", now=_now(), known_rooms=_rooms())
    if proposal is None:
        state.flash("error", " ".join(errors), "Propose A Rule")
        return
    s["proposals"] = s["proposals"] + [proposal]
    state.flash("success", f"Proposed: {proposal.statement} It waits in the Review Queue: press Verify there to accept it.", "Propose A Rule")


def _client():
    """The rule-drafting AI: Gemini when its key is set (the Helpdesk's model), else Claude, else None."""
    from io_sudoku.core.helpdesk import GeminiClient
    gemini = state.secret("GEMINI_API_KEY")
    return GeminiClient(gemini) if gemini else advisor.default_client(state.secret("ANTHROPIC_API_KEY"))


def _open_helpdesk() -> None:
    from io_sudoku.ui.views import assistant
    assistant.open_chat({"kind": "rule"})


def _draft_ai() -> None:
    s = st.session_state
    draft = advisor.draft_rule(s.get("ai_request") or "", s.get("rule_author") or "", _client(), _now(), _rooms())
    if draft.ok:
        s["proposals"] = s["proposals"] + [draft.proposal]
        state.flash("success", f"The assistant drafted: {draft.proposal.statement} It waits in the Review Queue like any other rule.",
                    "Ask The AI Assistant (optional)")
    else:
        state.flash("warning", draft.message + (" " + " ".join(draft.errors) if draft.errors else ""),
                    "Ask The AI Assistant (optional)")


def _decide(proposal_id: str, action: str) -> None:
    """Verify or reject a proposed rule: one button, no passcode (this is a prototype)."""
    s = st.session_state
    target = next((p for p in s["proposals"] if p.id == proposal_id), None)
    if target is None:
        return
    if action == "approve":
        errors = rc.verify(target, _now())
    else:
        errors = rc.dismiss(target, _now(), s.get(f"rs_{proposal_id}") or "")
    s["proposals"] = list(s["proposals"])
    state.flash("error" if errors else "success", " ".join(errors) if errors else
                ("Rule verified. Preview and activate it below to use it." if target.status == "approved" else "Rule rejected."),
                QUEUE)


def _decide_suggestion(sg_id: str, action: str) -> None:
    s = st.session_state
    target = next((x for x in s["suggestions"] if x.id == sg_id), None)
    if target is None:
        return
    if action == "approve":
        errors = sg_mod.verify(target, _now())
    else:
        errors = sg_mod.dismiss(target, _now(), s.get(f"sgrs_{sg_id}") or "")
    s["suggestions"] = list(s["suggestions"])
    if not errors:
        state.note_review(target.tq_id, target.ref, "suggestion-verified" if target.status == "approved"
                          else "suggestion-rejected", target.text + (f" (reason: {target.reason})" if target.reason else ""),
                          by=target.reviewer or "")
    state.flash("error" if errors else "success", " ".join(errors) if errors else
                ("Suggestion verified." if target.status == "approved" else "Suggestion rejected."), SUGGESTIONS)


def _decision_buttons(item_id: str, prefix: str, decide, what: str) -> None:
    """✓ Verify, and ✕ Reject behind a small pop-up (with an optional reason), side by side."""
    with st.container(horizontal=True, horizontal_alignment="right", gap="small", key=f"{prefix}buttons_{item_id}"):
        st.button("Verify", key=f"{prefix}verify_{item_id}", type="primary", icon=":material/check:",
                  on_click=decide, args=(item_id, "approve"),
                  help=f"Accept this {what}. No passcode is needed in this prototype.")
        with st.popover("Reject", icon=":material/close:", key=f"{prefix}reject_pop_{item_id}"):
            st.text_input("Reason (optional)", key=f"{prefix}rs_{item_id}", autocomplete="off")
            st.button(f"Reject This {what.title()}", key=f"{prefix}reject_{item_id}", on_click=decide,
                      args=(item_id, "reject"))


def _preview() -> None:
    s = st.session_state
    if not s["mdb_bytes"]:
        state.flash("error", "Upload an MDB or load the sample data first, so the impact can be measured.", PREVIEW)
        return
    cfg_now = ui_logic.config_for_pack(s["pack"])
    new_pack = rc.apply_approved(s["pack"], s["proposals"], cfg_now)
    if pack_hash(new_pack) == pack_hash(s["pack"]):
        state.flash("warning", "There is no verified rule to apply yet.", PREVIEW)
        return
    before = solve(s["mdb_bytes"], cfg_now, "00", column_overrides=s["column_overrides"])
    after = solve(s["mdb_bytes"], ui_logic.config_for_pack(new_pack), "00", column_overrides=s["column_overrides"])
    s["rule_preview"] = {"pack": new_pack, "diff": rc.row_diff_summary(before.rows, after.rows),
                         "before": before.readiness.status, "after": after.readiness.status,
                         "changes": rulescope.signal_changes(before.rows, after.rows),
                         "new_tqs": [(t.tq_id, t.ref, t.message) for t in after.tqs
                                     if t.tq_id in ("PROJECT-RULE-BROKEN", "PROJECT-CHECK-ERROR")]}


def _activate() -> None:
    s = st.session_state
    preview = s["rule_preview"]
    if preview and s.get("activate_ok"):
        s["pack"] = preview["pack"]
        s["rule_preview"] = None
        state.mark_stale()
        state.flash("success", f"Rule pack {s['pack'].name} v{s['pack'].version} is now active. Re-allocate to use it.", PREVIEW)
    else:
        state.flash("error", "Tick “I understand” to activate the new rule pack.", PREVIEW)


def _import_pack() -> None:
    s = st.session_state
    up = s.get("pack_uploader")
    if up is None:
        return
    try:
        pack = pack_from_dict(json.loads(up.getvalue()))
    except ValueError:
        state.flash("error", "That file is not a rule pack. Download one from this page and try again.", "Rule Pack And Audit Log")
        return
    problems = validate_pack(pack)
    if problems:
        state.flash("error", " ".join(problems), "Rule Pack And Audit Log")
        return
    s["pack"] = pack
    state.mark_stale()
    state.flash("success", f"Rule pack {pack.name} v{pack.version} loaded. Re-allocate to use it.", "Rule Pack And Audit Log")


# -------------------------------------------------------------------------------- view
def render() -> None:
    s = st.session_state
    st.header("Rules", help="Engineers propose rules from fixed forms, someone verifies them in the Review Queue "
                            "(one Verify button), then they are previewed and activated as a new rule-pack version. "
                            "Every step is in the audit log. The locked rules can never be changed.")
    pack = s["pack"]
    with st.expander(f"Locked Rules ({len(LOCKED_RULES)}) \u00b7 they can never be changed", icon="\U0001F512"):
        st.markdown("\n".join(f"- {r}" for r in LOCKED_RULES))
    choices = project_choices(ui_logic.config_for_pack(pack).rules)
    with st.expander(f"Project Choices ({len(choices)}) \u00b7 customer specific, changeable", icon=":material/tune:"):
        st.caption("The VIT allocation guide lists these as customer-specific items, not DeltaV rules. These are the "
                   "values in force for the active pack. The ones the solver uses are changed under Engineering "
                   "Settings below (proposed, verified, previewed and activated like any rule).")
        st.markdown("\n".join(f"- {md_escape(c)}" for c in choices))
    with st.container(border=True, key="rules_pack_card"):
        a, b = st.columns([3, 2], vertical_alignment="center")
        a.markdown(f"**Active pack:** {md_escape(pack.name)} v{pack.version} · fingerprint `{pack_hash(pack)[:10]}`",
                   help="Every allocation records this fingerprint, so you can always tell which rules made it.")
        rules = list((pack.overrides or {}).get("project_rules", []))
        b.caption(f"{len(pack.params)} settings · {len(rules)} project rules (columns and constraints)")
        with st.expander("Settings Of This Pack"):
            st.dataframe([{"Setting": k, "Value": v} for k, v in sorted(pack.params.items())], hide_index=True, width="stretch")
            other = {k: v for k, v in (pack.overrides or {}).items() if k != "project_rules"}
            if other:
                st.json(other, expanded=1)
    _propose_form()
    _queue()
    _suggestions()
    _impact()
    _active_rules()
    _ai_box()
    _pack_files()


def _wording(template: str, spec: dict) -> str:
    """The rule's wording with what is typed so far (blanks shown as …)."""
    s = st.session_state
    values = {}
    for arg in spec["args"]:
        value = s.get(f"rf_{template}_{arg['name']}")
        values[arg["name"]] = value if value not in (None, "") else "…"
    try:
        return spec["statement"].format(**values)
    except (KeyError, IndexError, ValueError):
        return spec["statement"]


def _propose_form() -> None:
    s = st.session_state
    heading("Propose A Rule", GROUP_HELP)
    if s.get("rule_group") not in GROUPS:          # pressing the chosen button again clears it: keep the last
        s["rule_group"] = s.get("rule_group_last") if s.get("rule_group_last") in GROUPS else columns.GROUP
    s["rule_group_last"] = s["rule_group"]
    a, b = st.columns([1, 1.4], vertical_alignment="bottom")
    a.text_input("Your Name", key="rule_author", autocomplete="off", placeholder="Who is proposing this?…")
    with b:
        st.segmented_control("Kind Of Rule", list(GROUPS), key="rule_group", label_visibility="collapsed")
    if s["rule_group"] == columns.GROUP:
        with st.container(border=True, key="column_form_box"):
            columns.render()
    else:
        with st.container(border=True, key="add_signal_box"):
            addsignal.render()
    with st.expander(SETTINGS_TITLE, icon=":material/tune:"):
        st.caption(SETTINGS_HELP)
        _settings_form()


def _settings_form() -> None:
    s = st.session_state
    catalogue = {t["key"]: t for t in rc.template_catalogue(_rooms())}
    keys = [k for k in SETTINGS if k in catalogue]
    if s.get("rule_tpl") not in keys:
        s["rule_tpl"] = keys[0]
    with st.container(border=True, key="rule_form_box"):
        template = st.selectbox("Rule Type", keys, format_func=lambda k: catalogue[k]["label"], key="rule_tpl")
        spec = catalogue[template]
        signals = [r for r in (getattr(s["result"], "rows", None) or []) if r.get("Tag Status") in ("Field", "Cabinet Alarm")]
        cols = st.columns(min(len(spec["args"]), 4) or 1)
        for i, arg in enumerate(spec["args"]):
            key, label = f"rf_{template}_{arg['name']}", ARG_LABELS.get(arg["name"], arg["name"].replace("_", " ").title())
            with cols[i % len(cols)]:
                if arg["kind"] == "choice":
                    st.selectbox(label, arg["choices"], key=key)
                elif arg["kind"] == "int":
                    st.number_input(label, min_value=arg["lo"], max_value=arg["hi"], value=arg["lo"], step=1, key=key)
                elif (template, arg["name"]) in PICK_FROM and signals:
                    columns._picker(label, key, columns._counts(PICK_FROM[(template, arg["name"])], signals),
                                    help="The values really in the allocation, with how many signals have each. "
                                         "You can also type a new one.")
                else:
                    st.text_input(label, key=key, max_chars=arg["max_len"], autocomplete="off")
        st.markdown(f"\U0001F4DD **Wording:** {md_escape(_wording(template, spec))}",
                    help="The rule's wording is written by the tool from the form, never typed free-hand.")
        if s["result"] is not None:
            args = {a["name"]: s.get(f"rf_{template}_{a['name']}") for a in spec["args"]}
            if all(v not in (None, "") for v in args.values()):
                st.caption(f"Right now this rule would cover {len(_covered(template, args)):,} signals "
                           f"({rulescope.scope_text(template, args)}).")
        st.button("Propose Setting", key="rule_propose", type="primary", on_click=_propose, args=(template,),
                  help="It goes to the Review Queue below; it is used only after Verify and Preview And Activate.")


def _status(status: str) -> str:
    word = {"approved": "verified", "rejected": "rejected"}.get(status, "waiting for verification")
    colour = {"approved": "#3fb950", "rejected": "#ff7b72"}.get(status, "#e3b341")
    return f"<span style='color:{colour};font-weight:700'>{word}</span>"


def _queue() -> None:
    s = st.session_state
    heading(QUEUE, "Review each proposed rule here: press Verify to accept it, or Reject. Verified rules are used "
                   "only after Preview And Activate.")
    if not s["proposals"]:
        st.caption("No rules have been proposed yet.")
        return
    waiting = sum(1 for p in s["proposals"] if p.status == "pending")
    st.caption(f"{len(s['proposals']):,} proposed · {waiting:,} waiting for verification · newest first"
               + (" · scroll inside the box to see them all" if len(s["proposals"]) > 3 else ""))
    box = st.container(height=560, key="review_queue_box") if len(s["proposals"]) > 3 else st.container()
    with box:
        for p in reversed(s["proposals"]):
            _proposal_card(p)


def _proposal_card(p) -> None:
    with st.container(border=True, key=f"proposal_{p.id}"):
        box, buttons = st.columns([4, 1.6], vertical_alignment="center")
        box.markdown(f"**{md_escape(p.statement)}**  \n<small>{'AI draft' if p.source == 'ai' else 'Form'} · "
                     f"{md_escape(rc.TEMPLATES[p.template].label)} · proposed by {md_escape(p.author)} · "
                     f"{_status(p.status)}" + (f" · by {md_escape(p.reviewer)}" if p.reviewer else "") + "</small>",
                     unsafe_allow_html=True,
                     help=("Assistant's reasoning (information only): " + p.rationale) if p.rationale else None)
        if p.template == "column_rule" and (p.args or {}).get("note"):
            box.caption(f"Purpose: {p.args['note']}")
        if p.status == "pending":
            with buttons:
                _decision_buttons(p.id, "", _decide, "rule")
        elif p.status == "rejected" and p.reason:
            buttons.caption(f"Reason: {md_escape(p.reason)}")
        if not (p.template == "column_rule" and (p.args or {}).get("remove")):
            _where_it_applies(p.template, p.args, p.id)


def _suggestions() -> None:
    s = st.session_state
    items = s["suggestions"]
    if not items:
        return
    heading(SUGGESTIONS, "Suggested fixes written on the TQ Board. Press Verify to accept one, or Reject. A verified "
                         "suggestion is guidance for whoever fixes the question: it changes nothing by itself.")
    for x in items:
        with st.container(border=True, key=f"suggestion_{x.id}"):
            box, buttons = st.columns([4, 1.6], vertical_alignment="center")
            box.markdown(f"**{md_escape(x.tq_id)} · {md_escape(x.ref or '-')}**: {md_escape(x.text)}  \n"
                         f"<small>by {md_escape(x.author)} · {_status(x.status)}"
                         + (f" · by {md_escape(x.reviewer)}" if x.reviewer else "") + "</small>", unsafe_allow_html=True)
            if x.status == "pending":
                with buttons:
                    _decision_buttons(x.id, "sg", _decide_suggestion, "suggestion")


def _impact() -> None:
    s = st.session_state
    heading(PREVIEW, "Approved rules take effect only after you preview and activate them. Preview allocates your file "
                     "with and without them and lists every cell that would change, signal by signal.")
    st.button("Preview Impact Of Approved Rules", key="rule_preview_btn", on_click=_preview)
    preview = s["rule_preview"]
    if not preview:
        return
    st.markdown(f"Readiness would change from **{preview['before']}** to **{preview['after']}**.")
    changes = preview.get("changes") or []
    if preview["diff"]:
        st.dataframe([{"Column": k, "Cells Changed": v} for k, v in preview["diff"].items()], hide_index=True, width="stretch")
    else:
        st.success("No cell of the allocation would change (new columns and constraints never move a signal).")
    if changes and st.toggle(f"\U0001F441 View The Changes ({len(changes):,})", key="rule_view_changes",
                             help="Every cell that would change, signal by signal: before and after."):
        st.dataframe(changes, hide_index=True, width="stretch", height=min(420, 38 + 35 * len(changes)))
    for tq_id, ref, message in preview.get("new_tqs") or []:
        st.warning(f"{tq_id} would be raised: {message}")
    st.checkbox("I understand this replaces the active rule pack", key="activate_ok")
    st.button("Activate Rule Pack", key="rule_activate", on_click=_activate, type="primary")


def _active_rules() -> None:
    s = st.session_state
    rules = list((s["pack"].overrides or {}).get("project_rules", []))
    heading(ACTIVE, "The project columns and checks of the ACTIVE pack. Open \U0001F441 Where It Applies to see the "
                    "CHARM signals each one covers, with each signal's value and the result of each check. Edit opens "
                    "a column in the form above; Remove proposes taking it away. Project columns can be downloaded "
                    "as a CSV; they are never written into the locked allocation.")
    if not rules:
        st.caption(f"The active pack has no project columns or checks yet. Propose one above ({columns.GROUP}).")
        return
    for i, rule in enumerate(rules):
        with st.container(border=True, key=f"active_rule_{i}"):
            text, buttons = st.columns([4, 1.6], vertical_alignment="center")
            note = (rule.get("args") or {}).get("note") if rule.get("kind") == "column_rule" else ""
            text.markdown(f"**{md_escape(rule.get('statement') or rule.get('kind'))}**  \n<small>{md_escape(rc.TEMPLATES[rule['kind']].label)}"
                          f" · {md_escape(rule.get('id', ''))}</small>", unsafe_allow_html=True,
                          help=f"Purpose: {note}" if note else None)
            if rule.get("kind") in ("column_rule", "project_column"):
                with buttons, st.container(horizontal=True, horizontal_alignment="right", gap="small"):
                    st.button("Edit", key=f"active_edit_{i}", icon=":material/edit:", on_click=columns.edit_rule, args=(rule,),
                              help="Open this column in the form above to change its values or checks.")
                    ask_first(f"active_remove_{i}", "Remove", "Propose removing this column and its checks? It goes to "
                              "the Review Queue like any other rule.", columns.remove_rule, (rule, ACTIVE), yes="Propose Removal")
            _where_it_applies(rule["kind"], rule["args"], f"active_{i}")
    result = s["result"]
    with_values = [r for r in rules if r.get("kind") == "project_column" or
                   (r.get("kind") == "column_rule" and (r.get("args") or {}).get("new"))]
    if with_values and result is not None:
        lines = []
        for row in result.rows:
            values = project_columns(with_values, row)
            if values:
                lines.append({"Tag Name": row.get("Tag Name"), **values})
        if lines:
            import csv
            import io
            names = list(dict.fromkeys(k for line in lines for k in line))
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=names)
            writer.writeheader()
            writer.writerows(lines)
            st.download_button("Download Project Columns (.csv)", data=buf.getvalue().encode("utf-8-sig"), mime="text/csv",
                               file_name="Project_Columns.csv", key="dl_project_columns", on_click="ignore")


def _ai_box() -> None:
    heading("Ask The AI Assistant (optional)", "The assistant only fills in the same form. It never changes the "
                                               "allocation, and it never sees your MDB data.")
    configured = _client() is not None
    if not configured:
        st.caption("The AI assistant is switched off because no API key is set. The form above works without it.")
    st.text_area("Describe The Rule You Want", key="ai_request", max_chars=advisor.MAX_REQUEST_CHARS, disabled=not configured,
                 placeholder="For example: treat PSV valves as high-current loads…")
    with st.container(horizontal=True, gap="small"):
        st.button("Draft Rule With AI", key="ai_draft", on_click=_draft_ai, disabled=not configured)
        st.button("\U0001F4AC Talk It Through With The Helpdesk", key="rules_helpdesk", on_click=_open_helpdesk,
                  help="Opens the Helpdesk on the right to discuss which rule you need and how to word it.")


def _pack_files() -> None:
    s = st.session_state
    heading("Rule Pack And Audit Log")
    c1, c2 = st.columns(2)
    c1.download_button("Download Rule Pack (.json)", data=json.dumps(pack_to_dict(s["pack"]), indent=2, sort_keys=True),
                       file_name=f"{s['pack'].name}_v{s['pack'].version}.json", mime="application/json", key="dl_pack")
    c2.download_button("Download Audit Log (.json)", data=json.dumps(rc.audit_entries(s["proposals"]), indent=2),
                       file_name="Rule_Audit_Log.json", mime="application/json", key="dl_audit")
    v1, v2 = st.columns(2)
    if v1.toggle("View Rule Pack Here", key="rules_view_pack"):
        st.json(pack_to_dict(s["pack"]), expanded=2)
    if v2.toggle("View Audit Log Here", key="rules_view_audit"):
        st.json(rc.audit_entries(s["proposals"]), expanded=1)
    st.file_uploader("Load A Rule Pack (.json)", type=["json"], key="pack_uploader", on_change=_import_pack)
    entries = rc.audit_entries(s["proposals"])
    if entries:
        st.dataframe(entries, hide_index=True, width="stretch")
