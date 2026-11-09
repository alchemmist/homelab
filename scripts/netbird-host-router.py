#!/usr/bin/env python3
"""Plan NetBird peers on the existing socrat-0 and socrat-2 hosts.

The default command path only validates and renders files. It does not enroll
peers, talk to management, or change WireGuard, K3s, or OpenSSH.
"""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "deploy/netbird/images.lock.json"
TABLE = "netbird_host_router"
IFACE = "nb-host"
FRONTEND_PORT = 8443
GRAFANA = "grafana.socrat.alchemmist.xyz"
UPSTREAM_IP = "10.250.0.3"
UPSTREAM_PORT = 443
SSH_ADDR = "10.250.0.2"
SSH_PORTS = {22, 2222}
CLIENT_MEM = "96m"
FRONTEND_MEM = "32m"
HEADROOM_MIB = 256
VPS_OBSERVED_KIB = 455948
OVERLAY_TOKEN = "__NB_OVERLAY_IP__"
URL_TOKEN = "__MANAGEMENT_URL__"
FORBIDDEN_IFACES = {
    "wg-socrat", "cni0", "docker0", "eth0", "eno1", "wlan0", "enp2s0", "lo", "wt0",
}
PROTECTED = [
    "0.0.0.0/8", "10.42.0.0/16", "10.43.0.0/16", "10.250.0.0/24",
    "172.17.0.0/16", "172.18.0.0/16", "176.98.185.0/24", "192.168.0.0/24",
]
HOSTS = ("socrat-0", "socrat-2")
EXECUTABLE_MARKERS = (
    "/etc/wireguard", "wg-quick", "wg set", "wg addconf", "authorized_keys",
    "sshd_config", "--privileged", "--allow-server-ssh=true", "0.0.0.0/0",
    "10.42.0.0", "10.43.0.0", "10.250.0.0/24", "docker.sock", "/etc/ssh",
    "ip route", "ip rule",
)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def default_facts():
    """Observed hosts. ssh_probe is a TCP connect, not an OpenSSH login."""
    return {
        "schema_version": 1,
        "overlay_cidr": "100.96.0.0/16",
        "interface": IFACE,
        "frontend_port": FRONTEND_PORT,
        "frontend_name": GRAFANA,
        "upstream_address": UPSTREAM_IP,
        "upstream_port": UPSTREAM_PORT,
        "ssh_address": SSH_ADDR,
        "ssh_port": 2222,
        "ssh_probe": {
            "address": SSH_ADDR,
            "accepted_port": 2222,
            "refused_ports": [22, 2224],
            "method": "tcp-connect",
            "login": False,
        },
        "management_url": None,
        "client_memory": CLIENT_MEM,
        "frontend_memory": FRONTEND_MEM,
        "hosts": [
            {
                "name": "socrat-0",
                "failure_domain": "home-lan",
                "owned": ["10.250.0.1", "192.168.0.23"],
                "public_addresses": [],
                "egress_iface": "wg-socrat",
                "snat_address": "10.250.0.1",
                "routes": ["10.250.0.0/24"],
                "mem_available_kib": 14630540,
                "sudo_nopass": False,
                "runtime": None,
            },
            {
                "name": "socrat-2",
                "failure_domain": "vps-109.120.141.60",
                "owned": ["10.250.0.2", "109.120.141.60"],
                "public_addresses": ["109.120.141.60"],
                "egress_iface": "wg-socrat",
                "snat_address": "10.250.0.2",
                "routes": ["10.250.0.0/24", "192.168.0.23/32", "192.168.0.24/32"],
                "mem_available_kib": VPS_OBSERVED_KIB,
                "sudo_nopass": False,
                "runtime": "docker",
            },
        ],
    }


def parse_mib(value):
    match = re.fullmatch(r"([1-9][0-9]*)m", value or "")
    require(match is not None, "memory limit must look like 96m")
    return int(match.group(1))


def client_image():
    item = json.loads(LOCK.read_text())["images"]["client"]
    require(item["repository"] == "netbirdio/netbird" and item["tag"] == "0.82.0",
            "client lock is not the pinned 0.82.0 image")
    require(re.fullmatch(r"sha256:[0-9a-f]{64}", item["digest"]) is not None, "client digest invalid")
    return item["repository"] + ":" + item["tag"] + "@" + item["digest"]


