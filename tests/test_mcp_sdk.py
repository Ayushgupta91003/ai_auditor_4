"""Actual MCP handshake, discovery and invocation using SDK memory transport."""
import asyncio
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch
SDK_AVAILABLE=importlib.util.find_spec("mcp") is not None

@unittest.skipUnless(SDK_AVAILABLE,"Install full requirements to execute the MCP SDK tests")
class MCPIntegrationTests(unittest.TestCase):
    def test_protocol_tool_discovery(self):
        from mcp.shared.memory import create_connected_server_and_client_session
        from agent.mcp_server import server
        async def exercise():
            async with create_connected_server_and_client_session(server) as session:
                names={tool.name for tool in (await session.list_tools()).tools}
                self.assertTrue({"invoice_watcher","data_harvester","lang_bridge","insight_reporter","vector_indexer","semantic_retriever","chunk_ranker","response_synthesizer","rag_evaluator"} <= names)
        asyncio.run(exercise())
    def test_protocol_invokes_real_document_harvester(self):
        from mcp.shared.memory import create_connected_server_and_client_session
        from agent.mcp_server import server,settings
        samples=Path(__file__).resolve().parents[1]/"samples"
        async def exercise():
            async with create_connected_server_and_client_session(server) as session:
                result=await session.call_tool("data_harvester",{"path":str(samples/"english.pdf")})
                self.assertFalse(result.isError)
                text="".join(c.text for c in result.content if c.type=="text")
                self.assertIn("INV-ENGLISH-001",text)
        with patch.object(settings,"incoming",samples):asyncio.run(exercise())
