import http.client
import json
import socket
import ssl
import subprocess
import urllib.request
from collections.abc import Iterator
from typing import Protocol, cast


class _Json(Protocol):
    def __getitem__(self, key: str) -> "_Json": ...

    def get(self, key: str, default: object = None) -> object: ...

    def __iter__(self) -> Iterator["_Json"]: ...

    def __add__(self, other: str) -> str: ...

    def __radd__(self, other: str) -> str: ...

    def __lt__(self, other: object) -> bool: ...

    def __bool__(self) -> bool: ...


class _GatewayConnection(http.client.HTTPSConnection):
    def __init__(self, endpoint: str) -> None:
        super().__init__(
            "rancher.socrat.alchemmist.xyz",
            timeout=30,
            context=ssl.create_default_context(),
        )
        self.gateway_endpoint = endpoint

    def _create_connection(
        self,
        _address: tuple[str, int],
        timeout: float | None = None,
        _source_address: tuple[str, int] | None = None,
    ) -> socket.socket:
        return socket.create_connection(
            (self.gateway_endpoint, 443),
            timeout,
            source_address=("10.250.0.1", 0),
        )


def kubectl(*arguments: str) -> _Json:
    loaded: object = json.loads(
        subprocess.check_output(
            ["kubectl", *arguments, "-o", "json"],
            stderr=subprocess.DEVNULL,
        )
    )
    return cast("_Json", loaded)


def verify() -> None:
    expected = sorted(str(node["metadata"]["name"]) for node in kubectl("get", "nodes")["items"])
    tokens = kubectl("get", "tokens.management.cattle.io")["items"]
    token = next(
        item
        for item in tokens
        if not item.get("expired") and item.get("token") and item.get("enabled") is not False
    )
    authorization = "Bearer " + str(token["metadata"]["name"]) + ":" + str(token["token"])
    pods = kubectl("-n", "cattle-system", "get", "pods", "-l", "app=rancher")["items"]
    endpoints = [
        (str(pod["metadata"]["name"]), "http://" + str(pod["status"]["podIP"])) for pod in pods
    ]
    endpoints.extend(("gateway-" + address, address) for address in ("10.250.0.1", "10.250.0.3"))
    for name, endpoint in endpoints:
        headers = {
            "Authorization": authorization,
            "Host": "rancher.socrat.alchemmist.xyz",
            "X-Forwarded-Proto": "https",
        }
        if name.startswith("gateway-"):
            connection = _GatewayConnection(endpoint)
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
