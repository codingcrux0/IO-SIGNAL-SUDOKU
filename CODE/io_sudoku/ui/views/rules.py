"""Rules: governed rule changes.  Engineers propose, a DIFFERENT person approves, the audit log records it all.

Three kinds of rule can be proposed: Settings (the tunable project values), New Columns (a project label on
some CHARM signals) and Constraints (a check every covered signal must pass).  Every rule shows which CHARM
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
from io_sudoku.core.rulepack import LOCKED_RULES, pack_from_dict, pack_hash, pack_to_dict, validate_pack
from io_sudoku.ui import rulescope, state, ui_logic
from io_sudoku.ui.views._common import ask_first, heading, md_escape

GROUPS = {"Settings": [k for k in rc.TEMPLATES if k not in rc.PROJECT_TEMPLATES],
          "New Columns": ["project_column"], "Constraints": ["expect_hardware", "require_filled"]}
GROUP_HELP = ("Settings change a project value (spare %, an IO-type alias, a cabinet ...). New Columns put a "
              "project label on some CHARM signals; they are shown in the app and never written into the locked "
              "76-column allocation. Constraints are checks: every signal they cover is checked after each "
              "allocation, and a broken one becomes a warning to sign off. None of them can move a signal.")
ARG_LABELS = {"io": "IO Type", "match_column": "Look At Column", "match_text": "That Contains", "charm_type": "Must Use CHARM",
              "check_column": "Must Have Filled In", "column": "New Column Name", "value": "Value", "pct": "Percent"}
QUEUE, SUGGESTIONS, PREVIEW, ACTIVE = "Review Queue", "Suggested Fixes Waiting For Approval", "Preview And Activate", \
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
    lines = rulescope.table(template, args, rows)
    broken = sum(1 for x in lines if str(x.get("Result", "")).startswith("✗"))
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
    state.flash("success", f"Proposed: {proposal.statement} It waits for approval in the Review Queue.", "Propose A Rule")


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
        state.flash("success", f"The assistant drafted: {draft.proposal.statement} It waits for approval like any other rule.",
                    "Ask The AI Assistant (optional)")
    else:
        state.flash("warning", draft.message + (" " + " ".join(draft.errors) if draft.errors else ""),
                    "Ask The AI Assistant (optional)")


def _decide(proposal_id: str, action: str) -> None:
    s = st.session_state
    target = next((p for p in s["proposals"] if p.id == proposal_id), None)
    if target is None:
        return
    reviewer, passcode = s.get(f"rv_{proposal_id}") or "", s.get(f"pc_{proposal_id}") or ""
    secret = state.secret("APPROVER_PASSCODE")
    if action == "approve":
        errors = rc.approve(target, reviewer, passcode, secret, _now())
    else:
        if not s.get(f"ok_{proposal_id}"):
            state.flash("error", "Tick “I understand” before rejecting a rule.", QUEUE)
            return
        errors = rc.reject(target, reviewer, s.get(f"rs_{proposal_id}") or "", passcode, secret, _now())
    state.flash("error" if errors else "success", " ".join(errors) if errors else
                f"Rule {target.status}." + (" Preview and activate it below to use it." if target.status == "approved" else ""), QUEUE)


def _decide_suggestion(sg_id: str, action: str) -> None:
    s = st.session_state
    target = next((x for x in s["suggestions"] if x.id == sg_id), None)
    if target is None:
        return
    reviewer, passcode = s.get(f"sgrv_{sg_id}") or "", s.get(f"sgpc_{sg_id}") or ""
    secret = state.secret("APPROVER_PASSCODE")
    if action == "approve":
        errors = sg_mod.approve(target, reviewer, passcode, secret, _now())
    else:
        errors = sg_mod.reject(target, reviewer, s.get(f"sgrs_{sg_id}") or "", passcode, secret, _now())
    s["suggestions"] = list(s["suggestions"])
    state.flash("error" if errors else "success", " ".join(errors) if errors else f"Suggestion {target.status}.", SUGGESTIONS)


def _preview() -> None:
    s = st.session_state
    if not s["mdb_bytes"]:
        state.flash("error", "Upload an MDB or load the sample data first, so the impact can be measured.", PREVIEW)
        return
    cfg_now = ui_logic.config_for_pack(s["pack"])
    new_pack = rc.apply_approved(s["pack"], s["proposals"], cfg_now)
    if pack_hash(new_pack) == pack_hash(s["pack"]):
        state.flash("warning", "There is no approved rule to apply yet.", PREVIEW)
        return
    before = solve(s["mdb_bytes"], cfg_now, "00", column_overrides=s["column_overrides"])
    after = solve(s["mdb_bytes"], ui_logic.config_for_pack(new_pack), "00", column_overrides=s["column_overrides"])
    s["rule_preview"] = {"pack": new_pack, "diff": rc.row_diff_summary(before.rows, after.rows),
                         "before": before.readiness.status, "after": after.readiness.status,
                         "changes": rulescope.signal_changes(before.rows, after.rows),
                         "new_tqs": [(t.tq_id, t.ref, t.message) for t in after.tqs if t.tq_id == "PROJECT-RULE-BROKEN"]}


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
    st.header("Rules", help="Engineers propose rules from fixed forms, a different person approves them with the "
                            "approver passcode, then they are previewed and activated as a new rule-pack version. "
                            "Every step is in the audit log. The locked rules can never be changed.")
    pack = s["pack"]
    with st.expander(f"Locked Rules ({len(LOCKED_RULES)}) \u00b7 they can never be changed", icon="\U0001F512"):
        st.markdown("\n".join(f"- {r}" for r in LOCKED_RULES))
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
    if s.get("rule_group") not in GROUPS:
        s["rule_group"] = "Settings"
    st.segmented_control("Kind Of Rule", list(GROUPS), key="rule_group", label_visibility="collapsed")
    group = s.get("rule_group") or "Settings"
    catalogue = {t["key"]: t for t in rc.template_catalogue(_rooms())}
    keys = [k for k in GROUPS[group] if k in catalogue]
    if s.get("rule_tpl") not in keys:
        s["rule_tpl"] = keys[0]
    with st.container(border=True, key="rule_form_box"):
        a, b = st.columns(2)
        a.text_input("Your Name", key="rule_author", autocomplete="off", placeholder="Who is proposing this?…")
        template = b.selectbox("Rule Type", keys, format_func=lambda k: catalogue[k]["label"], key="rule_tpl")
        spec = catalogue[template]
        cols = st.columns(min(len(spec["args"]), 4) or 1)
        for i, arg in enumerate(spec["args"]):
            key, label = f"rf_{template}_{arg['name']}", ARG_LABELS.get(arg["name"], arg["name"].replace("_", " ").title())
            with cols[i % len(cols)]:
                if arg["kind"] == "choice":
                    st.selectbox(label, arg["choices"], key=key)
                elif arg["kind"] == "int":
                    st.number_input(label, min_value=arg["lo"], max_value=arg["hi"], value=arg["lo"], step=1, key=key)
                else:
                    st.text_input(label, key=key, max_chars=arg["max_len"], autocomplete="off",
                                  help="Use * as the match text to cover every signal." if arg["name"] == "match_text" else None)
        st.markdown(f"\U0001F4DD **Wording:** {md_escape(_wording(template, spec))}",
                    help="The rule's wording is written by the tool from the form, never typed free-hand.")
        st.button("Propose Rule", key="rule_propose", type="primary", on_click=_propose, args=(template,))


def _queue() -> None:
    s = st.session_state
    heading(QUEUE, "A different person approves or rejects each proposal with the approver passcode. "
                   "Approved rules are used only after Preview And Activate.")
    if not s["proposals"]:
        st.caption("No rules have been proposed yet.")
        return
    if not state.secret("APPROVER_PASSCODE"):
        st.warning("Approval is switched off: no approver passcode is configured for this deployment.")
    for p in s["proposals"]:
        colour = {"approved": "#3fb950", "rejected": "#ff7b72"}.get(p.status, "#e3b341")
        with st.container(border=True, key=f"proposal_{p.id}"):
            st.markdown(f"**{md_escape(p.statement)}**  \n<small>{'AI draft' if p.source == 'ai' else 'Form'} · "
                        f"{md_escape(rc.TEMPLATES[p.template].label)} · proposed by {md_escape(p.author)} · "
                        f"<span style='color:{colour};font-weight:700'>{p.status}</span></small>",
                        unsafe_allow_html=True, help=("Assistant's reasoning (information only): " + p.rationale) if p.rationale else None)
            _where_it_applies(p.template, p.args, p.id)
            if p.status != "pending":
                continue
            with st.expander(f"Approver Decision for {p.id}"):
                with st.form(f"decide_{p.id}"):
                    st.text_input("Reviewer Name", key=f"rv_{p.id}", autocomplete="off")
                    st.text_input("Approver Passcode", key=f"pc_{p.id}", type="password", autocomplete="off")
                    st.text_input("Reason (if rejecting)", key=f"rs_{p.id}", autocomplete="off")
                    st.checkbox("I understand rejecting is final", key=f"ok_{p.id}")
                    a, b = st.columns(2)
                    with a:
                        st.form_submit_button("Approve Rule", on_click=_decide, args=(p.id, "approve"))
                    with b:
                        st.form_submit_button("Reject Rule", on_click=_decide, args=(p.id, "reject"))


def _suggestions() -> None:
    s = st.session_state
    items = s["suggestions"]
    if not items:
        return
    heading(SUGGESTIONS, "Suggested fixes written on the TQ Board. A different person approves them with the approver "
                         "passcode. An approved suggestion is guidance for whoever fixes the question: it changes "
                         "nothing by itself.")
    for x in items:
        colour = {"approved": "#3fb950", "rejected": "#ff7b72"}.get(x.status, "#e3b341")
        with st.container(border=True, key=f"suggestion_{x.id}"):
            st.markdown(f"**{md_escape(x.tq_id)} · {md_escape(x.ref or '-')}**: {md_escape(x.text)}  \n"
                        f"<small>by {md_escape(x.author)} · <span style='color:{colour};font-weight:700'>{x.status}</span>"
                        + (f" · by {md_escape(x.reviewer)}" if x.reviewer else "") + "</small>", unsafe_allow_html=True)
            if x.status != "pending":
                continue
            with st.expander(f"Approver Decision for {x.id}"):
                with st.form(f"sgdecide_{x.id}"):
                    st.text_input("Reviewer Name", key=f"sgrv_{x.id}", autocomplete="off")
                    st.text_input("Approver Passcode", key=f"sgpc_{x.id}", type="password", autocomplete="off")
                    st.text_input("Reason (if rejecting)", key=f"sgrs_{x.id}", autocomplete="off")
                    a, b = st.columns(2)
                    with a:
                        st.form_submit_button("Approve Suggestion", on_click=_decide_suggestion, args=(x.id, "approve"))
                    with b:
                        st.form_submit_button("Reject Suggestion", on_click=_decide_suggestion, args=(x.id, "reject"))


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
    heading(ACTIVE, "The new columns and constraints of the ACTIVE pack. Open \U0001F441 Where It Applies to see the "
                    "CHARM signals each one covers, with the result for each signal. Project columns can be "
                    "downloaded as a CSV; they are never written into the locked allocation.")
    if not rules:
        st.caption("The active pack has no project columns or constraints yet. Propose one above (New Columns or Constraints).")
        return
    for i, rule in enumerate(rules):
        with st.container(border=True, key=f"active_rule_{i}"):
            st.markdown(f"**{md_escape(rule.get('statement') or rule.get('kind'))}**  \n<small>{md_escape(rc.TEMPLATES[rule['kind']].label)}"
                        f" · {md_escape(rule.get('id', ''))}</small>", unsafe_allow_html=True)
            _where_it_applies(rule["kind"], rule["args"], f"active_{i}")
    result = s["result"]
    columns = [r for r in rules if r.get("kind") == "project_column"]
    if columns and result is not None:
        lines = []
        for row in result.rows:
            values = project_columns(columns, row)
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
