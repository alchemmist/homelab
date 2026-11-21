"""Bounded real client-leaf renewal and named mirror exercise; no SDK claims.

Uses the native Certificate Issuing status transition used by cmctl v2.3.0.
Does not delete Secrets, change certificate spec, expose private keys, grant
Deployment patch rights, or force restart any application.
"""

import argparse
import base64
import hashlib
import importlib.util
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "rotation_bootstrap", ROOT / "scripts/otel-production-bootstrap.py"
)
BOOTSTRAP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BOOTSTRAP)
NS = "cattle-monitoring-system"
APPLICATIONS = ("litellm", "vllm", "open-webui")


def leaf_name(application):
    if application not in APPLICATIONS:
        msg = "Only explicitly allowed application client leaves may be renewed"
        raise ValueError(msg)
    return "otel-app-tls-" + application


def renewal_conditions(certificate, application="litellm"):
    if (
        certificate["metadata"]["name"] != leaf_name(application)
        or certificate["metadata"]["namespace"] != NS
    ):
        msg = "Only the selected dedicated application client leaf is in this exercise"
        raise ValueError(msg)
    conditions = certificate.get("status", {}).get("conditions", [])
    if not any(c["type"] == "Ready" and c["status"] == "True" for c in conditions):
        msg = "Certificate is not ready before exercise"
        raise ValueError(msg)
    if any(c["type"] == "Issuing" and c["status"] == "True" for c in conditions):
        msg = "Existing issuance must complete; never overlap requests"
        raise ValueError(msg)
    result = [c for c in conditions if c["type"] != "Issuing"]
    result.append(
        {
            "type": "Issuing",
            "status": "True",
            "observedGeneration": certificate["metadata"]["generation"],
            "lastTransitionTime": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "reason": "ManuallyTriggered",
            "message": "Certificate re-issuance manually triggered",
        }
    )
    return result


def public_certificate_identity(kube, namespace, application="litellm"):
    # kubectl emits only the public certificate field, never tls.key or the Secret.
    template = '{{printf "{\\"certificatePemBase64\\":%q}" (index .data "tls.crt")}}'
    selected = kube(
        "-n", namespace, "get", "secret", leaf_name(application), "-o", "go-template=" + template
    )
    data = base64.b64decode(selected["certificatePemBase64"], validate=True)
    if b"-----BEGIN CERTIFICATE-----" not in data or b"PRIVATE KEY" in data:
        msg = "Expected only public certificate PEM"
        raise ValueError(msg)
    public_key = subprocess.run(
        ["openssl", "x509", "-pubkey", "-noout"],
        input=data,
        capture_output=True,
        check=True,
        timeout=10,
    ).stdout
    if b"PUBLIC KEY" not in public_key or b"PRIVATE KEY" in public_key:
        msg = "Expected public certificate key only"
        raise ValueError(msg)
    return {
        "certificateSHA256": hashlib.sha256(data).hexdigest(),
        "publicKeySHA256": hashlib.sha256(public_key).hexdigest(),
    }


def public_certificate_hash(kube, namespace, application="litellm"):
    return public_certificate_identity(kube, namespace, application)["certificateSHA256"]