def _host_map(facts):
    hosts = facts["hosts"]
    require(isinstance(hosts, list) and [h.get("name") for h in hosts] == list(HOSTS),
            "hosts must be exactly socrat-0 then socrat-2")
    return {h["name"]: h for h in hosts}


def classify(host, address):
    ip = ipaddress.ip_address(address)
    owned = {ipaddress.ip_address(item) for item in host["owned"]}
    if ip in owned:
        return "input"
    for route in host["routes"]:
        if ip in ipaddress.ip_network(route):
            return "forward"
    return "unreachable"


def validate(facts):
    require(isinstance(facts, dict) and facts.get("schema_version") == 1, "unsupported schema_version")
    allowed = {
        "schema_version", "overlay_cidr", "interface", "frontend_port", "frontend_name",
        "upstream_address", "upstream_port", "ssh_address", "ssh_port", "ssh_probe",
        "management_url", "client_memory", "frontend_memory", "hosts",
    }
    require(set(facts) == allowed, "unexpected or missing fact keys")
    overlay = ipaddress.ip_network(facts["overlay_cidr"], strict=True)
    require(overlay.version == 4 and overlay.subnet_of(ipaddress.ip_network("100.64.0.0/10"))
            and 16 <= overlay.prefixlen <= 24, "overlay must be a CGNAT IPv4 /16 through /24")
    for prefix in PROTECTED:
        require(not overlay.overlaps(ipaddress.ip_network(prefix)), "overlay overlaps " + prefix)
    iface = facts["interface"]
    require(iface == IFACE and re.fullmatch(r"[a-z][a-z0-9-]{0,14}", iface) is not None,
            "interface must be the dedicated nb-host name")
    require(iface not in FORBIDDEN_IFACES and not iface.startswith("wg"), "interface collides with an existing device")
    require(facts["frontend_port"] == FRONTEND_PORT, "frontend port must stay 8443")
    require(facts["frontend_name"] == GRAFANA, "frontend name must be the Grafana hostname")
    require(facts["upstream_address"] == UPSTREAM_IP and facts["upstream_port"] == UPSTREAM_PORT,
            "upstream must stay the verified Grafana listener 10.250.0.3:443")
    require(facts["ssh_address"] == SSH_ADDR, "SSH target must stay the existing 10.250.0.2 address")
    require(type(facts["ssh_port"]) is int and facts["ssh_port"] in SSH_PORTS,
            "SSH port must be exactly one of 22 or 2222")
    probe = facts["ssh_probe"]
    if probe is not None:
        require(set(probe) == {"address", "accepted_port", "refused_ports", "method", "login"},
                "ssh_probe keys invalid")
        require(probe["method"] == "tcp-connect" and probe["login"] is False, "ssh_probe must be a non-login TCP connect")
        require(probe["address"] == SSH_ADDR and probe["accepted_port"] == facts["ssh_port"],
                "ssh_port contradicts the TCP probe")
        require(isinstance(probe["refused_ports"], list) and facts["ssh_port"] not in probe["refused_ports"],
                "ssh_port was refused by the probe")
        require(all(type(port) is int for port in probe["refused_ports"]), "refused ports must be integers")
    url = facts["management_url"]
    if url is not None:
        require(re.fullmatch(r"https://[a-z0-9.-]+(:443)?", url) is not None, "management_url must be https://hostname")
    require(parse_mib(facts["client_memory"]) >= 32, "client memory cap too small")
    require(parse_mib(facts["frontend_memory"]) >= 16, "frontend memory cap too small")
    hosts = _host_map(facts)
    require(len({hosts[name]["failure_domain"] for name in HOSTS}) == 2, "failure domains must differ")
    for host in hosts.values():
        require(set(host) == {
            "name", "failure_domain", "owned", "public_addresses", "egress_iface", "snat_address",
            "routes", "mem_available_kib", "sudo_nopass", "runtime",
        }, "host keys invalid")
        require(host["egress_iface"] == "wg-socrat", "egress interface is the existing mesh interface")
        require(host["runtime"] in {None, "docker", "host"}, "runtime must be docker, host, or unknown")
        require(type(host["sudo_nopass"]) is bool and type(host["mem_available_kib"]) is int
                and host["mem_available_kib"] > 0, "host privilege or memory fact invalid")
        for address in host["owned"] + host["public_addresses"] + [host["snat_address"]]:
            ipaddress.ip_address(address)
        for route in host["routes"]:
            ipaddress.ip_network(route, strict=False)
    require(ipaddress.ip_address(SSH_ADDR) in {ipaddress.ip_address(item) for item in hosts["socrat-2"]["owned"]},
            "socrat-2 must own 10.250.0.2; that is what makes SSH INPUT on that host")
    require(ipaddress.ip_address(SSH_ADDR) not in {ipaddress.ip_address(item) for item in hosts["socrat-0"]["owned"]},
            "socrat-0 must not own the SSH target")
    require(classify(hosts["socrat-2"], SSH_ADDR) == "input", "socrat-2 delivery must be INPUT")
    require(classify(hosts["socrat-0"], SSH_ADDR) == "forward", "socrat-0 delivery must be FORWARD")
    routers = [name for name in HOSTS if classify(hosts[name], SSH_ADDR) == "forward"]
    require(routers == ["socrat-0"], "SSH has one routing peer; socrat-2 cannot be a second router for its own address")
    return facts


