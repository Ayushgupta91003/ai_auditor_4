"""Synthetic data, not the absent Masked Invoice attachment."""
from pathlib import Path
from docx import Document
from PIL import Image,ImageDraw,ImageFont
from reportlab.pdfgen import canvas
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/"samples"; out.mkdir(exist_ok=True)
headers={"english":["SYNTHETIC TEST INVOICE","Invoice number","Date","Vendor","Vendor ID","Purchase order","Currency","Item code | Description | Quantity | Unit price | Line total","Subtotal","Tax rate","Tax amount","Total"],
"spanish":["FACTURA SINTETICA DE PRUEBA","Numero de factura","Fecha","Proveedor","ID de proveedor","Orden de compra","Moneda","Codigo | Descripcion | Cantidad | Precio unitario | Importe","Subtotal","Tipo de impuesto","Impuesto","Total"],
"german":["SYNTHETISCHE TESTRECHNUNG","Rechnungsnummer","Datum","Lieferant","Lieferanten-ID","Bestellnummer","Waehrung","Artikelcode | Beschreibung | Menge | Einzelpreis | Gesamt","Zwischensumme","Steuersatz","Steuerbetrag","Gesamtbetrag"]}
for language,h in headers.items():
    quantity=12 if language=="german" else 10; price=120 if language=="spanish" else 100
    subtotal=quantity*price+100
    lines=[h[0],f"{h[1]}: INV-{language.upper()}-001",h[2]+": 2026-10-01",h[3]+": Global Logistics Supplies",h[4]+": V001",h[5]+": PO-1001",h[6]+": EUR",h[7],f"BOX-01 | Boxes | {quantity} | {price}.00 | {quantity*price}.00","PAL-01 | Pallets | 2 | 50.00 | 100.00",f"{h[8]}: {subtotal}.00",h[9]+": 10%",f"{h[10]}: {subtotal//10}.00",f"{h[11]}: {subtotal*11//10}.00"]
    text="\n".join(lines); (out/(language+".txt")).write_text(text,encoding="utf-8")
    doc=Document()
    for line in lines: doc.add_paragraph(line)
    doc.save(out/(language+".docx"))
    pdf=canvas.Canvas(str(out/(language+".pdf")))
    for i,line in enumerate(lines): pdf.drawString(40,800-24*i,line)
    pdf.save()
    image=Image.new("RGB",(1600,1100),"white"); draw=ImageDraw.Draw(image)
    try: font=ImageFont.truetype("C:/Windows/Fonts/arial.ttf",28)
    except OSError: font=ImageFont.load_default(size=28)
    draw.multiline_text((50,50),text,font=font,fill="black",spacing=15)
    image.save(out/(language+".png")); image.save(out/(language+"-scanned.pdf"),"PDF",resolution=120)
print("Generated multilingual fixtures: English matching, Spanish wrong price, German wrong quantity")
