"""One gateway: Bedrock Converse for the capstone; user-authorized Groq for local work."""
import hashlib
import json
import os
import re
from functools import lru_cache
from agent.settings import settings

@lru_cache
def chat_client(model):
    # Lazy imports ensure local Groq does not initialize AWS or require AWS credentials.
    from langchain_aws import ChatBedrockConverse
    from botocore.config import Config
    options={}
    if os.getenv("BEDROCK_GUARDRAIL_ID"):
        options["guardrail_config"]={"guardrailIdentifier":os.environ["BEDROCK_GUARDRAIL_ID"],"guardrailVersion":os.environ["BEDROCK_GUARDRAIL_VERSION"],"trace":"enabled"}
    return ChatBedrockConverse(model=model,region_name=settings.region,temperature=0,max_tokens=settings.max_output_tokens,
        config=Config(connect_timeout=10,read_timeout=120,retries={"max_attempts":2}),**options)

@lru_cache
def gateway():
    import litellm
    class BedrockProvider(litellm.CustomLLM):
        def completion(self,model,messages,**kwargs):
            result=chat_client(model.removeprefix("converse/")).invoke([(m["role"],m["content"]) for m in messages])
            content=result.content
            text=content if isinstance(content,str) else "".join(b.get("text","") for b in content if isinstance(b,dict))
            return response(model,text)
    class GroqProvider(litellm.CustomLLM):
        def completion(self,model,messages,**kwargs):
            from agent.groq_client import complete
            return response(model,complete(model.removeprefix("groq_local/"),messages))
    def response(model,text):
        return litellm.ModelResponse(model=model,choices=[{"index":0,"message":{"role":"assistant","content":text},"finish_reason":"stop"}])
    existing=[p for p in litellm.custom_provider_map if p["provider"] not in ("converse","groq_local")]
    litellm.custom_provider_map=existing+[{"provider":"converse","custom_handler":BedrockProvider()},{"provider":"groq_local","custom_handler":GroqProvider()}]
    litellm.telemetry=False
    litellm.turn_off_message_logging=True
    return litellm

def ask(system,data,model=None,cache=None):
    if settings.provider not in ("bedrock","groq"): raise ValueError("LLM_PROVIDER must be bedrock or groq")
    model=model or settings.model
    messages=[{"role":"system","content":system},{"role":"user","content":data}]
    key="llm:"+hashlib.sha256(json.dumps([settings.provider,model,messages],sort_keys=True).encode()).hexdigest()
    if cache:
        hit=cache.get(key)
        if hit: return hit
    from agent.observability import trace
    with trace(settings.provider+"-chat"):
        prefix="groq_local/" if settings.provider=="groq" else "converse/"
        if settings.provider=="groq" and os.getenv("LOCAL_DEVELOPMENT")=="true":
            # Laptop profile avoids LiteLLM's optional tokenizer downloads on offline machines.
            from agent.groq_client import complete
            text=complete(model,messages)
        else:
            result=gateway().completion(model=prefix+model,messages=messages)
            text=result.choices[0].message.content
    if cache: cache.setex(key,3600,text)
    return text

def parse_json(text):
    # Some reasoning models include a think block before their final JSON.
    text=re.sub(r"<think>.*?</think>","",text,flags=re.S).strip()
    if text.startswith("```"): text=text.split("\n",1)[1].rsplit("```",1)[0].strip()
    result=json.loads(text)
    if not isinstance(result,dict): raise ValueError("Expected a JSON object from model")
    return result

def json_answer(system,data,**kwargs):
    # Domain tools cache validated outputs; never retain malformed JSON across retries.
    kwargs.pop("cache",None)
    return parse_json(ask(system+"\nReturn only the requested JSON object, without reasoning or markdown.",data,**kwargs))

def embed(text):
    if os.getenv("EMBEDDING_PROVIDER","bedrock")=="local":
        from agent.local_vectors import vectorize
        return vectorize(text)
    import boto3
    from botocore.config import Config
    result=boto3.client("bedrock-runtime",region_name=settings.region,
        config=Config(connect_timeout=10,read_timeout=60,retries={"max_attempts":2})).invoke_model(
            modelId=settings.embedding_model,body=json.dumps({"inputText":text,"dimensions":1024,"normalize":True}))
    return json.loads(result["body"].read())["embedding"]