def blockers_for(facts):
    facts = validate(facts)
    hosts = _host_map(facts)
    blockers = []
    notes = []
    if facts["management_url"] is None:
        blockers.append("management_url_unpublished")
    for name in HOSTS:
        host = hosts[name]
        if host["sudo_nopass"] is not True:
            blockers.append(name + ": noninteractive sudo unavailable")
        if host["runtime"] is None:
            blockers.append(name + ": container runtime not proven (docker info failed on socrat-0)")
    vps = hosts["socrat-2"]
    avail = vps["mem_available_kib"] / 1024
    need = parse_mib(facts["client_memory"]) + parse_mib(facts["frontend_memory"])
    if vps["mem_available_kib"] == VPS_OBSERVED_KIB:
        notes.append("socrat-2 MemAvailable is 446 MiB (455948 KiB)")
    else:
        notes.append("socrat-2 MemAvailable is %.0f MiB (%d KiB)" % (avail, vps["mem_available_kib"]))
    notes.append("client cap %s plus frontend cap %s; %d MiB headroom required on the VPS"
                 % (facts["client_memory"], facts["frontend_memory"], HEADROOM_MIB))
    if need > 128 or avail < need + HEADROOM_MIB:
        blockers.append("socrat-2: memory caps do not fit inside 446 MiB with %d MiB headroom" % HEADROOM_MIB)
    notes.append("SSH %s:%d is INPUT on socrat-2 and FORWARD only on socrat-0; route HA is false"
                 % (SSH_ADDR, facts["ssh_port"]))
    notes.append("Grafana listeners are separate overlay destinations on TCP %d, upstream %s:%d"
                 % (FRONTEND_PORT, UPSTREAM_IP, UPSTREAM_PORT))
    return blockers, notes


def bind_allowed(address, overlay_cidr):
    try:
        addr = ipaddress.ip_address(address)
        overlay = ipaddress.ip_network(overlay_cidr, strict=True)
    except (TypeError, ValueError):
        return False
    if addr.is_unspecified or addr.is_loopback or addr.is_multicast or addr.is_link_local:
        return False
    if addr not in overlay:
        return False
    for prefix in PROTECTED:
        if addr in ipaddress.ip_network(prefix):
            return False
    return True


def roles(facts):
    facts = validate(facts)
    hosts = _host_map(facts)
    return {
        name: {
            "ssh_delivery": classify(hosts[name], facts["ssh_address"]),
            "ssh_routing_peer": classify(hosts[name], facts["ssh_address"]) == "forward",
            "grafana": "overlay-input",
            "disable_server_routes": name == "socrat-2",
        }
        for name in HOSTS
    }


