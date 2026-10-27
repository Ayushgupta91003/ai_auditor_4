"""Google ADK reporting role, exposed with the real A2A SDK adapter."""
import asyncio
import json
import os
from uuid import uuid4
from html import escape
import httpx
from google.adk.agents import BaseAgent
from google.adk.events import Event
from google.genai import types
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from a2a.types import AgentCard, AgentCapabilities, AgentSkill, SendMessageResponse
from agent.llm import ask
from agent.config import prompt
from agent.settings import settings

class ReportingAgent(BaseAgent):
    async def _run_async_impl(self, ctx):
        text = "\n".join(part.text or "" for part in ctx.user_content.parts)
        explanation = await asyncio.to_thread(ask,prompt("reporting"),text)
        yield Event(author=self.name,content=types.Content(role="model",parts=[types.Part(text=explanation)]))

card = AgentCard(name="InvoiceReporting",description="Explains computed invoice audit evidence",
    url=settings.a2a_url+"/",version="1.0.0",capabilities=AgentCapabilities(streaming=False),
    defaultInputModes=["text"],defaultOutputModes=["text"],skills=[AgentSkill(id="report",name="Audit report",
        description="Explain findings without changing the policy outcome",tags=["invoice","report"])])
a2a_app = to_a2a(ReportingAgent(name="invoice_reporter",description=card.description),agent_card=card)

async def explain(evidence):
    async with httpx.AsyncClient(timeout=150,follow_redirects=True,headers={"Authorization":"Bearer "+os.environ["SERVICE_TOKEN"]}) as client:
        discovery = await client.get(settings.a2a_url+"/.well-known/agent-card.json")
        discovery.raise_for_status()
        remote = AgentCard.model_validate(discovery.json())
        # Fixed allowlisted endpoint; never follow an arbitrary agent-card URL.
        if remote.url.rstrip("/") != settings.a2a_url.rstrip("/"): raise ValueError("Unexpected A2A destination")
        response = await client.post(remote.url,json={"jsonrpc":"2.0","id":str(uuid4()),"method":"message/send",
            "params":{"message":{"role":"user","messageId":str(uuid4()),"parts":[{"kind":"text","text":json.dumps(evidence)}]}}})
        response.raise_for_status()
        parsed = SendMessageResponse.model_validate(response.json()).model_dump(mode="json",exclude_none=True)
        if "error" in parsed: raise ValueError("A2A reporting failed")
        result = parsed["result"]
        if result.get("status",{}).get("state") in ("failed","rejected","canceled"):
            raise ValueError("Reporting agent failed")
        parts = result.get("parts",[])
        for artifact in result.get("artifacts",[]): parts.extend(artifact.get("parts",[]))
        text = "\n".join(part["text"] for part in parts if part.get("kind")=="text")
        if not text: raise ValueError("A2A response contained no report")
        return text

from agent.report_format import render_html
