#!/usr/bin/env python3
"""Configure the pg-mdb-backups Syncthing folder on a Socrat node.

The script runs on a Socrat node. It reads the node-local Syncthing API key from
/srv/syncthing/config/config.xml and configures the Kubernetes-hosted Syncthing
pod listening on hostNetwork localhost:8384.

No secrets are embedded here. Device IDs are public Syncthing identities.
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

MAC_ID = "W6ET4T3-XPAD52O-NJPCT5G-AW3OX7R-NASKRYZ-T2PZ62D-WQSIDM4-CEXOLAV"
SOCRAT0_ID = "CEUGPOG-MDQD3HI-M7Q5MDE-WOLEW5V-TZFXSBE-FP6VI5W-MGKQAE5-RLPSSAV"
# socrat-1 is currently offline, but keep it in the folder/device graph so the
# DaemonSet pod can join automatically when the node returns.
SOCRAT1_ID = "DYWEDAX-RDGBCC3-4AUXREZ-WGQLZJU-TT3HWIQ-2CSUQSE-WF2WVVH-4VV2IAP"
SOCRAT2_ID = "YYSU4UN-WFSESUW-NN7LPMM-JP2XKS6-OTU52IK-Z6SXXHF-TRN6CSJ-7JGCHAM"
PHONE_ID = "5R2QA45-SCZQL5S-EKW5SDB-C26ZNGK-FMH4KII-AJIRLKX-5EZ27QG-GYDXLQA"
OLD_YANDEX_MACBOOK_ID = "WEZT5SG-FJUY26T-F6E4XXW-MDP3NTE-PXUOOVU-T234ORE-SM5YIGC-L2OSAAU"
DEVICE_NAMES = {
    MAC_ID: "yandex-macbook",
    SOCRAT0_ID: "socrat-0",
    SOCRAT1_ID: "socrat-1",
    SOCRAT2_ID: "socrat-2",
    PHONE_ID: "phone",
}

FOLDER_ID = "pg-mdb-backups"
LABEL = "pg-mdb-encrypted-backups"
NODE_PATH = "/var/syncthing/pg_mdb_encrypted_backups"
CONFIG_XML = Path("/srv/syncthing/config/config.xml")
API = "http://127.0.0.1:8384"


def node_role() -> str:
    hn = socket.gethostname().split(".")[0]
    if hn in {"socrat-0", "socrat-1", "socrat-2"}:
        return hn
    raise SystemExit(f"Unsupported host for Syncthing backup config: {hn}")


def api_key() -> str:
    text = CONFIG_XML.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"<apikey>([^<]+)</apikey>", text)
    if not m:
        raise SystemExit(f"Cannot find Syncthing API key in {CONFIG_XML}")
    return m.group(1)


def req(method: str, path: str, data=None):
    headers = {"X-API-Key": api_key()}
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(API + path, data=body, headers=headers, method=method)
    with urllib.request.urlopen(r, timeout=30) as resp:
        txt = resp.read().decode()
        return json.loads(txt) if txt else None


def device(device_id: str, name: str, addresses=None) -> dict:
    return {
        "deviceID": device_id,
        "name": name,
        "addresses": addresses or ["dynamic"],
        "compression": "metadata",
        "certName": "",
        "introducer": False,
        "skipIntroductionRemovals": False,
        "introducedBy": "",
        "paused": False,
        "allowedNetworks": [],
        "autoAcceptFolders": False,
        "maxSendKbps": 0,
        "maxRecvKbps": 0,
        "ignoredFolders": [],
        "maxRequestKiB": 0,
        "untrusted": False,
        "remoteGUIPort": 0,
        "numConnections": 0,
        "group": "",
    }


def folder(this_id: str, peer_ids: list[str]) -> dict:
    return {
        "id": FOLDER_ID,
        "label": LABEL,
        "filesystemType": "basic",
        "path": NODE_PATH,
        "type": "receiveonly",
        "devices": [
            {"deviceID": d, "introducedBy": "", "encryptionPassword": ""}
            for d in [this_id, MAC_ID, *peer_ids]
        ],
        "group": "",
        "rescanIntervalS": 60,
        "fsWatcherEnabled": True,
        "fsWatcherDelayS": 10,
        "fsWatcherTimeoutS": 0,
        "ignorePerms": True,
        "autoNormalize": True,
        "minDiskFree": {"value": 1, "unit": "%"},
        "versioning": {"type": "", "params": {}, "cleanupIntervalS": 3600, "fsPath": "", "fsType": "basic"},
        "copiers": 0,
        "pullerMaxPendingKiB": 0,
        "hashers": 0,
        "order": "random",
        "ignoreDelete": False,
        "scanProgressIntervalS": 0,
        "pullerPauseS": 0,
        "pullerDelayS": 1,
        "maxConflicts": 10,
        "disableSparseFiles": False,
        "paused": False,
        "markerName": ".stfolder",
        "copyOwnershipFromParent": False,
        "modTimeWindowS": 0,
        "maxConcurrentWrites": 16,
        "disableFsync": False,
        "blockPullOrder": "standard",
        "copyRangeMethod": "standard",
        "caseSensitiveFS": False,
        "junctionsAsDirs": False,
        "syncOwnership": False,
        "sendOwnership": False,
        "syncXattrs": False,
        "sendXattrs": False,
        "blockIndexing": True,
        "xattrFilter": {"entries": [], "maxSingleEntrySize": 1024, "maxTotalSize": 4096},
    }


def desired_for(role: str) -> tuple[str, list[dict], list[str]]:
    if role == "socrat-0":
        return SOCRAT0_ID, [
            device(MAC_ID, "antonmoss-mac", ["dynamic"]),
            device(SOCRAT1_ID, "socrat-1-syncthing", ["tcp://192.168.0.24:22000", "quic://192.168.0.24:22000", "dynamic"]),
            device(SOCRAT2_ID, "socrat-2-syncthing", ["tcp://10.250.0.2:22000", "quic://10.250.0.2:22000", "dynamic"]),
        ], [SOCRAT1_ID, SOCRAT2_ID]
    if role == "socrat-1":
        return SOCRAT1_ID, [
            device(MAC_ID, "antonmoss-mac", ["dynamic"]),
            device(SOCRAT0_ID, "socrat-0-syncthing", ["tcp://192.168.0.23:22000", "quic://192.168.0.23:22000", "dynamic"]),
            device(SOCRAT2_ID, "socrat-2-syncthing", ["dynamic"]),
        ], [SOCRAT0_ID, SOCRAT2_ID]
    if role == "socrat-2":
        return SOCRAT2_ID, [
            device(MAC_ID, "antonmoss-mac", ["dynamic"]),
            device(SOCRAT0_ID, "socrat-0-syncthing", ["tcp://192.168.0.23:22000", "quic://192.168.0.23:22000", "dynamic"]),
            device(SOCRAT1_ID, "socrat-1-syncthing", ["dynamic"]),
        ], [SOCRAT0_ID, SOCRAT1_ID]
    raise SystemExit(f"Unsupported role: {role}")


def configure(role: str) -> bool:
    this_id, wanted_devices, peers = desired_for(role)
    cfg = req("GET", "/rest/config")
    changed = False

    by_dev = {d["deviceID"]: d for d in cfg.get("devices", [])}
    # Remove the old duplicate yandex-macbook identity. The active Mac device is
    # MAC_ID above. Keep knowledge-base devices (phone, yandex-macbook,
    # socrat-*) intact.
    before_devices = len(cfg.get("devices", []))
    cfg["devices"] = [d for d in cfg.get("devices", []) if d.get("deviceID") != OLD_YANDEX_MACBOOK_ID]
    if len(cfg["devices"]) != before_devices:
        changed = True
    for existing_folder in cfg.get("folders", []):
        before = len(existing_folder.get("devices", []))
        existing_folder["devices"] = [d for d in existing_folder.get("devices", []) if d.get("deviceID") != OLD_YANDEX_MACBOOK_ID]
        if len(existing_folder["devices"]) != before:
            changed = True

    wanted_devices = [*wanted_devices, device(PHONE_ID, "phone", ["dynamic"])]
    by_dev = {d["deviceID"]: d for d in cfg.get("devices", [])}
    for d in wanted_devices:
        if d["deviceID"] not in by_dev:
            cfg.setdefault("devices", []).append(d)
            changed = True
        else:
            wanted_name = DEVICE_NAMES.get(d["deviceID"], d["name"])
            if by_dev[d["deviceID"]].get("name") != wanted_name:
                by_dev[d["deviceID"]]["name"] = wanted_name
                changed = True
    for d in cfg.get("devices", []):
        wanted_name = DEVICE_NAMES.get(d.get("deviceID"))
        if wanted_name and d.get("name") != wanted_name:
            d["name"] = wanted_name
            changed = True

    desired_folder = folder(this_id, peers)
    by_folder = {f["id"]: f for f in cfg.get("folders", [])}
    if FOLDER_ID not in by_folder:
        cfg.setdefault("folders", []).append(desired_folder)
        changed = True
    else:
        cur = by_folder[FOLDER_ID]
        for key in ["label", "path", "type", "rescanIntervalS", "fsWatcherEnabled", "fsWatcherDelayS", "ignorePerms"]:
            if cur.get(key) != desired_folder[key]:
                cur[key] = desired_folder[key]
                changed = True
        cur_devices = {d["deviceID"]: d for d in cur.get("devices", [])}
        for d in desired_folder["devices"]:
            if d["deviceID"] not in cur_devices:
                cur.setdefault("devices", []).append(d)
                changed = True

    if changed:
        req("PUT", "/rest/config", cfg)
        try:
            req("POST", "/rest/system/restart")
        except urllib.error.URLError:
            pass
    print(json.dumps({"role": role, "changed": changed, "folder": FOLDER_ID, "path": NODE_PATH}))
    return changed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--role", default=node_role())
    args = ap.parse_args()
    configure(args.role)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
