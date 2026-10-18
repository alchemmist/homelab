import argparse
import base64
import json
import socket
import subprocess
import urllib.error
import urllib.parse
import urllib.request


URL = "https://grafana-mcp.socrat.alchemmist.xyz/mcp"


def load_token(ssh_host):
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", ssh_host,
         "env K3S_CONFIG_FILE=/dev/null k3s kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml -n cattle-monitoring-system get secret grafana-mcp-credentials -o json"],
        capture_output=True, text=True, timeout=30, check=True,
    )
    return base64.b64decode(json.loads(result.stdout)["data"]["client-token"]).decode()


class Client:
    def __init__(self, url, token):
        self.url = url
        self.headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.sequence = 0

    def request(self, method, params, notify=False):
        self.sequence += 1
        body = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notify:
            body["id"] = self.sequence
        request = urllib.request.Request(self.url, data=json.dumps(body).encode(), headers=self.headers)
        with self.opener.open(request, timeout=30) as response:
            if response.headers.get("Mcp-Session-Id"):
                self.headers["Mcp-Session-Id"] = response.headers["Mcp-Session-Id"]
            raw = response.read().decode()
        if notify:
            return None
        if raw.lstrip().startswith("{"):
            result = json.loads(raw)
        else:
            messages = [json.loads(line[5:].strip()) for line in raw.splitlines() if line.startswith("data:")]
            result = next(message for message in messages if message.get("id") == self.sequence)
        if "error" in result:
            raise RuntimeError("MCP protocol error")
        return result["result"]

    def tool(self, name, arguments):
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise RuntimeError("MCP tool failed: " + name)
        return "\n".join(block.get("text", "") for block in result.get("content", []))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=URL)
    parser.add_argument("--ssh-host", default="socrat-0")
    parser.add_argument("--address", help="Override DNS only in this test process while retaining TLS hostname validation")
    args = parser.parse_args()
    if args.address:
        hostname = urllib.parse.urlsplit(args.url).hostname
        original_resolver = socket.getaddrinfo
        socket.getaddrinfo = lambda host, *pos, **kw: original_resolver(args.address if host == hostname else host, *pos, **kw)
    client = Client(args.url, load_token(args.ssh_host))
    for authorization in [None, "Bearer invalid-test-token"]:
        headers = {"Accept": "application/json, text/event-stream"}
        if authorization:
            headers["Authorization"] = authorization
        try:
            client.opener.open(urllib.request.Request(args.url, headers=headers), timeout=15)
        except urllib.error.HTTPError as error:
            if error.code != 401:
                raise RuntimeError("Unexpected unauthenticated response") from None
        else:
            raise RuntimeError("MCP accepted invalid authentication")
    print("PASS: trusted HTTPS and both authentication rejection checks")
    initialized = client.request("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "homelab-check", "version": "1"}})
    client.headers["MCP-Protocol-Version"] = initialized["protocolVersion"]
    client.request("notifications/initialized", {}, notify=True)
    tools = client.request("tools/list", {})["tools"]
    if not tools or any(not tool.get("annotations", {}).get("readOnlyHint") for tool in tools):
        raise RuntimeError("Unexpected non-read-only tool")
    print(f"PASS: MCP initialized with {len(tools)} read-only tools")
    result = client.tool("search_dashboards", {"query": "Overview"})
    if "socrat-overview" not in result:
        raise RuntimeError("Overview was not found")
    result = client.tool("get_dashboard_by_uid", {"uid": "socrat-overview"})
    if "Cluster health" not in result:
        raise RuntimeError("Overview panels were not returned")
    print("PASS: dashboard search and full dashboard read")
    result = client.tool("query_prometheus", {"datasourceUid": "prometheus", "expr": "count(up)", "queryType": "instant", "endTime": "now"})
    parsed = json.loads(result)
    samples = parsed.get("data", [])
    if len(samples) != 1 or float(samples[0]["value"][1]) <= 0:
        raise RuntimeError("Prometheus returned no data")
    print("PASS: live Prometheus query returned data")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        print("FAIL:", type(error).__name__, str(error) if isinstance(error, RuntimeError) else "Connection or protocol check failed")
        raise SystemExit(1)
