# Wiki Git zombie recovery — 2026-10-30

## Root cause

Production image `ghcr.io/alchemmist/hugo-docs-wiki@sha256:56b24ca70f7ebcb5c3d4844c0e5ec5b779416f74f891be5b24807f65e8878b7e`
runs Uvicorn as PID 1. Its app.py SHA-256 matched the local hugo-docs source
(`cfd33fa04771c545c430fe7d0cc86f2535684931593ecb5277d808bfca1731e4`).
The outbox worker fetches every 30 seconds. Git auto-maintenance detaches by
default; each fetch created one orphaned Git process that Uvicorn did not reap.
Direct subprocess.run calls did wait for their immediate children correctly.
About 3,950 Git zombies accumulated. Kubernetes exec eventually failed with
`unable to spawn stage-1: Resource temporarily unavailable`.

Reproduced with the exact production image in an isolated disposable container:
10 local fetches produced 10 Git zombies. Setting `maintenance.autoDetach=false`
and `gc.autoDetach=false` produced zero zombies after 20 fetches. Maintenance
remains enabled, but runs synchronously and is waited for.

## Applied mitigation

Both `/data/repository` and `/data/live/remote` now have local Git configuration:

```ini
[maintenance]
    autoDetach = false
[gc]
    autoDetach = false
```

Because exec was already failing, these two settings were initially written
through the host into the existing container's mounted repository config files.
Original ownership and permissions were preserved; private config backups named
`config.pre-zombie-fix-20261030` remain alongside them. No content/history/account
files were changed. A single Deployment rollout restart cleared existing zombies.
The Recreate strategy retained the same PVC and single-writer model.

Verification: replacement pod Ready on socrat-3; zero zombies after multiple
30-second worker cycles; Git sync state has no error; public HTTPS returns 200.
No changes were made to observability or the active archive transfer.

## Reapply

`ansible/playbooks/wiki-process-lifecycle.yml` idempotently manages these two
repository-local settings via the existing runtime. Run with the normal verified
inventory/access overrides. It does not restart by default. An explicit
`-e wiki_process_reconcile=true` recreates the single writer and waits for readiness.
A temporary Wiki interruption is possible when reconciling. New repositories need
these settings applied again until the upstream fix is released.

## Upstream source fix

In the sibling `hugo-docs` repository, `runtime/app.py` now passes both Git options
on every invocation. This also covers initial clone and newly created repositories.
A unit test checks the command, and a Linux PID-1 integration test repeats 20
fetches and checks for orphaned Git zombies. The container integration test is
included in the Wiki CI workflow.

The upstream source fix does not itself publish a release;
the production image pin is unchanged. Publish a normal reviewed release and
update the Fleet chart/image pins separately when authorized. The current live
mitigation is persistent in the existing PVC, not an unpublished patched image.
