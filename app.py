"""Streamlit demo:  .venv/bin/streamlit run app.py"""
from __future__ import annotations

import csv
import os

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from supplier_checker import ai_reader, config, reviews
from supplier_checker.graph import check_document
from supplier_checker.schemas import Decision, Severity

load_dotenv(config.PROJECT_ROOT / ".env")
st.set_page_config(page_title="Supplier Document Checker", page_icon="📄", layout="wide")

# Streamlit Cloud: allow the key to come from st.secrets.
try:
    for secret in ("GEMINI_API_KEY", "GROQ_API_KEY"):
        if not os.getenv(secret) and secret in st.secrets:
            os.environ[secret] = st.secrets[secret]
except Exception:
    pass

BADGE = {
    Decision.APPROVE: ("✅ Approve", "green"),
    Decision.REJECT: ("⛔ Reject", "red"),
    Decision.REVIEW: ("🧑‍💼 Needs a person to check", "orange"),
}
SEV_ICON = {Severity.PASS: "✅", Severity.REJECT: "⛔", Severity.REVIEW: "🟠", Severity.INFO: "ℹ️"}

def remember(state: dict) -> None:
    """Keep every checked document for the Decisions tab (latest result per file)."""
    st.session_state.setdefault("checked", {})[state["document_name"]] = state


def review_form(state: dict, key: str, fd: "reviews.FinalDecision") -> None:
    """Form for a person to decide (or change their decision on) a 'Needs a person' document."""
    title = "Change the review" if fd.by_person else "Review this document"
    with st.form(key):
        st.markdown(f"**{title}**: the system stopped here and needs a person's decision.")
        c1, c2 = st.columns([1, 2])
        name = c1.text_input("Your name", key=f"{key}-name")
        choice = c2.radio("Decision", ["Approve", "Reject"], horizontal=True, key=f"{key}-choice")
        note = st.text_input("Note (why)", key=f"{key}-note")
        if st.form_submit_button("Save review"):
            try:
                reviews.add_review(state["document_name"], state["decision"], reviews.Decision(choice), name, note)
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.rerun()


def decided_line(fd: "reviews.FinalDecision") -> str:
    if not fd.by_person:
        return "Decided by the system"
    r = fd.review
    note = f' · "{r.note}"' if r.note else ""
    return f"Decided by **{r.reviewer_name}** on {r.time.replace('T', ' ')} · system said: {fd.system.value}{note}"


# ----------------------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("Settings")
    key = st.text_input("Gemini API key (optional)", type="password",
                        help="Used only in this session. Without any key the app runs in parser-only mode.")
    if key:
        os.environ["GEMINI_API_KEY"] = key
    groq_key = st.text_input("Groq API key (optional backup)", type="password",
                             help="Used if Gemini fails (quota, outage). Free at console.groq.com.")
    if groq_key:
        os.environ["GROQ_API_KEY"] = groq_key
    has_key = ai_reader.is_configured()
    modes = ["hybrid", "ai", "parser"] if has_key else ["parser"]
    mode = st.radio("Reading mode", modes, format_func={
        "hybrid": "Hybrid: AI + parser cross-check (recommended)",
        "ai": "AI only (quotes verified)",
        "parser": "Parser only (no AI, offline)"}.get)
    if not has_key:
        st.info("No Gemini key found: running in parser-only mode.")
    else:
        st.caption(f"AI chain: `{ai_reader.model_name()}`")

    st.divider()
    st.subheader("Purchase request PR-2026-114")
    st.dataframe(pd.read_csv(config.PURCHASE_REQUEST_CSV, encoding="utf-8-sig")
                 .drop(columns=["PR number"]), hide_index=True)
    with st.expander("Company rules"):
        st.markdown((config.DATA_DIR / "company-rules.md").read_text(encoding="utf-8"))