def _nft(host, facts):
    iface = facts["interface"]
    port = facts["frontend_port"]
    lines = [
        "add table ip %s" % TABLE,
        "add chain ip %s input { type filter hook input priority -50; policy accept; }" % TABLE,
        "add chain ip %s forward { type filter hook forward priority -50; policy accept; }" % TABLE,
        "add chain ip %s postrouting { type nat hook postrouting priority 90; policy accept; }" % TABLE,
        'add rule ip %s input iifname "%s" ip daddr %s tcp dport %d ct state new,established accept'
        % (TABLE, iface, OVERLAY_TOKEN, port),
        'add rule ip %s input iifname "%s" ct state established,related accept' % (TABLE, iface),
        'add rule ip %s input iifname "%s" drop' % (TABLE, iface),
        'add rule ip %s input iifname != "%s" tcp dport %d drop' % (TABLE, iface, port),
    ]
    if host["name"] == "socrat-0":
        lines.append(
            'add rule ip %s forward iifname "%s" oifname "%s" ip daddr %s tcp dport %d ct state new,established accept'
            % (TABLE, iface, host["egress_iface"], facts["ssh_address"], facts["ssh_port"]))
        lines.append('add rule ip %s forward oifname "%s" ct state established,related accept' % (TABLE, iface))
        lines.append(
            'add rule ip %s postrouting iifname "%s" oifname "%s" ip daddr %s tcp dport %d snat to %s'
            % (TABLE, iface, host["egress_iface"], facts["ssh_address"], facts["ssh_port"], host["snat_address"]))
    lines.append('add rule ip %s forward iifname "%s" drop' % (TABLE, iface))
    body = "\n".join(lines) + "\n"
    return """#!/bin/sh
set -eu
if grep -F -q '%s' "$0"; then
    echo 'refusing to load %s before the overlay address is enrolled' >&2
    exit 1
fi
nft=$(command -v nft) || { echo 'nft is required' >&2; exit 1; }
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
cat >"$tmp" <<'NFT'
%sNFT
"$nft" -c -f "$tmp"
"$nft" -f "$tmp"
""" % (OVERLAY_TOKEN, TABLE, body)


def assign_overlay(script, address, overlay_cidr):
    require(bind_allowed(address, overlay_cidr), "overlay address is not a dedicated NetBird address")
    require(script.count(OVERLAY_TOKEN) >= 1, "firewall script lost its overlay token")
    concrete = str(ipaddress.ip_address(address))
    return script.replace(OVERLAY_TOKEN, concrete)


def firewall_rules(script, chain):
    rules = []
    for line in script.splitlines():
        if line.startswith("add rule ip %s %s " % (TABLE, chain)):
            rules.append(line)
    return rules


def _up_script(facts):
    forbidden = "|".join(sorted(FORBIDDEN_IFACES | {"wg-*"}))
    return """#!/bin/sh
set -eu
IFACE=%s
case "$IFACE" in
    %s) echo 'refusing existing interface' >&2; exit 1;;
esac
if [ ! -f /etc/netbird-host-router/setup.key ]; then
    echo 'setup key file is missing' >&2
    exit 1
fi
mode=$(stat -c %%a /etc/netbird-host-router/setup.key)
case "$mode" in
    400|600) ;;
    *) echo 'setup key file mode must be 0400 or 0600' >&2; exit 1;;
esac
url=$(sed -n 's/^NB_MANAGEMENT_URL=//p' /etc/netbird-host-router/client.env)
case "$url" in
    ""|%s|*[[:space:]]*|*\"*|*\'*|*[;\\$`]*) echo 'management URL is not enrolled' >&2; exit 1;;
esac
if [ -x /usr/local/bin/netbird ]; then
    NB=/usr/local/bin/netbird
else
    NB=$(command -v netbird)
fi
"$NB" service run &
pid=$!
trap 'kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true' EXIT INT TERM
i=0
while [ "$i" -lt 30 ]; do
    if "$NB" status --check live >/dev/null 2>&1; then
        break
    fi
    i=$((i + 1))
    sleep 1
done
set -- \
    --management-url "$url" \
    --setup-key-file /etc/netbird-host-router/setup.key \
    --interface-name "$IFACE" \
    --allow-server-ssh=false \
    --enable-ssh-root=false \
    --enable-ssh-sftp=false \
    --enable-ssh-local-port-forwarding=false \
    --enable-ssh-remote-port-forwarding=false \
    --disable-ipv6=true
if [ "${NB_DISABLE_SERVER_ROUTES:-}" = true ]; then
    set -- "$@" --disable-server-routes=true
fi
"$NB" up "$@"
wait "$pid"
""" % (facts["interface"], forbidden, URL_TOKEN)


