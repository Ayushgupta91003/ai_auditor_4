import hashlib
import json
from langdetect import detect, DetectorFactory
from agent.llm import json_answer
from agent.config import prompt
from agent.models import Invoice
from agent.settings import settings
DetectorFactory.seed = 0

def translate(text, cache):
    language = detect(text)
    if language == "en": return {"text":text,"confidence":1.0,"language":"en","notes":"No translation performed"}
    key = "translation:" + hashlib.sha256((settings.rag_model+text).encode()).hexdigest()
    hit = cache.get(key)
    if hit: return json.loads(hit)
    result = json_answer(prompt("translation"),text,model=settings.rag_model)
    if not isinstance(result.get("text"),str) or not 0 <= float(result["confidence"]) <= 1:
        raise ValueError("Invalid translation response")
    result["language"] = language
    cache.setex(key,86400,json.dumps(result))
    return result

def parse(text, cache):
    data = json_answer(prompt("extraction") + "\nSchema: " + json.dumps(Invoice.model_json_schema()),text,cache=cache)
    return Invoice.model_validate(data)
