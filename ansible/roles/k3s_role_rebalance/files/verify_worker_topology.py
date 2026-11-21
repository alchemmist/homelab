"""Read-only verification of the topology replacing the 2026-10 rebalance."""

import json
import sys

from etcd_members import Etcd, require_members

VOTERS = {"socrat-0", "socrat-1", "socrat-2"}


def verify(client):
    members = client.members()
    require_members(members, VOTERS)
    for name in sorted(VOTERS):
        client.health(name)
        status = client.status(name)
        if int(status["header"]["member_id"]) != members[name]["id"]:
            raise RuntimeError("Endpoint member identity mismatch for " + name)
    if client.members() != members:
        raise RuntimeError("Membership changed during verification")
    return {"changed": False, "members": members, "worker": "socrat-3"}


if __name__ == "__main__":
    try:
        pass
    except Exception as error:
        sys.exit(1)