def _frontend_source(facts):
    return '''# Generated listener. Binds only to an enrolled NetBird overlay address.
import os
import select
import socket
import ssl
import sys

NAME = %r
PORT = %d
UPSTREAM_IP = %r
UPSTREAM_PORT = %d
OVERLAY = %r
CERT = "/etc/netbird-host-router/frontend.crt"
KEY = "/etc/netbird-host-router/frontend.key"
PROTECTED = %r


def bind_allowed(address):
    import ipaddress
    try:
        addr = ipaddress.ip_address(address)
        overlay = ipaddress.ip_network(OVERLAY, strict=True)
    except (TypeError, ValueError):
        return False
    if addr.is_unspecified or addr.is_loopback or addr.is_multicast or addr.is_link_local:
        return False
    if addr not in overlay:
        return False
    return not any(addr in ipaddress.ip_network(prefix) for prefix in PROTECTED)


def header_host(payload):
    if not isinstance(payload, (bytes, bytearray)):
        return None
    text = bytes(payload).split(b"\\r\\n\\r\\n", 1)[0].decode("ascii", "replace")
    hosts = []
    for line in text.split("\\r\\n")[1:]:
        if line.lower().startswith("host:"):
            hosts.append(line.split(":", 1)[1].strip().lower())
    if len(hosts) != 1 or not hosts[0]:
        return None
    value = hosts[0]
    if value.startswith("[") or "/" in value or " " in value:
        return None
    if value.count(":") > 1:
        return None
    host = value.rsplit(":", 1)[0] if ":" in value else value
    if host != NAME or not host:
        return None
    return host


def admit(sni, host_header):
    if not isinstance(sni, str) or sni.lower() != NAME:
        return False
    return header_host(b"GET / HTTP/1.1\\r\\nHost: " + host_header.encode("ascii", "replace") + b"\\r\\n\\r\\n") == NAME


def sni_callback(sock, server_name, _ctx):
    if not server_name or server_name.lower() != NAME:
        return ssl.ALERT_DESCRIPTION_UNRECOGNIZED_NAME
    sock.nb_sni = server_name.lower()
    return None


def upstream_context():
    ctx = ssl.create_default_context()
    if ctx.verify_mode != ssl.CERT_REQUIRED or not ctx.check_hostname:
        raise RuntimeError("upstream TLS verification is not the default")
    return ctx


def read_headers(tls):
    data = b""
    while b"\\r\\n\\r\\n" not in data:
        chunk = tls.recv(1024)
        if not chunk:
            break
        data += chunk
        if len(data) > 8192:
            return None
    if b"\\r\\n\\r\\n" not in data:
        return None
    return data


def splice(left, right):
    sockets = [left, right]
    while sockets:
        readable, _, _ = select.select(sockets, [], [], 60)
        if not readable:
            break
        for source in readable:
            dest = right if source is left else left
            chunk = source.recv(16384)
            if not chunk:
                return
            dest.sendall(chunk)


def handle(conn, ctx):
    tls = None
    upstream = None
    try:
        tls = ctx.wrap_socket(conn, server_side=True)
        if getattr(tls, "nb_sni", None) != NAME:
            return
        payload = read_headers(tls)
        if payload is None or header_host(payload) != NAME:
            tls.sendall(b"HTTP/1.1 421 Misdirected Request\\r\\nContent-Length: 0\\r\\nConnection: close\\r\\n\\r\\n")
            return
        raw = socket.create_connection((UPSTREAM_IP, UPSTREAM_PORT), timeout=10)
        upstream = upstream_context().wrap_socket(raw, server_hostname=NAME)
        upstream.sendall(payload)
        splice(tls, upstream)
    finally:
        for item in (upstream, tls, conn):
            if item is not None:
                try:
                    item.close()
                except OSError:
                    pass


def serve(address):
    if not bind_allowed(address):
        raise SystemExit("refusing frontend bind")
    if not (os.path.isfile(CERT) and os.path.isfile(KEY)):
        raise SystemExit("frontend certificate is missing")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(CERT, KEY)
    ctx.sni_callback = sni_callback
    ctx.set_alpn_protocols(["http/1.1"])
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((address, PORT))
    sock.listen(16)
    while True:
        conn, _addr = sock.accept()
        handle(conn, ctx)


if __name__ == "__main__":
    serve(os.environ.get("NB_OVERLAY_IP", ""))
''' % (facts["frontend_name"], facts["frontend_port"], facts["upstream_address"],
       facts["upstream_port"], facts["overlay_cidr"], PROTECTED)


