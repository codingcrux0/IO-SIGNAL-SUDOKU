"""Rules: governed rule changes.  Engineers propose, a DIFFERENT person approves, the audit log records it all.

The locked rules cannot be changed here at all.  The AI box only drafts a proposal for the same
form; it never touches allocation and never sees your MDB data."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import streamlit as st

from io_sudoku.core import advisor, rulechange as rc
from io_sudoku.core.pipeline import solve
from io_sudoku.core.rulepack import LOCKED_RULES, derive, pack_from_dict, pack_hash, pack_to_dict, validate_pack
from io_sudoku.ui import state, ui_logic


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _rooms() -> list[str]:
    return ui_logic.config_for_pack(st.session_state["pack"]).known_rooms()


# --------------------------------------------------------------------------- callbacks
def _propose(template: str) -> None:
    s = st.session_state
    spec = rc.TEMPLATES[template]
    args = {a.name: s.get(f"rf_{template}_{a.name}") for a in spec.args}
    proposal, errors = rc.build_proposal(template, args, s.get("rule_author") or "", now=_now(), known_rooms=_rooms())
    if proposal is None:
        state.flash("error", " ".join(errors))
        return
    s["proposals"] = s["proposals"] + [proposal]
    state.flash("success", f"Proposed: {proposal.statement} It waits for approval.")


def _client():
    return advisor.default_client(state.secret("ANTHROPIC_API_KEY"))


def _draft_ai() -> None:
    s = st.session_state
    draft = advisor.draft_rule(s.get("ai_request") or "", s.get("rule_author") or "", _client(), _now(), _rooms())
    if draft.ok:
        s["proposals"] = s["proposals"] + [draft.proposal]
        state.flash("success", f"The assistant drafted: {draft.proposal.statement} It waits for approval like any other rule.")
    else:
        state.flash("warning", draft.message + (" " + " ".join(draft.errors) if draft.errors else ""))


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
            state.flash("error", "Tick “I understand” before rejecting a rule.")
            return
        errors = rc.reject(target, reviewer, s.get(f"rs_{proposal_id}") or "", passcode, secret, _now())
    state.flash("error" if errors else "success", " ".join(errors) if errors else f"Rule {target.status}.")


def _preview() -> None:
    s = st.session_state
    if not s["mdb_bytes"]:
        state.flash("error", "Upload an MDB or load the sample data first, so the impact can be measured.")
        return
    cfg_now = ui_logic.config_for_pack(s["pack"])
    new_pack = rc.apply_approved(s["pack"], s["proposals"], cfg_now)
    if pack_hash(new_pack) == pack_hash(s["pack"]):
        state.flash("warning", "There is no approved rule to apply yet.")
        return
    before = solve(s["mdb_bytes"], cfg_now, "00", column_overrides=s["column_overrides"])
    after = solve(s["mdb_bytes"], ui_logic.config_for_pack(new_pack), "00", column_overrides=s["column_overrides"])
    s["rule_preview"] = {"pack": new_pack, "diff": rc.row_diff_summary(before.rows, after.rows),
                         "before": before.readiness.status, "after": after.readiness.status}


def _activate() -> None:
    s = st.session_state
    preview = s["rule_preview"]
    if preview and s.get("activate_ok"):
        s["pack"] = preview["pack"]
        s["rule_preview"] = None
        state.mark_stale()
        state.flash("success", f"Rule pack {s['pack'].name} v{s['pack'].version} is now active. Re-solve to use it.")
    else:
        state.flash("error", "Tick “I understand” to activate the new rule pack.")


def _import_pack() -> None:
    s = st.session_state
    up = s.get("pack_uploader")
    if up is None:
        return
    try:
        pack = pack_from_dict(json.loads(up.getvalue()))
    except ValueError:
        state.flash("error", "That file is not a rule pack. Download one from this page and try again.")
        return
    problems = validate_pack(pack)
    if problems:
        state.flash("error", " ".join(problems))
        return
    s["pack"] = pack
    state.mark_stale()
    state.flash("success", f"Rule pack {pack.name} v{pack.version} loaded. Re-solve to use it.")


# -------------------------------------------------------------------------------- view
def render() -> None:
    s = st.session_state
    st.header("Rules")
    with st.expander("Locked Rules (cannot be changed)", expanded=True):
        st.markdown("\n".join(f"- {r}" for r in LOCKED_RULES))
    pack = s["pack"]
    st.markdown(f"**Active pack:** {pack.name} v{pack.version} · fingerprint `{pack_hash(pack)[:10]}`")
    st.dataframe([{"Setting": k, "Value": v} for k, v in sorted(pack.params.items())], hide_index=True, width="stretch")
    if pack.overrides:
        with st.expander("Project Rules In This Pack"):
            st.json(pack.overrides)

    st.subheader("Propose A Rule")
    st.text_input("Your Name", key="rule_author", autocomplete="off", placeholder="Who is proposing this?…")
    catalogue = {t["key"]: t for t in rc.template_catalogue(_rooms())}
    template = st.selectbox("Rule Type", list(catalogue), format_func=lambda k: catalogue[k]["label"], key="rule_tpl")
    spec = catalogue[template]
    st.caption("Wording preview: " + spec["statement"])
    with st.form("rule_form"):
        for arg in spec["args"]:
            key, label = f"rf_{template}_{arg['name']}", arg["name"].replace("_", " ").title()
            if arg["kind"] == "choice":
                st.selectbox(label, arg["choices"], key=key)
            elif arg["kind"] == "int":
                st.number_input(label, min_value=arg["lo"], max_value=arg["hi"], value=arg["lo"], step=1, key=key)
            else:
                st.text_input(label, key=key, max_chars=arg["max_len"], autocomplete="off")
        st.form_submit_button("Propose Rule", on_click=_propose, args=(template,))

    st.subheader("Ask The AI Assistant (optional)")
    configured = _client() is not None
    if not configured:
        st.caption("The AI assistant is switched off because no API key is set. The form above works without it.")
    st.text_area("Describe The Rule You Want", key="ai_request", max_chars=advisor.MAX_REQUEST_CHARS, disabled=not configured,
                 placeholder="For example: treat PSV valves as high-current loads…")
    st.button("Draft Rule With AI", key="ai_draft", on_click=_draft_ai, disabled=not configured)
    st.caption("The assistant only fills in the same form. It never changes the allocation, and it never sees your MDB data.")

    _queue()
    _impact()
    _pack_files()


def _queue() -> None:
    s = st.session_state
    st.subheader("Review Queue")
    if not s["proposals"]:
        st.info("No rules have been proposed yet.")
        return
    configured = bool(state.secret("APPROVER_PASSCODE"))
    if not configured:
        st.warning("Approval is switched off: no approver passcode is configured for this deployment.")
    for p in s["proposals"]:
        origin = "AI draft" if p.source == "ai" else "Form"
        st.markdown(f"**{p.statement}**  \n{origin} · proposed by {p.author} · status: **{p.status}**")
        if p.rationale:
            st.caption("Assistant's reasoning (information only): " + p.rationale)
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


def _impact() -> None:
    s = st.session_state
    st.subheader("Preview And Activate")
    st.button("Preview Impact Of Approved Rules", key="rule_preview_btn", on_click=_preview)
    preview = s["rule_preview"]
    if not preview:
        st.caption("Approved rules take effect only after you preview and activate them.")
        return
    st.markdown(f"Readiness would change from **{preview['before']}** to **{preview['after']}**.")
    if preview["diff"]:
        st.dataframe([{"Column": k, "Cells Changed": v} for k, v in preview["diff"].items()], hide_index=True, width="stretch")
    else:
        st.success("No cell of the allocation would change.")
    st.checkbox("I understand this replaces the active rule pack", key="activate_ok")
    st.button("Activate Rule Pack", key="rule_activate", on_click=_activate, type="primary")


def _pack_files() -> None:
    s = st.session_state
    st.subheader("Rule Pack And Audit Log")
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
