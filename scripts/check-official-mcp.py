#!/usr/bin/env python3
"""Opt-in real MCP reads; requires the official Python MCP SDK (mcp==1.30.0). No writes/data dumps."""
import asyncio
from pathlib import Path
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {'sync_application','create_application','delete_application','update_application',
             'run_resource_action','reload','quit','snapshot','delete_series','clean_tombstones'}

async def main():
    for name in ('argocd', 'metrics'):
        params = StdioServerParameters(command=sys.executable,
            args=[str(ROOT/'scripts/run-official-mcp.py'),name],cwd=str(ROOT))
        async with stdio_client(params) as (r,w):
            async with ClientSession(r,w) as client:
                await client.initialize()
                catalog = await client.list_tools()
                names = {tool.name for tool in catalog.tools}
                if not names or names & FORBIDDEN:
                    raise RuntimeError(name+': empty or unsafe catalog')
                tool, args = ('list_applications',{'limit':1}) if name=='argocd' else ('query',{'query':'1'})
                result = await client.call_tool(tool,args)
                if result.isError:
                    raise RuntimeError(name+': real read failed')
                print(name+': initialize, tools/list, write-tool exclusion and real bounded read passed ('+str(len(names))+' tools)')

if __name__ == '__main__':
    asyncio.run(main())
