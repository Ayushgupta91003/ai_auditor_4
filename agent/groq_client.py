"""Small Groq REST adapter. The hostname is fixed; keys are never sent elsewhere."""
import os
import time
import httpx
BASE="https://api.groq.com/openai/v1"
class ProviderError(RuntimeError): pass

def request(path,method="GET",payload=None,client=None):
    key=os.getenv("GROQ_API_KEY","").strip()
    if not key: raise ProviderError("Add GROQ_API_KEY to .env.local, then restart the local server")
    if path not in ("/models","/chat/completions"): raise ValueError("Unsupported Groq endpoint")
    owns_client=client is None
    client=client or httpx.Client(timeout=httpx.Timeout(120,connect=10),follow_redirects=False)
    try:
        for attempt in range(3):
            try:
                response=client.request(method,BASE+path,headers={"Authorization":"Bearer "+key},json=payload)
            except httpx.TransportError as exc:
                raise ProviderError("Cannot reach Groq. Check internet access and retry") from None
            if response.status_code in (429,500,502,503,504) and attempt<2:
                try: delay=float(response.headers.get("retry-after","1"))
                except ValueError: delay=1
                time.sleep(min(max(delay,0),5)); continue
            if response.status_code==401: raise ProviderError("Groq rejected the API key; check .env.local")
            if response.status_code==429: raise ProviderError("Groq rate limit reached. Wait and retry")
            if response.status_code==404: raise ProviderError("Groq model unavailable. Choose an accessible model using the provider check")
            if not response.is_success: raise ProviderError("Groq request failed (HTTP "+str(response.status_code)+"). Check model access/configuration")
            try: return response.json()
            except ValueError: raise ProviderError("Groq returned an invalid JSON response") from None
    finally:
        if owns_client: client.close()

def complete(model,messages,client=None):
    if model.startswith(("openai/","gemini","gpt-")):
        raise ProviderError("This project uses a non-OpenAI, non-Gemini Groq model; configure GROQ_MODEL")
    body=request("/chat/completions","POST",{"model":model,"messages":messages,"temperature":0,"max_completion_tokens":6000},client)
    try:
        text=body["choices"][0]["message"]["content"]
        if not isinstance(text,str) or not text.strip(): raise ValueError()
        return text
    except (KeyError,IndexError,TypeError,ValueError): raise ProviderError("Groq returned no text answer") from None

def models():
    return [row["id"] for row in request("/models").get("data",[]) if not row["id"].startswith("openai/")]