def _unit(host, facts, image, runtime):
    disable = "true" if host["name"] == "socrat-2" else "false"
    common = [
        "[Unit]",
        "Description=NetBird host peer for %s" % host["name"],
        "After=network-online.target",
        "[Service]",
        "Type=simple",
        "Environment=NB_DISABLE_SERVER_ROUTES=%s" % disable,
        "Restart=on-failure",
        "RestartSec=5",
        "MemoryMax=%s" % facts["client_memory"].upper(),
    ]
    if runtime == "docker":
        common.append("NoNewPrivileges=true")
        common.append(
            "ExecStart=/usr/bin/docker run --rm --name netbird-host-router "
            "--cap-drop=ALL --cap-add=NET_ADMIN --cap-add=NET_RAW --cap-add=BPF "
            "--security-opt=no-new-privileges:true --memory=%s --memory-swap=%s --pids-limit=64 "
            "--read-only --tmpfs=/tmp:rw,noexec,nosuid,size=16m --network=host --device=/dev/net/tun "
            "-e NB_LOG_FILE=console -e NB_DISABLE_SERVER_ROUTES=%s "
            "-v /var/lib/netbird-host-router:/var/lib/netbird "
            "-v /etc/netbird-host-router/setup.key:/etc/netbird-host-router/setup.key:ro "
            "-v /etc/netbird-host-router/client.env:/etc/netbird-host-router/client.env:ro "
            "-v /usr/local/libexec/netbird-host-router/netbird-up.sh:/netbird-up.sh:ro "
            "--entrypoint=/bin/sh %s /netbird-up.sh"
            % (facts["client_memory"], facts["client_memory"], disable, image))
    else:
        common.extend([
            "NoNewPrivileges=false",
            "CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_RAW CAP_BPF",
            "AmbientCapabilities=CAP_NET_ADMIN CAP_NET_RAW CAP_BPF",
            "ExecStart=/usr/local/libexec/netbird-host-router/netbird-up.sh",
        ])
    common.append("[Install]\nWantedBy=multi-user.target\n")
    return "\n".join(common)


def _frontend_unit(facts):
    return """[Unit]
Description=Grafana-only NetBird frontend
After=netbird-host-router.service
[Service]
Type=simple
EnvironmentFile=/run/netbird-host-router/overlay.env
ExecStart=/usr/bin/python3 /usr/local/libexec/netbird-host-router/grafana-frontend.py
NoNewPrivileges=true
CapabilityBoundingSet=
PrivateTmp=true
ProtectSystem=strict
ReadOnlyPaths=/etc/netbird-host-router
MemoryMax=%s
RestrictAddressFamilies=AF_INET
[Install]
WantedBy=multi-user.target
""" % facts["frontend_memory"].upper()


def _playbook(host):
    tasks = """---
- name: Install the reviewed NetBird host-router files for %s
  hosts: "%s"
  become: true
  gather_facts: false
  vars:
    netbird_host_router_apply: false
  tasks:
    - name: Stay render-only until the reviewed variable is set
      ansible.builtin.assert:
        that:
          - netbird_host_router_apply | bool
          - netbird_host_router_interface | default('nb-host') == 'nb-host'
    - name: Install owned unit, firewall script, and frontend
      ansible.builtin.copy:
        src: "{{ item.src }}"
        dest: "{{ item.dest }}"
        mode: "{{ item.mode }}"
      loop:
        - {src: netbird-host-router.service, dest: /etc/systemd/system/netbird-host-router.service, mode: "0644"}
        - {src: netbird-grafana-frontend.service, dest: /etc/systemd/system/netbird-grafana-frontend.service, mode: "0644"}
        - {src: table.nft.sh, dest: /usr/local/libexec/netbird-host-router/table.nft.sh, mode: "0755"}
        - {src: netbird-up.sh, dest: /usr/local/libexec/netbird-host-router/netbird-up.sh, mode: "0755"}
        - {src: grafana-frontend.py, dest: /usr/local/libexec/netbird-host-router/grafana-frontend.py, mode: "0644"}
""" % (host["name"], host["name"])
    if host["name"] == "socrat-0":
        tasks += """        - {src: 99-netbird-host-router.conf, dest: /etc/sysctl.d/99-netbird-host-router.conf, mode: "0644"}
"""
    tasks += """    - name: Load only the owned firewall table
      ansible.builtin.command: /usr/local/libexec/netbird-host-router/table.nft.sh
"""
    return tasks


