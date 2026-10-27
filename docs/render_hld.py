from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
import math
ROOT=Path(__file__).parent
im=Image.new("RGB",(2000,1590),"#f4f7fc"); d=ImageDraw.Draw(im)
def font(n,bold=False):
    try: return ImageFont.truetype("C:/Windows/Fonts/"+("arialbd.ttf" if bold else "arial.ttf"),n)
    except OSError: return ImageFont.truetype("DejaVuSans.ttf",n)
def text(x,y,s,n=26,bold=False,color="#19324f"):
    d.text((x,y),s,font=font(n,bold),fill=color)
def box(rect,title,lines,fill="#ffffff"):
    x,y,x2,y2=rect; d.rounded_rectangle(rect,18,fill=fill,outline="#a6b7cc",width=2)
    text(x+20,y+16,title,30,True)
    for i,line in enumerate(lines): text(x+20,y+63+i*35,line,25)
def arrow(points,label=None,pos=None,color="#547191"):
    d.line(points,fill=color,width=4)
    a,b=points[-2:]; angle=math.atan2(b[1]-a[1],b[0]-a[0])
    d.polygon([b,(b[0]-16*math.cos(angle-.5),b[1]-16*math.sin(angle-.5)),(b[0]-16*math.cos(angle+.5),b[1]-16*math.sin(angle+.5))],fill=color)
    if label and pos:
        bb=d.textbbox(pos,label,font=font(22));d.rectangle((bb[0]-5,bb[1]-3,bb[2]+5,bb[3]+3),fill="#f4f7fc")
        text(*pos,label,22,color=color)
text(60,35,"AI INVOICE AUDITOR",52,True)
text(60,103,"High-level architecture | Six-service capstone deployment | Four-member team",28)
box((60,165,600,300),"Human auditor",["Upload, review, correct and ask"])
box((700,165,1250,300),"Mounted incoming folder",["PDF / DOCX / PNG | EN / ES / DE"])
box((1380,165,1940,320),"AWS Bedrock",["Nova Lite: chat / translation / RAG", "Titan V2 embeddings: InvokeModel"],"#eee8ff")
d.rounded_rectangle((35,365,1965,1130),25,outline="#728caa",width=3)
text(65,385,"COMPOSE BRIDGE NETWORK - SERVICE-NAME DISCOVERY",27,True)
box((70,455,600,600),"streamlit-ui  :8501",["Human review + immutable feedback","Read-only audit queries"],"#e5efff")
box((730,455,1250,600),"mock-erp  :8000",["PO / vendor / SKU HTTP API","Owns ERP access"],"#e5efff")
box((1380,455,1915,600),"redis  :6379",["Translation + answer cache (TTL)","DISPOSABLE - no volume"],"#fff0cf")
box((70,695,1250,910),"agent  :8000",["LangGraph: monitor > extract > translate > validate > index","Google ADK reporter via A2A discovery + message/send","MCP stdio: discover and invoke processing / RAG tools","LiteLLM custom gateway > ChatBedrockConverse only"],"#e5efff")
box((1380,695,1915,910),"qdrant  :6333",["Invoice + report chunk vectors","Payload includes invoice + version","Named volume: qdrant-data","REBUILDABLE from PostgreSQL"],"#def2e8")
box((70,985,1250,1100),"postgres  :5432 | Named volume: postgres-data",["audit: originals, lines, reports, feedback | langgraph: checkpoints | erp: master data"],"#def2e8")
arrow([(330,300),(330,455)])
arrow([(600,525),(660,525),(660,695)],"API",(670,625))
arrow([(975,300),(975,345),(30,345),(30,780),(70,780)])
arrow([(985,695),(985,600)],"HTTP only",(1005,630))
arrow([(990,600),(1280,600),(1280,1045),(1250,1045)],"ERP reads",(1286,945))
arrow([(335,600),(335,645),(10,645),(10,1045),(70,1045)],"audit reads",(48,932))
arrow([(610,910),(610,985)],"audit + checkpoints",(625,935))
arrow([(1250,790),(1380,790)],"vectors",(1265,750))
arrow([(1250,720),(1320,720),(1320,525),(1380,525)],"cache",(1264,650))
arrow([(1250,855),(1350,855),(1350,240),(1380,240)],"AWS API",(1258,335),"#8764a6")
box((1380,1160,1915,1280),"External LangFuse endpoint",["Redacted spans; runtime configuration"],"#eee8ff")
arrow([(1250,875),(1300,875),(1300,1220),(1380,1220)],"traces",(1305,1140),"#8764a6")
text(65,1165,"RAG: index > retrieve > rerank > generate > reflect",32,True)
text(65,1215,"Triad average > 0.7; up to three retries; otherwise abstain.",26)
text(65,1257,"SQL for known intents; append-only human correction history.",26)
text(65,1320,"FOUR SUBSTANTIAL WORKSTREAMS",30,True)
for i,(title,line) in enumerate([
("Member 1 - Document intelligence","Monitor, OCR, translation, parsing, MCP ingestion tools"),
("Member 2 - Audit and enterprise data","ERP API, schemas, Decimal rules, discrepancies, checkpoints"),
("Member 3 - Evidence and RAG","Qdrant, five RAG roles, triad evaluation, rebuild and cache"),
("Member 4 - Review and integration","ADK/A2A reports, Streamlit, feedback, tracing and Compose")]):
    y=1380+i*45; text(65,y,title,25,True); text(695,y,line,25)
im.save(ROOT/"HLD_ARCHITECTURE.png")
print(ROOT/"HLD_ARCHITECTURE.png")
