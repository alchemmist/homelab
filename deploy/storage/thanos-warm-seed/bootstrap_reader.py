"""Provision one new, bucket-scoped Store identity. Never rotate an existing key."""

import json
import secrets
import sys

from start import BASE, RES, SEC, create, kube

NAME = "thanos-warm-store-reader"
ROOT = "thanos-warm-root"
RUST = "rustfs/rustfs:1.0.4@sha256:ed9210d6411d77ffceb70d94b964a3cb7d225983368bc25bebe01e995293dcc2"
RELEASE = "RELEASE.2025-08-13T08-35-41Z"
SHA = "01f866e9c5f9b87c2b09116fa5d7c06695b106242d829a8bb32990c00312e891"
POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
            "Resource": ["arn:aws:s3:::thanos-workshop"],
        },
        {
            "Effect": "Allow",
            "Action": ["s3:GetObject"],
            "Resource": ["arn:aws:s3:::thanos-workshop/*"],
        },
    ],
}


def main() -> None:
    fixture = sys.argv[1:] == ["--run", "--synthetic-hour"]
    role = (
        sys.argv[2]
        if len(sys.argv) == 3
        and sys.argv[1] == "--run"
        and sys.argv[2] in ("shipper", "compactor", "tier-marker")
        else None
    )
    assert role or fixture or sys.argv[1:] == ["--run"]
    name = "thanos-hour-fixture-reader" if fixture else NAME
    if role:
        name = "thanos-warm-" + role
    bucket = "thanos-hour-fixture" if fixture else "thanos-workshop"
    access = "store" + secrets.token_hex(10)
    secret = secrets.token_hex(32)
    cfg = {
        "type": "S3",
        "config": {
            "bucket": bucket,
            "endpoint": "thanos-warm-api:9000",
            "access_key": access,
            "secret_key": secret,
            "insecure": False,
            "bucket_lookup_type": "path",
            "http_config": {"tls_config": {"ca_file": "/trust/ca.crt"}},
        },
    }
    # A failed bootstrap must be inspected, not automatically retried against an existing user.
    create(
        "Secret",
        {
            "immutable": True,
            "stringData": {
                "access": access,
                "secret": secret,
                "objstore.yml": json.dumps(cfg),
            },
        },
        name,
    )
    trust = {"name": "trust", "mountPath": "/trust", "readOnly": True}
    tmp = {"name": "tmp", "mountPath": "/tmp"}
    base = {"image": RUST, "resources": RES, "securityContext": SEC}
    fetch = {
        "name": "fetch",
        **base,
        "volumeMounts": [tmp],
        "command": [
            "sh",
            "-ec",
            f'curl -fsSL --retry 2 --max-time 90 -o /tmp/mc https://github.com/minio/mc/releases/download/{RELEASE}/mc.linux-amd64.{RELEASE}; echo "{SHA}  /tmp/mc" | sha256sum -c -; chmod 0500 /tmp/mc',
        ],
    }
    script = """set -eu
umask 077
export HOME=/tmp SSL_CERT_FILE=/trust/ca.crt MC_CONFIG_DIR=/tmp/config
trap 'rm -rf /tmp/config' EXIT
/tmp/mc alias set warm https://thanos-warm-api:9000 "$ADMIN_A" "$ADMIN_S" >/dev/null
printf '%s' "$POLICY" >/tmp/read.json
/tmp/mc admin policy create warm thanos-workshop-read /tmp/read.json >/dev/null
/tmp/mc admin user add warm "$READER_A" "$READER_S" >/dev/null
/tmp/mc admin policy attach warm thanos-workshop-read --user "$READER_A" >/dev/null
echo 'workshop read-only policy attached'
"""
    env = [
        {"name": prefix + "_" + s, "valueFrom": {"secretKeyRef": {"name": n, "key": k}}}
        for prefix, n in [("ADMIN", ROOT), ("READER", name)]
        for s, k in [("A", "access"), ("S", "secret")]
    ]
    policy_value = {
        "name": "POLICY",
        "value": json.dumps(POLICY).replace("thanos-workshop", bucket),
    }
    mounts = [tmp, trust]
    command = script
    if role:
        policy = json.loads(json.dumps(POLICY))
        policy["Statement"][0]["Action"].append("s3:ListBucketMultipartUploads")
        policy["Statement"][1]["Action"] += [
            "s3:PutObject",
            "s3:AbortMultipartUpload",
            "s3:ListMultipartUploadParts",
        ]
        if role == "compactor":
            policy["Statement"][1]["Action"].append("s3:DeleteObject")
        if role == "tier-marker":
            policy = json.loads(json.dumps(POLICY))
            policy["Statement"].append(
                {
                    "Effect": "Allow",
                    "Action": ["s3:PutObject"],
                    "Resource": [
                        "arn:aws:s3:::thanos-workshop/*/" + f + "-mark.json"
                        for f in ("deletion", "no-downsample", "no-compact")
                    ],
                }
            )
        policy_value["value"] = json.dumps(policy)
        command = script.replace("thanos-workshop-read", "thanos-workshop-" + role).replace(
            "workshop read-only policy attached",
            "bucket-scoped " + role + " policy attached",
        )
    extra = []
    if fixture:
        # Only synthetic files from the previous 28-day block drill, never a live shelf.
        uid = kube(
            "get",
            "pods",
            "-l",
            "job-name=thanos-warm-block-drill-nmqfh",
            "-o",
            "jsonpath={.items[0].metadata.uid}",
        ).strip()
        from uuid import UUID

        sub = "drill-" + str(UUID(uid))
        extra = [
            {
                "name": "fixture",
                "persistentVolumeClaim": {
                    "claimName": "thanos-warm-s1-candidate",
                    "readOnly": True,
                },
            }
        ]
        for res in ("300000", "3600000"):
            mounts.append(
                {
                    "name": "fixture",
                    "mountPath": "/fixture/" + res,
                    "subPath": sub + "/" + res,
                    "readOnly": True,
                }
            )
        command = script.replace("thanos-workshop-read", "thanos-hour-fixture-read").replace(
            "printf '%s'",
            """/tmp/mc mb warm/thanos-hour-fixture >/dev/null
for d in /fixture/*/*; do
    test -f "$d/meta.json"; id=${d##*/}
    /tmp/mc cp --recursive "$d/" "warm/thanos-hour-fixture/$id/" >/dev/null
done
cd /fixture/3600000
find . -type f -exec sha256sum {} \\; | sort
printf '%s'""",
        )
    c = {
        "name": "provision",
        **base,
        "command": ["sh", "-ec", command],
        "volumeMounts": mounts,
        "env": [*env, policy_value],
    }
    create(
        "Job",
        {
            "spec": {
                "activeDeadlineSeconds": 240,
                "ttlSecondsAfterFinished": 3600,
                "backoffLimit": 0,
                "template": {
                    "metadata": {"labels": {"thanos-warm-client": "seed"}},
                    "spec": {
                        **BASE,
                        "nodeSelector": {"kubernetes.io/hostname": "socrat-1"},
                        "initContainers": [fetch],
                        "containers": [c],
                        "volumes": [
                            *extra,
                            {"name": "tmp", "emptyDir": {"medium": "Memory", "sizeLimit": "96Mi"}},
                            {
                                "name": "trust",
                                "secret": {
                                    "secretName": "thanos-warm-api-tls",
                                    "items": [{"key": "ca.crt", "path": "ca.crt"}],
                                },
                            },
                        ],
                    },
                },
            }
        },
        name + "-bootstrap",
        api="batch/v1",
    )


if __name__ == "__main__":
    main()