def _client_env(facts):
    url = facts["management_url"] or URL_TOKEN
    return "NB_MANAGEMENT_URL=%s\n" % url



def assert_clean(filename, content):
    markers = EXECUTABLE_MARKERS
    if filename == "grafana-frontend.py":
        markers = (
            "/etc/wireguard", "wg-quick", "wg set", "wg addconf", "authorized_keys",
            "sshd_config", "--privileged", "--allow-server-ssh=true", "docker.sock", "/etc/ssh",
            "ip route", "ip rule",
        )
    for marker in markers:
        require(marker not in content, "%s contains forbidden marker %s" % (filename, marker))


def render_host(host, facts, image):
    runtime = host["runtime"] or "docker"
    files = {
        "netbird-host-router.service": _unit(host, facts, image, runtime),
        "netbird-grafana-frontend.service": _frontend_unit(facts),
        "table.nft.sh": _nft(host, facts),
        "netbird-up.sh": _up_script(facts),
        "grafana-frontend.py": _frontend_source(facts),
        "client.env": _client_env(facts),
        "install.yml": _playbook(host),
    }
    if host["name"] == "socrat-0":
        files["99-netbird-host-router.conf"] = "net.ipv4.ip_forward=1\n"
    for name, content in files.items():
        assert_clean(name, content)
        require("--allow-server-ssh=false" in files["netbird-up.sh"], "NetBird SSH must be off")
    if host["name"] == "socrat-2":
        require("10.250.0.2" not in files["table.nft.sh"], "socrat-2 firewall must not target its own SSH address")
        require("ip_forward" not in "\n".join(files.values()), "socrat-2 plan must not enable forwarding")
        require("NB_DISABLE_SERVER_ROUTES=true" in files["netbird-host-router.service"],
                "socrat-2 must disable NetBird server routes")
    else:
        require("NB_DISABLE_SERVER_ROUTES=false" in files["netbird-host-router.service"],
                "socrat-0 keeps server routes so the single SSH forward can be advertised")
        forward = firewall_rules(files["table.nft.sh"], "forward")
        require(any(facts["ssh_address"] in line and "dport %d" % facts["ssh_port"] in line and line.endswith("accept")
                    for line in forward), "socrat-0 forward rule missing")
        require(not any("dport %d" % facts["ssh_port"] in line for line in firewall_rules(files["table.nft.sh"], "input")),
                "socrat-0 must not accept SSH on INPUT")
    return files


def build(facts):
    facts = validate(facts)
    image = client_image()
    blockers, notes = blockers_for(facts)
    hosts = _host_map(facts)
    rendered = {name: render_host(hosts[name], facts, image) for name in HOSTS}
    digests = {
        name: {filename: hashlib.sha256(content.encode()).hexdigest() for filename, content in files.items()}
        for name, files in rendered.items()
    }
    plan = {
        "schema_version": 1,
        "apply_allowed": not blockers,
        "blockers": blockers,
        "notes": notes,
        "image": image,
        "interface": facts["interface"],
        "overlay_cidr": facts["overlay_cidr"],
        "ssh": {
            "address": facts["ssh_address"],
            "port": facts["ssh_port"],
            "routers": ["socrat-0"],
            "destination": "socrat-2",
            "destination_delivery": "input",
            "ha": False,
        },
        "grafana": {
            "mode": "separate-overlay-destinations",
            "port": facts["frontend_port"],
            "name": facts["frontend_name"],
            "upstream": "%s:%d" % (facts["upstream_address"], facts["upstream_port"]),
            "shared_vip_published": False,
            "policies": ["overlay-peer:socrat-0", "overlay-peer:socrat-2"],
        },
        "roles": roles(facts),
        "digests": digests,
    }
    return plan, rendered


def _outside_worktree(path):
    resolved = Path(path).resolve()
    return not resolved.is_relative_to(ROOT.resolve())


