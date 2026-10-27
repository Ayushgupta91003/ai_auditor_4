"""Run inside the configured agent container; makes a small Bedrock reporting call."""
import asyncio
import os
import httpx
from agent.mcp_client import Tools
from agent.settings import settings
async def main():
    async with Tools() as tools:
        required={"invoice_watcher","data_harvester","lang_bridge","invoice_parser","data_completeness_checker","business_validation","insight_reporter","vector_indexer","semantic_retriever","chunk_ranker","response_synthesizer","rag_evaluator"}
        assert required <= tools.names
        print("MCP discovery: all 12 tools present")
        text=await tools.call("insight_reporter",{"evidence":{"recommendation":"review","findings":[{"field":"unit_price","actual":"120","expected":"100"}],"translation_confidence":0.9}})
        assert isinstance(text,str) and len(text)>10
        print("MCP call -> A2A discovery -> Google ADK -> Bedrock Converse: response received")
if __name__=="__main__": asyncio.run(main())
