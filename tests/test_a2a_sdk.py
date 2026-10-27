"""Real ADK/A2A adapter tests; the report model response is mocked explicitly."""
import importlib.util
import json
import unittest
from unittest.mock import patch

def available():
    try:return importlib.util.find_spec("google.adk") is not None and importlib.util.find_spec("a2a") is not None
    except ModuleNotFoundError:return False

@unittest.skipUnless(available(),"Install full requirements to test the real ADK/A2A adapter")
class A2AIntegrationTests(unittest.TestCase):
    def test_agent_card_discovery(self):
        from fastapi.testclient import TestClient
        from agent.reporting import a2a_app
        with TestClient(a2a_app) as client:
            response=client.get("/.well-known/agent-card.json")
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()["name"],"InvoiceReporting")
            self.assertTrue(any(s["id"]=="report" for s in response.json()["skills"]))
    def test_real_message_send_executes_adk_agent(self):
        from fastapi.testclient import TestClient
        from agent.reporting import a2a_app
        payload={"jsonrpc":"2.0","id":"sdk-test","method":"message/send","params":{"message":{
            "role":"user","messageId":"test-message-1","parts":[{"kind":"text","text":json.dumps({"recommendation":"review","findings":[]})}]}}}
        with patch("agent.reporting.ask",return_value="SDK test report: human review required.") as model:
            with TestClient(a2a_app) as client:response=client.post("/",json=payload)
        self.assertEqual(response.status_code,200,response.text)
        self.assertNotIn("error",response.json(),response.text)
        self.assertIn("SDK test report",response.text)
        model.assert_called_once()

    def test_langgraph_side_client_discovers_and_invokes_reporter(self):
        import asyncio
        import os
        import httpx
        from starlette.applications import Starlette
        from starlette.routing import Mount
        from agent import reporting
        original_client=httpx.AsyncClient
        parent=Starlette(routes=[Mount("/reporting",app=reporting.a2a_app)])
        def transport_client(**kwargs):
            return original_client(transport=httpx.ASGITransport(app=parent),**kwargs)
        async def exercise():
            await reporting.a2a_app.router.startup()
            try:
                with patch("agent.reporting.ask",return_value="Verified A2A client report"),patch("agent.reporting.httpx.AsyncClient",side_effect=transport_client),patch.dict(os.environ,{"SERVICE_TOKEN":"test-only-token"}):
                    text=await reporting.explain({"recommendation":"review","findings":[]})
                    self.assertEqual(text,"Verified A2A client report")
            finally:await reporting.a2a_app.router.shutdown()
        asyncio.run(exercise())