# ----------------------------------------------------------------------------- rendering
def show_result(state: dict, key_prefix: str) -> None:
    decision = state["decision"]
    label, colour = BADGE[decision]
    ex = state.get("extraction")
    fd = reviews.final_decision(state["document_name"], decision, reviews.load_reviews())
    if fd.by_person:
        f_label, f_colour = BADGE[fd.decision]
        st.markdown(f"### :{f_colour}[{f_label}] (final, by a person)")
        st.info(decided_line(fd))
        st.markdown(f"System decision: :{colour}[{label}]")
    else:
        st.markdown(f"### :{colour}[{label}]")
    if state.get("ai_provider"):
        st.caption(f"Read by: `{state['ai_provider']}`")

    if decision == Decision.APPROVE:
        st.success("Every check passed. See the full checklist below.")
    else:
        st.markdown("**Why:**")
        for r in state["reasons"]:
            st.markdown(f"- **[{r.rule_id}] {r.check}:** {r.message}")
            if r.evidence:
                st.markdown(f"  > _\"{' '.join(r.evidence.split())}\"_")
        others = [f for f in state["findings"] if f.severity == Severity.REVIEW and f not in state["reasons"]]
        if others:
            st.markdown("**Also flagged:** " + "; ".join(f"[{f.rule_id}] {f.message}" for f in others))

    c1, c2 = st.columns([1, 1])
    with c1:
        st.markdown("**Extracted from the document**")
        if ex:
            rows = {"Supplier": ex.supplier_name, "Quotation": f"{ex.quotation_no} ({ex.quotation_date})",
                    "PR reference": ex.pr_reference}
            for it in ex.line_items:
                rows[f"Item {it.item_code}"] = (f"{it.description} — {it.quantity:,.0f} {it.unit} × "
                                                f"{it.unit_price} BDT = {it.amount:,.2f}"
                                                + (" (VAT incl.)" if it.price_includes_vat else ""))
            rows.update({"Subtotal / VAT / Total": f"{ex.subtotal} / {ex.vat_amount} ({ex.vat_rate_percent}%) / {ex.total}",
                         "TIN / BIN": f"{ex.tin} / {ex.bin}", "Advance": f"{ex.advance_percent}%",
                         "Payment days": f"{ex.payment_days_min}–{ex.payment_days_max}",
                         "Delivery": f"{ex.delivery_days} days",
                         "Penalty": f"{ex.penalty_percent_per_week}% / week" if ex.penalty_present else "none",
                         "Validity": f"{ex.validity_days} days"})
            st.table(pd.DataFrame(rows.items(), columns=["Field", "Value"]).astype(str).set_index("Field"))
            if state.get("uncertain_fields"):
                st.warning("Uncertain fields: " + ", ".join(state["uncertain_fields"]))
    with c2:
        st.markdown("**Pipeline steps**")
        for s in state["steps"]:
            icon = {"ok": "✅", "skipped": "⏭️", "failed": "❌", "reject": "⛔",
                    "review": "🟠", "uncertain": "🟠"}.get(s["status"], "▶️")
            st.markdown(f"{icon} **{s['step']}** — {s['detail']} _({s['seconds']}s)_")

    with st.expander("Full checklist (every rule)"):
        st.dataframe(pd.DataFrame([{
            "": SEV_ICON[f.severity], "Rule": f.rule_id, "Check": f.check, "Result": f.message,
            "Quote": " ".join((f.evidence or "").split())} for f in state["findings"]]),
            hide_index=True, width="stretch")

    if decision == Decision.REVIEW:
        review_form(state, f"{key_prefix}-review", fd)


# ----------------------------------------------------------------------------- main
st.title("📄 Supplier Document Checker")
st.caption("Aamar Garments Ltd (fictional) · Checks supplier quotations step by step against the purchase "
           "request and company rules. When unsure, it stops and asks a person.")

tab_all, tab_one, tab_board = st.tabs(["Check all 10 samples", "Check one document", "Decisions"])

