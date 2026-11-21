import argparse
import json
import subprocess
import sys
import time

ENDPOINTS = {
    "socrat-0": "https://192.168.0.23:2379",
    "socrat-1": "https://192.168.0.24:2379",
    "socrat-2": "https://10.250.0.2:2379",
    "socrat-3": "https://10.250.0.5:2379",
}
PEERS = {
    name: endpoint.replace(":2379", ":2380") for name, endpoint in ENDPOINTS.items()
}
FINAL = {"socrat-0", "socrat-2", "socrat-3"}
TLS = "/var/lib/rancher/k3s/server/tls/etcd/"


class Etcd:
    def call(self, args, endpoint="https://127.0.0.1:2379", structured=True) -> object:
        command = [
            "etcdctl",
            "--endpoints=" + endpoint,
            "--cacert=" + TLS + "server-ca.crt",
            "--cert=" + TLS + "client.crt",
            "--key=" + TLS + "client.key",
            "--dial-timeout=5s",
            "--command-timeout=10s",
        ]
        if structured:
            command.append("--write-out=json")
        result = subprocess.run(
            command + args, capture_output=True, text=True, timeout=15
        )
        if result.returncode:
            raise RuntimeError("etcdctl operation failed: " + " ".join(args))
        return json.loads(result.stdout) if structured else result.stdout

    def members(self) -> dict[str, dict[str, object]]:
        listing = self.call(["member", "list"])
        if not isinstance(listing, dict):
            message = "Unexpected etcdctl member listing payload"
            raise RuntimeError(message)
        entries = listing["members"]
        if not isinstance(entries, list):
            message = "Unexpected etcdctl member listing payload"
            raise RuntimeError(message)
        result: dict[str, dict[str, object]] = {}
        for member in entries:
            matches = [
                name
                for name, peer in PEERS.items()
                if member.get("peerURLs") == [peer]
                and (
                    member.get("name") == name
                    or member.get("name", "").startswith(name + "-")
                )
            ]
            if len(matches) != 1 or matches[0] in result:
                raise RuntimeError(
                    "Unknown or duplicate etcd member; refusing reconfiguration"
                )
            result[matches[0]] = {
                "id": int(member["ID"]),
                "id_hex": format(int(member["ID"]), "x"),
                "peer_urls": member["peerURLs"],
                "learner": member.get("isLearner", False),
            }
        return result

    def health(self, name) -> None:
        result = self.call(["endpoint", "health"], ENDPOINTS[name])
        if not isinstance(result, list):
            message = "Unexpected etcdctl health payload"
            raise RuntimeError(message)
        if len(result) != 1 or result[0].get("health") is not True:
            raise RuntimeError("Linearizable health check failed for " + name)

    def status(self, name) -> dict[str, object]:
        result = self.call(["endpoint", "status"], ENDPOINTS[name])
        if not isinstance(result, list):
            message = "Unexpected etcdctl status payload"
            raise RuntimeError(message)
        if len(result) != 1 or result[0].get("Error"):
            message = "Endpoint status failed for " + name
            raise RuntimeError(message)
        status: dict[str, object] = result[0]["Status"]
        return status


def require_members(members, names) -> None:
    if set(members) != set(names) or any(item["learner"] for item in members.values()):
        raise RuntimeError("Unexpected voting membership; refusing reconfiguration")


def verify_final(client) -> dict[str, dict[str, object]]:
    members: dict[str, dict[str, object]] = client.members()
    require_members(members, FINAL)
    for name in ("socrat-0", "socrat-3"):
        client.health(name)
    return members


def remove_socrat_1(client) -> dict[str, object]:
    members = client.members()
    if set(members) == FINAL:
        return {"changed": False, "members": verify_final(client)}
    require_members(members, ENDPOINTS)
    for name in ("socrat-0", "socrat-1", "socrat-3"):
        client.health(name)
        status = client.status(name)
        header = status["header"]
        if not isinstance(header, dict):
            raise RuntimeError("Endpoint status failed for " + name)
        if int(header["member_id"]) != members[name]["id"]:
            raise RuntimeError("Endpoint member identity mismatch for " + name)
    status = client.status("socrat-1")
    if int(status["leader"]) == members["socrat-1"]["id"]:
        client.call(
            ["move-leader", members["socrat-0"]["id_hex"]],
            ENDPOINTS["socrat-1"],
            structured=False,
        )
        for attempt in range(10):
            leader = client.status("socrat-0")["leader"]
            if int(leader) == members["socrat-0"]["id"]:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Leadership transfer did not converge")
    current = client.members()
    if current != members:
        raise RuntimeError("Membership changed during preflight; refusing removal")
    try:
        client.call(
            ["member", "remove", members["socrat-1"]["id_hex"]], structured=False
        )
    except (RuntimeError, subprocess.TimeoutExpired):
        current = client.members()
        if "socrat-1" in current:
            raise RuntimeError(
                "Removal failed and socrat-1 remains a member; restore its staged configuration"
            ) from None
    return {"changed": True, "members": verify_final(client)}


def inspect(client) -> dict[str, object]:
    members = client.members()
    endpoints: dict[str, dict[str, object]] = {}
    for name in members:
        try:
            status = client.status(name)
            client.health(name)
            header = status["header"]
            if not isinstance(header, dict):
                raise RuntimeError("Endpoint status failed for " + name)
            endpoints[name] = {
                "healthy": True,
                "member_id": header["member_id"],
                "leader_id": status["leader"],
            }
        except (RuntimeError, subprocess.TimeoutExpired):
            endpoints[name] = {"healthy": False}
    return {
        "changed": False,
        "members": members,
        "expected_final_members": sorted(FINAL),
        "endpoints": endpoints,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action", choices=["inspect", "remove-socrat-1", "verify-final"]
    )
    args = parser.parse_args()
    try:
        if args.action == "inspect":
            result = inspect(Etcd())
        elif args.action == "verify-final":
            result = {"changed": False, "members": verify_final(Etcd())}
        else:
            result = remove_socrat_1(Etcd())
        print(json.dumps(result, sort_keys=True))
    except (
        RuntimeError,
        subprocess.TimeoutExpired,
        ValueError,
        KeyError,
        OSError,
    ) as error:
        print(json.dumps({"error": str(error), "ok": False}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
