#!/usr/bin/env python3
"""Exercise controller dependency interfaces using only in-memory fixtures."""

import time

import jwt
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from kubernetes import client


def check() -> None:
    """Sign an app assertion and serialize a ConfigMap without credentials or a cluster."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    now = int(time.time())
    claims = {"iat": now - 30, "exp": now + 540, "iss": "fixture"}
    assertion = jwt.encode(claims, pem, algorithm="RS256")
    if jwt.decode(assertion, key.public_key(), algorithms=["RS256"]) != claims:
        message = "RS256 assertion did not round trip"
        raise ValueError(message)

    config_map = client.V1ConfigMap(
        metadata=client.V1ObjectMeta(name="fixture"), data={"proposal.json": "{}"}
    )
    with client.ApiClient(client.Configuration()) as api:
        payload = api.sanitize_for_serialization(config_map)
    if payload != {"metadata": {"name": "fixture"}, "data": {"proposal.json": "{}"}}:
        message = "ConfigMap serialization changed"
        raise ValueError(message)
    # Prepare the same JSON/auth request shape as the controller; never send it.
    request = requests.Request(
        "POST",
        "https://fixture.invalid/",
        headers={"Authorization": f"Bearer {assertion}"},
        json={"repositories": ["fixture"]},
    ).prepare()
    if request.headers["Content-Type"] != "application/json":
        message = "Session JSON encoding unavailable"
        raise ValueError(message)


if __name__ == "__main__":
    check()
