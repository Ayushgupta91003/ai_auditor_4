import os
import httpx
import psycopg
from psycopg.rows import dict_row
import streamlit as st
st.set_page_config(page_title="AI Invoice Auditor",layout="wide")
st.title("AI Invoice Auditor")
st.caption("Audit recommendations with human oversight. Translation scores are self-assessed. Synthetic fixtures are included.")
BASE=os.getenv("AGENT_URL","http://agent:8000")
def api(method,path,**kwargs):
    try:
        response=httpx.request(method,BASE+path,timeout=600,headers={"Authorization":"Bearer "+os.environ["SERVICE_TOKEN"]},**kwargs)
        response.raise_for_status(); return response.json()
    except httpx.HTTPError as error:
        st.error("Request failed. Check the agent audit status and service logs.")
        return None
file=st.file_uploader("Upload an invoice",type=["pdf","docx","png"])
if file and st.button("Process invoice"):
    with st.spinner("Extracting, translating and validating..."):
        result=api("POST","/upload",files={"file":(file.name,file.getvalue())})
        if result: st.success(result)
if st.button("Refresh reports"): st.rerun()
# Read-only transaction: corrections always go through the agent API.
try:
    with psycopg.connect(os.environ["DATABASE_URL"],row_factory=dict_row) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        rows=conn.execute("SELECT invoice_id,invoice_number,vendor_name,total_amount,currency,status,error FROM audit.invoice_audit ORDER BY processed_at DESC LIMIT 500").fetchall()
except psycopg.Error:
    st.error("Audit database unavailable"); st.stop()
st.dataframe(rows,use_container_width=True)
if not rows: st.info("Upload an invoice or place one in data/incoming."); st.stop()
selected=st.selectbox("Select invoice",[str(r["invoice_id"]) for r in rows])
detail=api("GET","/invoices/"+selected)
if not detail: st.stop()
if detail["status"] in ("failed","processing") and st.button("Resume failed or interrupted workflow"):
    api("POST",f"/invoices/{selected}/retry"); st.rerun()
runs=detail["runs"]
if runs:
    version=st.selectbox("Report version",list(range(len(runs))),format_func=lambda i:f"Version {runs[i]['version']}",index=len(runs)-1)
    report=runs[version]["report"]
    st.subheader("Recommendation: "+report["recommendation"].upper())
    st.write(report["explanation"])
    st.metric("Translation confidence",report["translation_confidence"])
    st.dataframe(report["findings"],use_container_width=True)
    st.download_button("Download HTML report",runs[version]["html"],file_name="invoice-report.html",mime="text/html")
    import json
    st.download_button("Download JSON report",json.dumps(report,indent=2),file_name="invoice-report.json")
    with st.expander("Original extraction and correction history"):
        st.json(detail["extracted_raw"]); st.dataframe(detail["feedback"])
    with st.form("correction"):
        st.write("Append a correction, then revalidate. Original extraction is retained.")
        field=st.selectbox("Field",["invoice_number","invoice_date","vendor_name","vendor_id","po_number","currency","total_amount","subtotal","tax_rate","tax_amount","quantity","unit_price","line_total","item_code","description"])
        line=st.number_input("Line number (0 = invoice header)",min_value=0,step=1)
        value=st.text_input("Corrected value"); reviewer=st.text_input("Reviewer name"); reason=st.text_input("Reason")
        if st.form_submit_button("Save and revalidate"):
            result=api("POST",f"/invoices/{selected}/corrections",json={"field":field,"line_number":int(line) or None,"value":value,"reviewer":reviewer,"reason":reason,"expected_version":runs[-1]["version"]})
            if result: st.rerun()
    if any(not x["revalidated"] for x in detail["feedback"]) and st.button("Revalidate pending correction"):
        api("POST",f"/invoices/{selected}/revalidate"); st.rerun()
question=st.text_input("Ask about this invoice")
if st.button("Ask") and question:
    result=api("POST","/questions",json={"question":question,"invoice_id":selected})
    if result:
        st.write(result["answer"])
        with st.expander("Evidence and RAG evaluation"): st.json(result)
