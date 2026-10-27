"""Reject currency substitutions in generated prose; never alter computed findings."""
import re
CODES={"USD","EUR","GBP","INR","JPY","CAD","AUD","NZD","CHF","CNY","SGD","HKD","AED","BRL"}
SYMBOLS={"$":{"USD","CAD","AUD","NZD","SGD","HKD","MXN"},"€":{"EUR"},"£":{"GBP"},"₹":{"INR"},"¥":{"JPY","CNY"}}
MONEY_FIELDS={"unit_price","line_total","total_amount","subtotal","tax_amount","freight","discount"}

def checked_explanation(report,text):
    invoice=report.get("invoice") or {}
    currency=invoice.get("currency")
    if not currency:return text,"model"
    allowed={currency}
    for finding in report["findings"]:
        if finding["field"]=="currency":allowed.update(v for v in (finding.get("actual"),finding.get("expected")) if v)
    mentioned=set(re.findall(r"\b[A-Z]{3}\b",text)) & CODES
    wrong_code=bool(mentioned-allowed)
    wrong_symbol=any(symbol in text and not (currencies & allowed) for symbol,currencies in SYMBOLS.items())
    if not (wrong_code or wrong_symbol):return text,"model"
    name=invoice.get("invoice_number") or "This invoice"
    findings=report["findings"]
    if not findings:
        conclusion="passed the configured checks with no discrepancies" if report["recommendation"]=="approve" else "requires manual review based on the configured policy and translation confidence"
        return name+" "+conclusion+".","verified-findings-template"
    sentences=[name+" has "+str(len(findings))+" finding(s); recommendation: "+report["recommendation"]+"."]
    for finding in findings[:5]:
        label=("Line "+str(finding["line_number"])+" " if finding.get("line_number") else "")+finding["field"]
        if finding.get("actual") is None:
            sentences.append(label+": "+finding["message"]+".");continue
        prefix=currency+" " if finding["field"] in MONEY_FIELDS else ""
        sentence=label+": invoice "+prefix+str(finding["actual"])+", expected "+prefix+str(finding.get("expected"))+"."
        if finding.get("deviation_percent") is not None:sentence+=" Deviation: "+str(finding["deviation_percent"])+"%."
        sentences.append(sentence)
    return " ".join(sentences),"verified-findings-template"
