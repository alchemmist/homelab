"""Smoke-check the public Grafana MCP proxy endpoint."""
import argparse
import base64
import json
import socket
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus

URL = "https://grafana-mcp.socrat.alchemmist.xyz/mcp"


def load_token(ssh_host):
    """Perform the load token operation."""
    result = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            ssh_host,
            "env K3S_CONFIG_FILE=/dev/null k3s kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml -n cattle-monitoring-system get secret grafana-mcp-credentials -o json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return base64.b64decode(json.loads(result.stdout)["data"]["client-token"]).decode()


class Client:
    """Minimal Grafana MCP HTTP client."""

    def __init__(self, url: str, token: str) -> None:
        """Initialize the Grafana MCP client."""
        self.url = url
        self.headers = {
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.sequence = 0

    def request(
        self, method: str, params: dict[str, object], *, notify: bool = False
    ) -> dict[str, object]:
        """Send one JSON-RPC request to the MCP server."""
        self.sequence += 1
        body = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notify:
            body["id"] = self.sequence
        request = urllib.request.Request(
            self.url, data=json.dumps(body).encode(), headers=self.headers
        )
        with self.opener.open(request, timeout=30) as response:
            if response.headers.get("Mcp-Session-Id"):
                self.headers["Mcp-Session-Id"] = response.headers["Mcp-Session-Id"]
            raw = response.read().decode()
        if notify:
            return None
        if raw.lstrip().startswith("{"):
            result = json.loads(raw)
        else:
            messages = [
                json.loads(line[5:].strip())
                for line in raw.splitlines()
                if line.startswith("data:")
            ]
            result = next(message for message in messages if message.get("id") == self.sequence)
        if "error" in result:
            message = "MCP protocol error"
            raise RuntimeError(message)
        return result["result"]

    def tool(self, name: str, arguments: dict[str, object]) -> str:
        """Call one MCP tool and fail loudly on tool errors."""
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise RuntimeError("MCP tool failed: " + name)
        return "\n".join(block.get("text", "") for block in result.get("content", []))


def _rejection_checks(client: Client, url: str) -> None:
    """Require the endpoint to refuse invalid and missing authentication."""
    for authorization in [None, "Bearer invalid-test-token"]:
        headers = {"Accept": "application/json, text/event-stream"}
        if authorization:
            headers["Authorization"] = authorization
        try:
            client.opener.open(urllib.request.Request(url, headers=headers), timeout=15)
        except urllib.error.HTTPError as error:
            if error.code != HTTPStatus.UNAUTHORIZED:
                message = "Unexpected unauthenticated response"
                raise RuntimeError(message) from None
        else:
            message = "MCP accepted invalid authentication"
            raise RuntimeError(message)


def _check_dashboards(client: Client) -> None:
    """Search the overview dashboard and verify a full read returns its panels."""
    result = client.tool("search_dashboards", {"query": "Overview"})
    if "socrat-overview" not in result:
        message = "Overview was not found"
        raise RuntimeError(message)
    result = client.tool("get_dashboard_by_uid", {"uid": "socrat-overview"})
    if "Cluster health" not in result:
        message = "Overview panels were not returned"
        raise RuntimeError(message)
    print("PASS: dashboard search and full dashboard read")


def _check_prometheus(client: Client) -> None:
    """Run one instant query and require a strictly positive sample."""
    result = client.tool(
        "query_prometheus",
        {
            "datasourceUid": "prometheus",
            "expr": "count(up)",
            "queryType": "instant",
            "endTime": "now",
        },
    )
    parsed = json.loads(result)
    samples = parsed.get("data", [])
    if len(samples) != 1 or float(samples[0]["value"][1]) <= 0:
        message = "Prometheus returned no data"
        raise RuntimeError(message)
    print("PASS: live Prometheus query returned data")


def main():
    """Run the command-line entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=URL)
    parser.add_argument("--ssh-host", default="socrat-0")
    parser.add_argument(
        "--address",
        help="Override DNS only in this test process while retaining TLS hostname validation",
    )
    args = parser.parse_args()
    if args.address:
        hostname = urllib.parse.urlsplit(args.url).hostname
        original_resolver = socket.getaddrinfo
        socket.getaddrinfo = lambda host, *pos, **kw: original_resolver(
            args.address if host == hostname else host, *pos, **kw
        )
    client = Client(args.url, load_token(args.ssh_host))
    _rejection_checks(client, args.url)
    print("PASS: trusted HTTPS and both authentication rejection checks")
    initialized = client.request(
        "initialize",
        {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "homelab-check", "version": "1"},
        },
    )
    client.headers["MCP-Protocol-Version"] = initialized["protocolVersion"]
    client.request("notifications/initialized", {}, notify=True)
    tools = client.request("tools/list", {})["tools"]
    if not tools or any(not tool.get("annotations", {}).get("readOnlyHint") for tool in tools):
        message = "Unexpected non-read-only tool"
        raise RuntimeError(message)
    print(f"PASS: MCP initialized with {len(tools)} read-only tools")
    _check_dashboards(client)
    _check_prometheus(client)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        print(
            "FAIL:",
            type(error).__name__,
            str(error)
            if isinstance(error, RuntimeError)
            else "Connection or protocol check failed",
        )
        raise SystemExit(1)