def run(output, application="litellm"):
    leaf_name(application)
    os.umask(0o077)
    controller = Path.home() / "Library/Application Support/homelab/otel-controller"
    if not output.resolve().is_relative_to(controller.resolve()):
        msg = "Use protected durable controller evidence"
        raise ValueError(msg)
    output.mkdir(mode=0o700)
    kube = BOOTSTRAP.kube
    before = kube("-n", NS, "get", "certificate", leaf_name(application), "-o", "json")
    conditions = renewal_conditions(before, application)
    identity_before = public_certificate_identity(kube, NS, application)
    source_before = identity_before["certificateSHA256"]
    target_before = public_certificate_hash(kube, "llm", application)
    if source_before != target_before:
        msg = "Existing client-leaf mirror has not converged"
        raise ValueError(msg)
    (output / "certificate-before.json").write_text(json.dumps(before, indent=2) + "\n")
    progress = {
        "success": False,
        "application": application,
        "phase": "trigger-native-renewal",
        "originalRevision": before["status"]["revision"],
        "originalCertificateSHA256": source_before,
        "originalPublicKeySHA256": identity_before["publicKeySHA256"],
        "secretsDeleted": False,
        "privateKeysSaved": False,
        "applicationDeploymentsChanged": False,
        "sdkExporterReloadVerified": False,
        "nativeReference": "https://github.com/cert-manager/cmctl/blob/v2.3.0/pkg/renew/renew.go",
    }

    def record():
        (output / "progress.json").write_text(json.dumps(progress, indent=2) + "\n")

    record()
    kube(
        "-n",
        NS,
        "patch",
        "certificate",
        leaf_name(application),
        "--subresource=status",
        "--type=json",
        "-p",
        json.dumps(
            [
                {
                    "op": "test",
                    "path": "/metadata/resourceVersion",
                    "value": before["metadata"]["resourceVersion"],
                },
                {"op": "replace", "path": "/status/conditions", "value": conditions},
            ]
        ),
        "-o",
        "json",
    )
    progress["phase"] = "await-new-native-revision"
    record()
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        after = kube("-n", NS, "get", "certificate", leaf_name(application), "-o", "json")
        status = after.get("status", {})
        if (
            status.get("revision", 0) > before["status"]["revision"]
            and any(
                c["type"] == "Ready" and c["status"] == "True" for c in status.get("conditions", [])
            )
            and not any(
                c["type"] == "Issuing" and c["status"] == "True"
                for c in status.get("conditions", [])
            )
        ):
            break
        time.sleep(2)
    else:
        msg = "Native renewal deadline exceeded; preserve progress"
        raise ValueError(msg)
    if after["spec"] != before["spec"]:
        msg = "Certificate spec changed during exercise"
        raise ValueError(msg)
    identity_after = public_certificate_identity(kube, NS, application)
    source_after = identity_after["certificateSHA256"]
    if (
        source_after == source_before
        or identity_after["publicKeySHA256"] == identity_before["publicKeySHA256"]
    ):
        msg = "New native revision must rotate both certificate and keypair"
        raise ValueError(msg)
    progress.update(
        renewedPublicKeySHA256=identity_after["publicKeySHA256"], clientKeypairRotationVerified=True
    )
    progress.update(
        phase="await-named-mirror-job",
        renewedRevision=after["status"]["revision"],
        renewedCertificateSHA256=source_after,
    )
    record()
    job_name = "otel-app-leaf-rotation-" + datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    kube(
        "-n",
        NS,
        "create",
        "job",
        "--from=cronjob/otel-application-credentials",
        job_name,
        "-o",
        "json",
    )
    progress["mirrorJob"] = job_name
    record()
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        job = kube("-n", NS, "get", "job", job_name, "-o", "json")
        if job.get("status", {}).get("failed"):
            (output / "failed-job-status.json").write_text(json.dumps(job["status"]))
            msg = "Bounded mirror job failed; do not retry silently"
            raise ValueError(msg)
        if job.get("status", {}).get("succeeded"):
            break
        time.sleep(2)
    else:
        msg = "Mirror deadline exceeded; preserve native issuance"
        raise ValueError(msg)
    log = kube("-n", NS, "logs", "job/" + job_name)
    (output / "mirror-result.json").write_text(json.dumps(log, indent=2) + "\n")
    if (
        application not in log["nativeClientMtlsVerified"]
        or public_certificate_hash(kube, "llm", application) != source_after
    ):
        msg = "New client mTLS or mirror equality was not proven"
        raise ValueError(msg)
    progress.update(
        success=True,
        phase="native-leaf-renewal-and-mirror-verified",
        certificateSpecChanged=False,
        newLeafNativeClientMtlsVerified=True,
        targetMirrorCertificateEqualityVerified=True,
        sdkExporterReloadVerified=False,
        oldStillValidLeafRevocationClaimed=False,
    )
    record()
    (output / "result.json").write_text(json.dumps(progress, indent=2) + "\n")
    print(json.dumps(progress))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--application", choices=APPLICATIONS, default="litellm")
    args = parser.parse_args()
    run(args.output, args.application)
