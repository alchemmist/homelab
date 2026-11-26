"""Run inside a permitted rehearsal probe Pod; never fall back to public DNS."""

import argparse
import http.client
import ipaddress
import socket
import ssl

BLOG_HOSTS = ("alchemmist.xyz", "www.alchemmist.xyz")
TITLE = b"<title>Personal blog of Anton Grishin</title>"


TITLES = {
    **dict.fromkeys(BLOG_HOSTS, TITLE),
    "cats.alchemmist.xyz": b"<title>Funny cats</title>",
    "fq.alchemmist.xyz": b"<title>FQ</title>",
}


def service_ip(value: str) -> str:
    """Accept only an IPv4 address in the Socrat Service CIDR."""
    address = ipaddress.ip_address(value)
    if address not in ipaddress.ip_network("10.43.0.0/16"):
        raise ValueError("Expected the private Moscow Service ClusterIP")
    return str(address)


def probe(host: str, address: str) -> bool:
    """Connect to the Service IP; verify public hostname, TLS chain and blog content."""
    context = ssl.create_default_context()
    with socket.create_connection((service_ip(address), 443), timeout=5) as raw:
        with context.wrap_socket(raw, server_hostname=host) as secured:
            secured.sendall(
                f"GET / HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode(
                    "ascii"
                )
            )
            with http.client.HTTPResponse(secured) as response:
                response.begin()
                return response.status == http.HTTPStatus.OK and TITLES[
                    host
                ] in response.read(256 * 1024)


def main() -> int:
    """Return failure for either hostname without logging response bodies or secrets."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service_ip", type=service_ip)
    parser.add_argument(
        "--all-sites",
        action="store_true",
        help="check every reviewed private web canary",
    )
    args = parser.parse_args()
    ok = True
    for host in TITLES if args.all_sites else BLOG_HOSTS:
        try:
            passed = probe(host, args.service_ip)
        except (OSError, http.client.HTTPException) as error:
            print(f"{host}: failed ({type(error).__name__})")
            ok = False
        else:
            print(f"{host}: {'passed' if passed else 'wrong status or content'}")
            ok = ok and passed
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
