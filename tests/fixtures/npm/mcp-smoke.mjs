// Run inside the freshly installed official client tree, never against a real service.
import assert from 'node:assert/strict';
import http from 'node:http';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';

const requests = [];
const api = http.createServer((req, res) => {
  requests.push([req.method, req.url]);
  res.writeHead(200, { 'content-type': 'application/json' });
  res.end(JSON.stringify({ items: [{ metadata: { name: 'fixture-app' } }] }));
});
await new Promise(resolve => api.listen(0, '127.0.0.1', resolve));
const url = `http://127.0.0.1:${api.address().port}`;
async function stdio(args, env, verify) {
  const client = new Client({ name: 'offline-fixture', version: '1.0.0' });
  try {
    await client.connect(new StdioClientTransport({ command: process.execPath, args, env }));
    await verify(client);
  } finally {
    await client.close();
  }
}
try {
  await stdio(['node_modules/argocd-mcp/dist/index.js', 'stdio'], {
    ARGOCD_BASE_URL: url, MCP_READ_ONLY: 'true', ARGOCD_API_TOKEN: 'fixture-only',
  }, async client => {
    const { tools } = await client.listTools();
    const list = tools.find(t => t.name === 'list_applications');
    assert.equal(list.inputSchema.properties.limit.type, 'integer');
    assert(!tools.some(t => /^(create|update|delete|sync|run)_/.test(t.name)));
    const invalid = await client.callTool({ name: list.name, arguments: { limit: -1 } });
    assert.equal(invalid.isError, true);
    assert.equal(requests.length, 0);
    const result = await client.callTool({ name: list.name, arguments: { limit: 1 } });
    assert.equal(JSON.parse(result.content[0].text).items[0].metadata.name, 'fixture-app');
    assert.deepEqual(requests, [['GET', '/api/v1/applications']]);
  });
  await stdio(['node_modules/@umami/mcp/bin/umami-mcp.js'], {
    UMAMI_URL: url, UMAMI_API_TOKEN: 'fixture-only',
  }, async client => assert((await client.listTools()).tools.some(t => t.name === 'list_websites')));
} finally {
  api.close();
}
