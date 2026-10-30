"""
Streamlit Human-in-the-Loop Audit Dashboard
Provides auditors with:
  1. Invoice Audit Explorer (metrics, line items, discrepancy breakdowns, HTML reports)
  2. Human Feedback & Corrections (immutable audit feedback log)
  3. RAG Audit Assistant (natural language QA with RAG Triad metrics display)
  4. System Monitor & Batch Processing Trigger
"""

import os
import json
import logging
from datetime import datetime
import streamlit as st
import httpx
import pandas as pd

logging.basicConfig(level=logging.INFO)

AGENT_URL = os.getenv("AGENT_URL", "http://agent:8000")
MOCK_ERP_URL = os.getenv("MOCK_ERP_URL", "http://mock-erp:8000")

# Page Config
st.set_page_config(
    page_title="AI Invoice Auditor – Dashboard",
    page_icon="📑",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling
st.markdown("""
<style>
    .main-header { font-size: 26px; font-weight: 700; color: #1e293b; margin-bottom: 2px; }
    .sub-header { font-size: 14px; color: #64748b; margin-bottom: 20px; }
    .badge-approved { background-color: #dcfce7; color: #15803d; padding: 4px 10px; border-radius: 6px; font-weight: 600; }
    .badge-review { background-color: #fef3c7; color: #b45309; padding: 4px 10px; border-radius: 6px; font-weight: 600; }
    .badge-rejected { background-color: #fee2e2; color: #b91c1c; padding: 4px 10px; border-radius: 6px; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

# Helper functions for API calls
def get_agent_health():
    try:
        resp = httpx.get(f"{AGENT_URL}/health", timeout=2.0)
        return resp.status_code == 200, resp.json()
    except Exception as e:
        return False, str(e)

def get_erp_health():
    try:
        resp = httpx.get(f"{MOCK_ERP_URL}/health", timeout=2.0)
        return resp.status_code == 200, resp.json()
    except Exception as e:
        return False, str(e)

def fetch_invoices():
    try:
        resp = httpx.get(f"{AGENT_URL}/invoices", timeout=5.0)
        if resp.status_code == 200:
            return resp.json().get("invoices", [])
    except Exception as e:
        st.sidebar.error(f"Cannot reach Agent API: {e}")
    return []

def fetch_invoice_details(invoice_id):
    try:
        resp = httpx.get(f"{AGENT_URL}/invoices/{invoice_id}", timeout=5.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        st.error(f"Failed to fetch details for {invoice_id}: {e}")
    return None

def get_watchdog_status():
    try:
        resp = httpx.get(f"{AGENT_URL}/watcher/status", timeout=2.5)
        if resp.status_code == 200:
            return True, resp.json()
    except Exception as e:
        return False, str(e)
    return False, {}

def toggle_watchdog():
    try:
        resp = httpx.post(f"{AGENT_URL}/watcher/toggle", timeout=5.0)
        return resp.status_code == 200, resp.json()
    except Exception as e:
        return False, str(e)

def trigger_watchdog_scan():
    try:
        resp = httpx.post(f"{AGENT_URL}/watcher/scan", timeout=60.0)
        return resp.status_code == 200, resp.json()
    except Exception as e:
        return False, str(e)

def fetch_review_queue():
    try:
        resp = httpx.get(f"{AGENT_URL}/review/queue", timeout=5.0)
        if resp.status_code == 200:
            return resp.json().get("invoices", [])
    except Exception as e:
        st.error(f"Cannot reach review queue: {e}")
    return []

def post_revalidate(invoice_id, corrections, line_items, reviewed_by):
    try:
        payload = {"corrections": corrections, "line_items": line_items, "reviewed_by": reviewed_by}
        resp = httpx.post(f"{AGENT_URL}/invoices/{invoice_id}/revalidate", json=payload, timeout=30.0)
        return resp.status_code == 200, resp.json() if resp.status_code == 200 else resp.text
    except Exception as e:
        return False, str(e)

def post_decision(invoice_id, action, reviewed_by, notes):
    try:
        resp = httpx.post(
            f"{AGENT_URL}/invoices/{invoice_id}/{action}",
            json={"reviewed_by": reviewed_by, "notes": notes}, timeout=30.0
        )
        return resp.status_code == 200, resp.json() if resp.status_code == 200 else resp.text
    except Exception as e:
        return False, str(e)

# Sidebar Navigation
st.sidebar.image("https://img.icons8.com/color/96/audit.png", width=64)
st.sidebar.title("AI Invoice Auditor")
st.sidebar.caption("Multilingual Agentic Validation Stack")

# Health Status in Sidebar
agent_ok, agent_info = get_agent_health()
erp_ok, erp_info = get_erp_health()
watchdog_ok, watchdog_info = get_watchdog_status()

st.sidebar.markdown("### Service Status")
st.sidebar.markdown(f"**Agent Service:** {'🟢 Healthy' if agent_ok else '🔴 Offline'}")
st.sidebar.markdown(f"**Mock ERP:** {'🟢 Healthy' if erp_ok else '🔴 Offline'}")

if watchdog_ok:
    is_paused = watchdog_info.get("is_paused", False)
    is_running = watchdog_info.get("is_running", False)
    if is_running and not is_paused:
        st.sidebar.markdown("**Watchdog:** 🟢 Active (Monitoring)")
    elif is_paused:
        st.sidebar.markdown("**Watchdog:** 🟡 Paused")
    else:
        st.sidebar.markdown("**Watchdog:** 🔴 Stopped")
else:
    st.sidebar.markdown("**Watchdog:** ⚪ Connecting...")

st.sidebar.divider()

# Main Tabs
tab_explorer, tab_review, tab_corrections, tab_rag, tab_system = st.tabs([
    "📊 Invoice Audit Explorer",
    "🕵️ Review Queue",
    "✏️ Human-in-the-Loop Corrections",
    "💬 RAG Audit Assistant",
    "⚙️ System Controls"
])

# ------------------------------------------------------------------------------
# TAB 1: INVOICE AUDIT EXPLORER
# ------------------------------------------------------------------------------
with tab_explorer:
    head_col, ref_col = st.columns([4, 1])
    with head_col:
        st.markdown('<div class="main-header">Processed Invoices & Audit Trail</div>', unsafe_allow_html=True)
        st.markdown('<div class="sub-header">Review validated vendor invoices, line items, and discrepancy reports</div>', unsafe_allow_html=True)
    with ref_col:
        st.write("")
        if st.button("🔄 Refresh Data", use_container_width=True):
            st.rerun()

    invoices = fetch_invoices()

    if not invoices:
        st.info("No invoices found in audit database yet. Drop an invoice file into `data/incoming/` — the autonomous Watchdog will detect and audit it automatically!")
    else:
        # Top KPI cards (driven by the human-review gate state)
        col1, col2, col3, col4 = st.columns(4)
        total_inv = len(invoices)

        def _review_state(i):
            # Fall back to recommendation for rows audited before the review gate existed.
            rs = i.get("review_status")
            if rs:
                return rs
            rec = i.get("recommendation")
            return "rejected" if rec == "reject" else ("pending_review" if rec == "manual_review" else "auto_approved")

        approved = sum(1 for i in invoices if _review_state(i) in ("auto_approved", "approved"))
        pending = sum(1 for i in invoices if _review_state(i) == "pending_review")
        rejected = sum(1 for i in invoices if _review_state(i) == "rejected")

        col1.metric("Total Audited", total_inv)
        col2.metric("Approved / Indexed", approved)
        col3.metric("Pending Review", pending)
        col4.metric("Rejected", rejected)

        st.divider()

        # Invoices Table
        df = pd.DataFrame(invoices)
        display_cols = ["invoice_number", "vendor_name", "po_number", "total_amount", "currency", "validation_status", "recommendation", "review_status", "risk_score", "reviewed_by", "translation_confidence", "processed_at"]
        available_cols = [c for c in display_cols if c in df.columns]
        st.dataframe(df[available_cols], use_container_width=True)

        st.markdown("### Invoice Inspector")
        inv_options = {f"{i.get('invoice_number') or 'Incomplete'} ({i.get('vendor_name') or 'Unknown'})": i["invoice_id"] for i in invoices}
        selected_label = st.selectbox("Select Invoice to inspect in detail:", list(inv_options.keys()))

        if selected_label:
            inv_id = inv_options[selected_label]
            detail = fetch_invoice_details(inv_id)

            if detail:
                c1, c2, c3, c4 = st.columns(4)
                c1.write(f"**Invoice No:** {detail.get('invoice_number') or 'None'}")
                c2.write(f"**PO Number:** {detail.get('po_number') or 'None'}")
                c3.write(f"**Total Amount:** {detail.get('currency', '')} {detail.get('total_amount', 0.0):.2f}")
                rec = detail.get("recommendation", "review")
                rec_badge = f'<span class="badge-approved">APPROVE</span>' if rec == "approve" else (f'<span class="badge-review">MANUAL REVIEW</span>' if rec == "manual_review" else f'<span class="badge-rejected">REJECT</span>')
                c4.markdown(f"**Recommendation:** {rec_badge}", unsafe_allow_html=True)

                rv = detail.get("review_status") or "pending_review"
                rv_badge = f'<span class="badge-approved">{rv.replace("_", " ").upper()}</span>' if rv in ("approved", "auto_approved") else (f'<span class="badge-rejected">REJECTED</span>' if rv == "rejected" else f'<span class="badge-review">PENDING REVIEW</span>')
                rc1, rc2, rc3 = st.columns(3)
                rc1.markdown(f"**Review Status:** {rv_badge}", unsafe_allow_html=True)
                rc2.write(f"**Risk Score:** {float(detail.get('risk_score') or 0.0):.2f}")
                rc3.write(f"**Reviewed By:** {detail.get('reviewed_by') or '—'}")

                st.write(f"**Language:** {detail.get('source_language', 'en').upper()} (Confidence: {detail.get('translation_confidence', 1.0):.2f})")

                # Discrepancies Table
                st.markdown("#### Discrepancies & ERP Validations")
                discrepancies = detail.get("discrepancies", [])
                if discrepancies:
                    st.dataframe(pd.DataFrame(discrepancies)[["field_name", "invoice_value", "erp_value", "deviation_pct", "severity"]], use_container_width=True)
                else:
                    st.success("No discrepancies detected. ERP validation succeeded completely!")

                # Line Items
                st.markdown("#### Line Items")
                lines = detail.get("line_items", [])
                if lines:
                    st.dataframe(pd.DataFrame(lines)[["line_number", "item_code", "description", "quantity", "unit_price", "line_total"]], use_container_width=True)
                else:
                    st.warning("No line items extracted.")

                # Raw vs Translated Text Expander
                with st.expander("View Raw & Translated Text"):
                    col_raw, col_trans = st.columns(2)
                    with col_raw:
                        st.markdown("**Raw Extracted Text:**")
                        st.text_area("raw", detail.get("raw_extracted_text", ""), height=200, disabled=True, label_visibility="collapsed")
                    with col_trans:
                        st.markdown("**Translated English Text:**")
                        st.text_area("translated", detail.get("translated_text", ""), height=200, disabled=True, label_visibility="collapsed")

# ------------------------------------------------------------------------------
# TAB 2: REVIEW QUEUE (Human approve / reject + edit & revalidate)
# ------------------------------------------------------------------------------
with tab_review:
    head_col, ref_col = st.columns([4, 1])
    with head_col:
        st.markdown('<div class="main-header">Human Review Queue</div>', unsafe_allow_html=True)
        st.markdown('<div class="sub-header">Invoices held by the risk gate before vector-store indexing. Edit &amp; revalidate if needed, then Approve (index) or Reject.</div>', unsafe_allow_html=True)
    with ref_col:
        st.write("")
        if st.button("🔄 Refresh Queue", use_container_width=True):
            st.rerun()

    queue = fetch_review_queue()
    st.metric("Awaiting Human Decision", len(queue))

    if not queue:
        st.success("Nothing awaiting review. Low-risk invoices are auto-approved and indexed automatically.")
    else:
        q_df = pd.DataFrame(queue)
        q_cols = [c for c in ["invoice_number", "vendor_name", "po_number", "total_amount", "currency",
                              "validation_status", "recommendation", "risk_score"] if c in q_df.columns]
        st.dataframe(q_df[q_cols], use_container_width=True)

        q_map = {f"{i.get('invoice_number') or 'Incomplete'} - {i.get('vendor_name') or 'Unknown'}": i["invoice_id"] for i in queue}
        choice = st.selectbox("Select an invoice to review:", list(q_map.keys()), key="review_select")
        rv_id = q_map[choice]
        detail = fetch_invoice_details(rv_id)

        if detail:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Risk Score", f"{float(detail.get('risk_score') or 0.0):.2f}")
            c2.write(f"**Status:** {detail.get('validation_status')}")
            c3.write(f"**Recommendation:** {detail.get('recommendation')}")
            c4.write(f"**Review:** {detail.get('review_status')}")

            st.markdown("#### Discrepancies")
            discrepancies = detail.get("discrepancies", [])
            if discrepancies:
                st.dataframe(pd.DataFrame(discrepancies)[["field_name", "invoice_value", "erp_value", "deviation_pct", "severity"]], use_container_width=True)
            else:
                st.success("No discrepancies on the current (possibly corrected) data.")

            st.markdown("#### Edit Header Fields")
            e1, e2, e3 = st.columns(3)
            with e1:
                ed_invoice_number = st.text_input("Invoice Number", value=str(detail.get("invoice_number") or ""), key=f"inum_{rv_id}")
                ed_currency = st.text_input("Currency", value=str(detail.get("currency") or ""), key=f"curr_{rv_id}")
            with e2:
                ed_po_number = st.text_input("PO Number", value=str(detail.get("po_number") or ""), key=f"po_{rv_id}")
                ed_vendor_name = st.text_input("Vendor Name", value=str(detail.get("vendor_name") or ""), key=f"vn_{rv_id}")
            with e3:
                ed_total = st.text_input("Total Amount", value=str(detail.get("total_amount") or ""), key=f"tot_{rv_id}")
                ed_vendor_id = st.text_input("Vendor ID", value=str(detail.get("vendor_id") or ""), key=f"vid_{rv_id}")

            st.markdown("#### Edit Line Items")
            lines = detail.get("line_items", [])
            line_cols = ["item_code", "description", "quantity", "unit_price", "line_total"]
            if lines:
                base_df = pd.DataFrame(lines)[[c for c in line_cols if c in pd.DataFrame(lines).columns]]
            else:
                base_df = pd.DataFrame(columns=line_cols)
            edited_lines = st.data_editor(base_df, num_rows="dynamic", use_container_width=True, key=f"lines_{rv_id}")

            reviewer = st.text_input("Reviewer Name / ID:", value="Senior Auditor", key=f"rev_{rv_id}")
            notes = st.text_area("Review Notes (optional):", key=f"notes_{rv_id}")

            b1, b2, b3 = st.columns(3)
            with b1:
                if st.button("♻️ Revalidate with Edits", use_container_width=True, key=f"reval_{rv_id}"):
                    corrections = {
                        "invoice_number": ed_invoice_number,
                        "currency": ed_currency,
                        "po_number": ed_po_number,
                        "vendor_name": ed_vendor_name,
                        "vendor_id": ed_vendor_id,
                    }
                    if str(ed_total).strip():
                        corrections["total_amount"] = ed_total
                    line_items_payload = edited_lines.to_dict(orient="records")
                    with st.spinner("Applying edits and re-running validation..."):
                        ok, res = post_revalidate(rv_id, corrections, line_items_payload, reviewer)
                    if ok:
                        st.success(f"Revalidated. New risk score: {res.get('risk_score')}, status: {res.get('validation_status')}")
                        st.json({"discrepancies": res.get("discrepancies", []), "risk_reasons": res.get("risk_reasons", [])})
                        st.rerun()
                    else:
                        st.error(f"Revalidation failed: {res}")
            with b2:
                if st.button("✅ Approve & Index", type="primary", use_container_width=True, key=f"appr_{rv_id}"):
                    with st.spinner("Approving and indexing into vector store..."):
                        ok, res = post_decision(rv_id, "approve", reviewer, notes)
                    if ok:
                        st.success("Approved and indexed. Decision stored in audit.human_feedback.")
                        st.rerun()
                    else:
                        st.error(f"Approval failed: {res}")
            with b3:
                if st.button("⛔ Reject", use_container_width=True, key=f"rej_{rv_id}"):
                    with st.spinner("Recording rejection..."):
                        ok, res = post_decision(rv_id, "reject", reviewer, notes)
                    if ok:
                        st.warning("Rejected. This invoice will not be indexed.")
                        st.rerun()
                    else:
                        st.error(f"Rejection failed: {res}")

# ------------------------------------------------------------------------------
# TAB 3: HUMAN-IN-THE-LOOP CORRECTIONS
# ------------------------------------------------------------------------------
with tab_corrections:
    st.markdown('<div class="main-header">Human Auditor Feedback & Corrections</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Submit corrections to extracted fields. Corrections are recorded permanently without altering the original extraction.</div>', unsafe_allow_html=True)

    invoices = fetch_invoices()
    if not invoices:
        st.info("No invoices available to correct.")
    else:
        inv_map = {f"{i.get('invoice_number') or 'Incomplete'} - {i.get('vendor_name') or 'Unknown'}": i["invoice_id"] for i in invoices}
        choice = st.selectbox("Select Invoice for Correction:", list(inv_map.keys()), key="fb_inv_select")
        inv_id = inv_map[choice]
        detail = fetch_invoice_details(inv_id)

        if detail:
            with st.form("feedback_form"):
                field_to_correct = st.selectbox("Field to Correct:", [
                    "invoice_number", "vendor_name", "vendor_id", "po_number", "currency", "total_amount", "line_item_qty", "line_item_price"
                ])
                current_val = str(detail.get(field_to_correct, "N/A"))
                st.text_input("Original Extracted Value:", value=current_val, disabled=True)
                corrected_val = st.text_input("Corrected Value:")
                auditor_name = st.text_input("Auditor Name / ID:", value="Senior Auditor")

                submitted = st.form_submit_button("Record Human Feedback")
                if submitted:
                    if not corrected_val.strip():
                        st.error("Please enter a corrected value.")
                    else:
                        payload = {
                            "field_name": field_to_correct,
                            "original_value": current_val,
                            "corrected_value": corrected_val,
                            "corrected_by": auditor_name
                        }
                        try:
                            resp = httpx.post(f"{AGENT_URL}/invoices/{inv_id}/feedback", json=payload, timeout=5.0)
                            if resp.status_code == 200:
                                st.success("Feedback recorded permanently in audit.human_feedback!")
                            else:
                                st.error(f"Error submitting feedback: {resp.text}")
                        except Exception as ex:
                            st.error(f"Connection error: {ex}")

            # Show historical feedback
            feedbacks = detail.get("feedback", [])
            st.markdown("#### Historical Corrections for this Invoice")
            if feedbacks:
                st.dataframe(pd.DataFrame(feedbacks)[["field_name", "original_value", "corrected_value", "corrected_by", "corrected_at"]], use_container_width=True)
            else:
                st.info("No prior human feedback recorded for this invoice.")

# ------------------------------------------------------------------------------
# TAB 3: RAG AUDIT ASSISTANT
# ------------------------------------------------------------------------------
with tab_rag:
    st.markdown('<div class="main-header">RAG Audit Assistant</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Ask natural language questions across invoice text, discrepancies, and audit reports with RAG Triad reflection.</div>', unsafe_allow_html=True)

    invoices = fetch_invoices()
    filter_opts = {"All Invoices (Global)": None}
    for inv in invoices:
        label = f"{inv.get('invoice_number') or 'Incomplete'} ({inv.get('vendor_name') or 'Vendor'})"
        filter_opts[label] = inv["invoice_id"]

    selected_scope = st.selectbox("Search Scope:", list(filter_opts.keys()))
    target_inv_id = filter_opts[selected_scope]

    sample_questions = [
        "What was the total amount and currency for Global Logistics?",
        "Why was the invoice for BlueOcean Transport flagged with a discrepancy?",
        "Which purchase order corresponds to the Spanish invoice from Transporte Ibérico?",
        "Were there any missing mandatory fields in the OceanFreight invoice?"
    ]
    st.caption(f"Suggested questions: *{sample_questions[0]}*")

    query_input = st.text_input("Enter your question:", placeholder="e.g. What items were invoiced under PO-1001?")

    if st.button("Ask Assistant", type="primary") and query_input.strip():
        with st.spinner("Retrieving evidence, reranking context, synthesizing an answer and scoring the RAG Triad..."):
            try:
                resp = httpx.post(
                    f"{AGENT_URL}/rag/query",
                    json={"query": query_input, "invoice_id": target_inv_id, "max_retries": 3},
                    timeout=180.0
                )
                if resp.status_code == 200:
                    rag_res = resp.json()

                    if rag_res.get("blocked"):
                        st.warning(rag_res.get("answer"))
                        st.caption(f"Blocked by Responsible AI guardrails: {rag_res.get('blocked_reason')}")
                    else:
                        st.markdown("### Answer")
                        st.markdown(f"> {rag_res.get('answer')}")

                    triad = rag_res.get("triad", {})
                    threshold = triad.get("threshold", 0.70)
                    st.markdown("#### RAG Triad Evaluation Metrics")
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Context Relevance", f"{triad.get('context_relevance', 0.0):.2f}")
                    m2.metric("Groundedness", f"{triad.get('groundedness', 0.0):.2f}")
                    m3.metric("Answer Relevance", f"{triad.get('answer_relevance', 0.0):.2f}")
                    avg = triad.get("average_score", 0.0)
                    m4.metric(f"Avg Score (> {threshold:.2f})", f"{avg:.2f}",
                              delta="Passed" if triad.get("passed") else "Below gate")

                    st.write(
                        f"**Attempts:** {rag_res.get('attempts', 1)} "
                        f"(retries used: {rag_res.get('retries_used', 0)} of 3) | "
                        f"**Served from cache:** {rag_res.get('cached', False)}"
                    )
                    if triad.get("critique"):
                        st.caption(f"Reflection Agent critique: {triad['critique']}")

                    findings = (rag_res.get("guardrail") or {}).get("findings") or []
                    if findings:
                        with st.expander(f"Responsible AI guardrail findings ({len(findings)})"):
                            st.table(findings)

                    with st.expander("Sources used (reranked chunks)"):
                        for idx, src in enumerate(rag_res.get("sources", []), start=1):
                            st.markdown(
                                f"**{idx}. {src.get('invoice_number') or src.get('invoice_id')}** "
                                f"— {src.get('doc_type')} (score {float(src.get('score') or 0):.3f})"
                            )

                    with st.expander("Reflection loop history"):
                        for attempt in rag_res.get("history", []):
                            st.markdown(
                                f"**Attempt {attempt.get('attempt')}** — query "
                                f"`{attempt.get('search_query')}`, retrieved "
                                f"{attempt.get('retrieved')} / kept {attempt.get('ranked')}, "
                                f"avg {attempt.get('average_score')} "
                                f"({'passed' if attempt.get('passed') else 'retry'})"
                            )
                else:
                    st.error(f"Error querying RAG engine: {resp.text}")
            except Exception as e:
                st.error(f"Failed to connect to agent service: {e}")

# ------------------------------------------------------------------------------
# TAB 4: SYSTEM CONTROLS & WATCHDOG
# ------------------------------------------------------------------------------
with tab_system:
    st.markdown('<div class="main-header">Autonomous Watchdog & Ingestion Controls</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Continuous directory observer automatically detects new invoices and triggers the audit pipeline</div>', unsafe_allow_html=True)

    w_ok, w_data = get_watchdog_status()

    # Watchdog Status & Metrics Card
    st.markdown("### 📡 Watchdog Live Monitor")
    m1, m2, m3, m4, m5 = st.columns(5)

    if w_ok:
        is_running = w_data.get("is_running", False)
        is_paused = w_data.get("is_paused", False)
        if is_running and not is_paused:
            status_text = "🟢 Active & Monitoring"
        elif is_paused:
            status_text = "🟡 Paused"
        else:
            status_text = "🔴 Stopped"

        m1.metric("Watchdog Status", status_text)
        m2.metric("Poll Interval", f"{w_data.get('poll_interval_seconds', 4.0)}s")
        m3.metric("Detected", w_data.get("total_detected", 0))
        m4.metric("Processed", w_data.get("total_processed", 0))
        m5.metric("Skipped (Duplicates)", w_data.get("total_skipped", 0))

        st.caption(f"**Monitored Directory:** `{w_data.get('incoming_dir', 'data/incoming')}` | **Last Scan Cycle:** `{w_data.get('last_scan_time', 'Never')}`")
    else:
        st.warning(f"Unable to query Watchdog service: {w_data}")

    st.divider()

    # Watchdog Actions
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### Watchdog Controls")
        st.write("The watchdog operates autonomously in the background. You can pause, resume, or trigger an on-demand scan cycle manually:")

        b_col1, b_col2 = st.columns(2)
        with b_col1:
            pause_label = "▶️ Resume Watchdog" if (w_ok and w_data.get("is_paused")) else "⏸️ Pause Watchdog"
            if st.button(pause_label, use_container_width=True):
                success, res = toggle_watchdog()
                if success:
                    st.toast(res.get("message", "Watchdog toggled!"))
                    st.rerun()
                else:
                    st.error(f"Toggle failed: {res}")

        with b_col2:
            if st.button("⚡ Force Immediate Scan", type="primary", use_container_width=True):
                with st.spinner("Executing immediate watchdog scan cycle..."):
                    success, res = trigger_watchdog_scan()
                    if success:
                        st.success("Scan cycle completed!")
                        if res.get("results"):
                            st.json(res.get("results"))
                        else:
                            st.info("No new un-audited invoices detected.")
                        st.rerun()
                    else:
                        st.error(f"Scan failed: {res}")

    with c2:
        st.markdown("#### System Information")
        st.write(f"**Agent Endpoint:** `{AGENT_URL}`")
        st.write(f"**Mock ERP Endpoint:** `{MOCK_ERP_URL}`")
        st.write(f"**Incoming Directory:** `data/incoming/`")
        st.write(f"**Current System Time:** `{datetime.utcnow().isoformat()}Z`")

    st.divider()

    # Real-time Activity Feed
    st.markdown("#### 📜 Recent Autonomous Activity Feed")
    if w_ok and w_data.get("recent_events"):
        events = w_data.get("recent_events")
        df_events = pd.DataFrame(events)
        st.dataframe(df_events, use_container_width=True, hide_index=True)
    else:
        st.info("No watchdog events logged yet. Place invoice files (`.pdf`, `.docx`, `.png`) in `data/incoming/` to observe real-time events.")

    st.divider()

    # --------------------------------------------------------------------------
    # Agentic surface: A2A agent directory, MCP tool catalogue, stores
    # --------------------------------------------------------------------------
    st.markdown("#### 🤖 Agents, Tools & Stores")

    a_col, t_col = st.columns(2)

    with a_col:
        st.markdown("**A2A agent directory**")
        try:
            agents = httpx.get(f"{AGENT_URL}/agents", timeout=10.0).json().get("agents", [])
            st.dataframe(
                pd.DataFrame([{
                    "Agent": a.get("name"),
                    "Framework": a.get("framework"),
                    "Skills": ", ".join(s.get("id") for s in a.get("skills", [])),
                } for a in agents]),
                use_container_width=True, hide_index=True,
            )
            st.caption("Agents are discovered over the Agent-to-Agent protocol; "
                       "LangGraph and Google ADK agents appear side by side.")
        except Exception as e:
            st.error(f"Agent directory unavailable: {e}")

    with t_col:
        st.markdown("**MCP tool catalogue**")
        try:
            tools = httpx.get(f"{AGENT_URL}/mcp/tools", timeout=10.0).json().get("tools", [])
            st.dataframe(
                pd.DataFrame([{
                    "Tool": t.get("name"),
                    "Owning agent": (t.get("annotations") or {}).get("owningAgent"),
                    "Guardrails": ", ".join((t.get("annotations") or {}).get("guardrails", [])) or "—",
                } for t in tools]),
                use_container_width=True, hide_index=True,
            )
            st.caption("Served over the Model Context Protocol at /mcp — agents discover "
                       "these at run time rather than importing them.")
        except Exception as e:
            st.error(f"MCP tool catalogue unavailable: {e}")

    st.markdown("**Stores & observability**")
    try:
        deps = httpx.get(f"{AGENT_URL}/health/dependencies", timeout=10.0).json()
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("PostgreSQL", "connected" if deps.get("postgres", {}).get("ok") else "degraded")
        d2.metric("mock-erp", "reachable" if deps.get("mock_erp", {}).get("ok") else "unreachable")
        qdrant = deps.get("qdrant", {})
        d3.metric("Qdrant vectors", qdrant.get("points", 0) if qdrant.get("reachable") else "offline")
        redis_info = deps.get("redis", {})
        d4.metric("Redis cache hit rate",
                  f"{redis_info.get('hit_rate', 0):.0%}" if redis_info.get("reachable") else "offline")
    except Exception as e:
        st.warning(f"Dependency health unavailable: {e}")

    if st.button("🔁 Rebuild vector index from PostgreSQL"):
        with st.spinner("Re-chunking and re-embedding every approved invoice from the system of record..."):
            try:
                result = httpx.post(f"{AGENT_URL}/rag/rebuild", json={}, timeout=600.0).json()
                st.success(f"Rebuilt {result.get('invoices_indexed', 0)} invoices "
                           f"({result.get('chunks_written', 0)} chunks).")
                st.json(result)
            except Exception as e:
                st.error(f"Rebuild failed: {e}")
    st.caption("Qdrant is a derived store. Destroying its volume costs a rebuild, not data: "
               "every vector is regenerated from text already held in PostgreSQL.")