with tab_all:
    expected = {r["file"]: r for r in csv.DictReader(open(config.EXPECTED_CSV, encoding="utf-8"))}
    if st.button("▶ Run all 10 sample packs", type="primary"):
        results, progress = {}, st.progress(0.0)
        for i, name in enumerate(expected):
            results[name] = check_document(config.DATA_DIR / name, mode=mode)
            remember(results[name])
            progress.progress((i + 1) / len(expected), text=f"Checked {name}")
        st.session_state["batch"] = (mode, results)

    if "batch" in st.session_state:
        run_mode, results = st.session_state["batch"]
        correct = sum(results[n]["decision"].value == expected[n]["expected_decision"] for n in results)
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Correct vs expected", f"{correct} / {len(results)}")
        for col, d in zip((m2, m3, m4), Decision):
            col.metric(BADGE[d][0], sum(r["decision"] == d for r in results.values()))
        st.caption(f"Mode: {run_mode}")
        history = reviews.load_reviews()
        finals = {n: reviews.final_decision(n, r["decision"], history) for n, r in results.items()}
        st.dataframe(pd.DataFrame([{
            "File": n, "Supplier": (r["extraction"].supplier_name if r.get("extraction") else "-"),
            "System decision": BADGE[r["decision"]][0],
            "Final decision": BADGE[finals[n].decision][0],
            "Decided by": finals[n].decided_by,
            "Expected": expected[n]["expected_decision"],
            "Match": "✅" if r["decision"].value == expected[n]["expected_decision"] else "❌",
            "Main reason": "; ".join(f"[{x.rule_id}] {x.message}" for x in r["reasons"]) or "All checks passed",
        } for n, r in results.items()]), hide_index=True, width="stretch")
        pick = st.selectbox("Inspect a document", list(results))
        show_result(results[pick], f"batch-{pick}")

with tab_one:
    choice = st.selectbox("Pick a sample…", ["—"] + list(expected))
    upload = st.file_uploader("…or upload a supplier quotation PDF", type=["pdf"])
    if st.button("Check document", type="primary", disabled=(choice == "—" and upload is None)):
        if upload is not None:
            st.session_state["single"] = check_document(upload, name=upload.name, mode=mode)
        else:
            st.session_state["single"] = check_document(config.DATA_DIR / choice, mode=mode)
        remember(st.session_state["single"])
    if "single" in st.session_state:
        show_result(st.session_state["single"], "single")

with tab_board:
    checked: dict = st.session_state.get("checked", {})
    history = reviews.load_reviews()
    st.markdown("Every checked document, sorted by its **final** decision: the reviewer's decision when a "
                "person has reviewed it, otherwise the system's.")
    if not checked:
        st.info("No documents checked yet in this session. Run **Check all 10 samples** or **Check one "
                "document** first. Past reviews are still listed in the history below.")
    else:
        finals = {n: reviews.final_decision(n, s["decision"], history) for n, s in checked.items()}
        groups = {d: [n for n in checked if finals[n].decision == d] for d in Decision}
        cols = st.columns(3)
        for col, d in zip(cols, (Decision.APPROVE, Decision.REJECT, Decision.REVIEW)):
            with col:
                label, colour = BADGE[d]
                title = "Needs a person" if d == Decision.REVIEW else label
                st.markdown(f"#### :{colour}[{title}] ({len(groups[d])})")
                if not groups[d]:
                    st.caption("None")
                for n in groups[d]:
                    state, fd = checked[n], finals[n]
                    ex = state.get("extraction")
                    with st.container(border=True):
                        st.markdown(f"**{n}**  \n{ex.supplier_name if ex else ''}")
                        if fd.by_person:
                            st.caption(f"👤 {decided_line(fd)}")
                        else:
                            st.caption("🤖 Decided by the system")
                            if state["reasons"]:
                                r = state["reasons"][0]
                                st.caption(f"[{r.rule_id}] {r.message}")
                        if state["decision"] == Decision.REVIEW:
                            with st.expander("Change review" if fd.by_person else "Review now"):
                                review_form(state, f"board-{n}", fd)

    st.divider()
    st.markdown(f"#### Review history ({len(history)})")
    if history:
        st.caption("Every review ever saved, newest first. Nothing is overwritten: a changed decision is a "
                   "new row, and the latest one counts.")
        st.dataframe(pd.DataFrame([{
            "Time": r.time.replace("T", " "), "Document": r.document, "Reviewer": r.reviewer_name,
            "Decision": BADGE[r.decision][0], "System had said": r.system, "Note": r.note,
        } for r in reversed(history)]), hide_index=True, width="stretch")
    else:
        st.caption("No reviews yet.")
    st.caption(f"Saved in `{reviews.REVIEW_LOG.relative_to(config.PROJECT_ROOT)}`. On the free online demo "
               "this file is reset whenever the app restarts.")
