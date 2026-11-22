# LMS certification sandbox runner (reference only)

From the homelab root, render the four objects without network or cluster access:

```sh
uv run --locked python deploy/lms-certify/runner/render.py ../lms > /tmp/certification-runner.json
```

The local `alchemmist/lms` clone must contain commit
`10307eea58e346b560749cc6861b1bbb53b209f5`. The renderer reads eight Git blobs,
not the working copy; `launch.py` is the ninth ConfigMap key. It emits only the
runner ConfigMap, Deployment, Service and ingress NetworkPolicy in `automation`.
This directory is not an Argo CD application or an automatic restore job.

The existing Secret `lms-certification-pilot` supplies `JUDGE` and `RUNNER`;
no Secret values are included. The pod runs as UID/GID 1000 on `socrat-1`
and uses that user's rootless Docker socket. Its read-only volume mount does
**not** make the Docker API read-only. The daemon must already have
`lms-certification-sandbox:pilot`. The service is on port 9000; the ingress
policy selects n8n pods in the same namespace. Preserve these boundaries.

This records the deployed configuration, not an immutable runtime image:
`python:3.12-slim`, the local sandbox tag and pip installation at startup are
unchanged. Recovery requires separate review of those prerequisites. Do not
create a standalone database, rotate credentials or import/activate workflows
when rendering the runner. Certification state lives in `pg-common`.
