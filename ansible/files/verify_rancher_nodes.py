import http.client
import json
import socket
import ssl
import subprocess
import urllib.request
from typing import cast


def kubectl(*arguments) -> dict[str, object]:
    document: dict[str, object] = json.loads(
        subprocess.check_output(
            ["kubectl", *arguments, "-o", "json"],
            stderr=subprocess.DEVNULL,
        )
    )
    return document


def verify() -> None:
    nodes = cast("list[dict[str, object]]", kubectl("get", "nodes")["items"])
    expected = sorted(
        cast("str", cast("dict[str, object]", node["metadata"])["name"]) for node in nodes
    )
    tokens = cast("list[dict[str, object]]", kubectl("get", "tokens.management.cattle.io")["items"])
    token = next(
        item
        for item in tokens
        if not item.get("expired") and item.get("token") and item.get("enabled") is not False
    )
    authorization = (
        "Bearer "
        + cast("str", cast("dict[str, object]", token["metadata"])["name"])
        + ":"
        + cast("str", token["token"])
    )
    pods = cast(
        "list[dict[str, object]]",
        kubectl("-n", "cattle-system", "get", "pods", "-l", "app=rancher")["items"],
    )
    endpoints = [
        (
            cast("str", cast("dict[str, object]", pod["metadata"])["name"]),
            "http://" + cast("str", cast("dict[str, object]", pod["status"])["podIP"]),
        )
        for pod in pods
    ]
    endpoints.extend(("gateway-" + address, address) for address in ("10.250.0.1", "10.250.0.3"))
    for name, endpoint in endpoints:
        headers = {
            "Authorization": authorization,
            "Host": "rancher.socrat.alchemmist.xyz",
            "X-Forwarded-Proto": "https",
        }
        if name.startswith("gateway-"):
            connection = http.client.HTTPSConnection(
                "rancher.socrat.alchemmist.xyz",
                timeout=30,
                context=ssl.create_default_context(),
            )
            connection._create_connection = lambda target, timeout, source_address=None: (
                socket.create_connection(
                    (endpoint, 443),
                    timeout,
                    source_address=("10.250.0.1", 0),
                )
            )
            try:
                connection.request("GET", "/k8s/clusters/local/v1/nodes", headers=headers)
                response = connection.getresponse()
                if response.status != 200:
                    raise RuntimeError("Rancher API returned HTTP " + str(response.status))
                result = json.load(response)
            finally:
                connection.close()
        else:
            request = urllib.request.Request(
                endpoint + "/k8s/clusters/local/v1/nodes", headers=headers
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                result = json.load(response)
        actual = sorted(node["metadata"]["name"] for node in result["data"])
        print(name, "nodes=" + ",".join(actual), "revision=" + str(result.get("revision")))
        if actual != expected:
            raise RuntimeError("Rancher node list does not match Kubernetes on " + name)


if __name__ == "__main__":
    verify()