def write_plan(out, plan, rendered):
    require(_outside_worktree(out), "--out must be outside the Git worktree")
    target = Path(out)
    require(not target.exists(), "--out must be a new directory")
    target.mkdir(parents=True)
    (target / "plan.json").write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    for name, files in rendered.items():
        host_dir = target / name
        host_dir.mkdir()
        for filename, content in files.items():
            path = host_dir / filename
            path.write_text(content)
            if filename.endswith(".sh") or filename.endswith(".py"):
                path.chmod(0o755 if filename.endswith(".sh") else 0o644)


def _safe_rel(rel):
    path = Path(rel)
    require(not path.is_absolute() and ".." not in path.parts, "owned path escapes")
    require("wireguard" not in path.parts and "ssh" not in path.parts, "owned path collides with existing config")
    return path


OWNED = {
    "etc/systemd/system/netbird-host-router.service": ("netbird-host-router.service", 0o644),
    "etc/systemd/system/netbird-grafana-frontend.service": ("netbird-grafana-frontend.service", 0o644),
    "etc/netbird-host-router/client.env": ("client.env", 0o644),
    "usr/local/libexec/netbird-host-router/table.nft.sh": ("table.nft.sh", 0o755),
    "usr/local/libexec/netbird-host-router/netbird-up.sh": ("netbird-up.sh", 0o755),
    "usr/local/libexec/netbird-host-router/grafana-frontend.py": ("grafana-frontend.py", 0o644),
    "usr/local/libexec/netbird-host-router/install.yml": ("install.yml", 0o644),
}


def apply_tree(plan_dir, root, host, overlay_ip=None):
    plan_dir = Path(plan_dir)
    root = Path(root)
    plan = json.loads((plan_dir / "plan.json").read_text())
    require(plan.get("apply_allowed") is True, "apply refused: blockers remain")
    require(host in HOSTS, "unknown host")
    files = {}
    for filename, digest in plan["digests"][host].items():
        content = (plan_dir / host / filename).read_text()
        require(hashlib.sha256(content.encode()).hexdigest() == digest, "plan file digest mismatch: " + filename)
        assert_clean(filename, content)
        files[filename] = content
    if overlay_ip is not None:
        files["table.nft.sh"] = assign_overlay(files["table.nft.sh"], overlay_ip, plan["overlay_cidr"])
    root.mkdir(parents=True, exist_ok=True)
    mapping = dict(OWNED)
    if host == "socrat-0":
        mapping["etc/sysctl.d/99-netbird-host-router.conf"] = ("99-netbird-host-router.conf", 0o644)
    written = []
    for rel, (filename, mode) in mapping.items():
        rel_path = _safe_rel(rel)
        dest = (root / rel_path).resolve()
        require(dest.is_relative_to(root.resolve()), "destination escapes --root")
        require(not dest.is_symlink(), "refusing symlink destination")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(files[filename])
        os.chmod(dest, mode)
        written.append(str(rel_path))
    state = root / "var/lib/netbird-host-router"
    state.mkdir(parents=True, exist_ok=True)
    os.chmod(state, 0o700)
    return written


def main(argv):
    parser = argparse.ArgumentParser(description="Plan NetBird peers on existing socrat-0 and socrat-2 hosts")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("check", "plan"):
        command = sub.add_parser(name)
        command.add_argument("--facts")
        if name == "plan":
            command.add_argument("--out", required=True)
    apply_cmd = sub.add_parser("apply")
    apply_cmd.add_argument("--plan", required=True)
    apply_cmd.add_argument("--root", required=True)
    apply_cmd.add_argument("--host", required=True, choices=list(HOSTS))
    apply_cmd.add_argument("--overlay-ip")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "apply":
            written = apply_tree(args.plan, args.root, args.host, args.overlay_ip)
            print("\n".join(written))
            return 0
        facts = default_facts() if not args.facts else json.loads(Path(args.facts).read_text())
        plan, rendered = build(facts)
        if args.cmd == "check":
            print(json.dumps({"apply_allowed": plan["apply_allowed"], "blockers": plan["blockers"]}, indent=2))
            return 0 if plan["apply_allowed"] else 2
        write_plan(args.out, plan, rendered)
        print(args.out)
        return 0 if plan["apply_allowed"] else 2
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
