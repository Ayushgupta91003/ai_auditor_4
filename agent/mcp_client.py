import json
import sys
import os
from datetime import timedelta
from contextlib import AsyncExitStack
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
class Tools:
    async def __aenter__(self):
        self.stack=AsyncExitStack()
        read,write=await self.stack.enter_async_context(stdio_client(StdioServerParameters(command=sys.executable,args=["-m","agent.mcp_server"],env=os.environ.copy())))
        self.session=await self.stack.enter_async_context(ClientSession(read,write,read_timeout_seconds=timedelta(seconds=300)))
        await self.session.initialize()
        self.names={t.name for t in (await self.session.list_tools()).tools}
        return self
    async def call(self,name,arguments):
        if name not in self.names: raise ValueError("Undiscovered MCP tool")
        from agent.observability import trace
        with trace("mcp-"+name):
            response=await self.session.call_tool(name,arguments=arguments)
        if response.isError: raise RuntimeError("MCP tool failed: "+name)
        # MCP structuredContent wraps non-dict results with a result property.
        if response.structuredContent is not None:
            result=response.structuredContent
            return result["result"] if set(result)=={"result"} else result
        text="".join(x.text for x in response.content if x.type=="text")
        try: return json.loads(text)
        except json.JSONDecodeError: return text
    async def __aexit__(self,*args): return await self.stack.__aexit__(*args)
