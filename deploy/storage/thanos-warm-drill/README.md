# Warm archive on socrat-1: isolated block acceptance

The job mounts only `thanos-warm-s1-candidate`, creates a fresh `drill-<pod UID>`
directory and uses loopback Store/Query endpoints. No Service, production block,
credential, Store discovery or change to production retention. It is an explicit
one-shot experiment, not an Argo hook. The scratch PVC directory survives Job TTL;
do not use it as a production bucket or delete the containing PVC.

Render with `python3 deploy/storage/thanos-warm-drill/job.py`. To repeat in the
Socrat context, inspect the rendered JSON then submit with `kubectl create -f -`.
Watch the generated Job in `cattle-monitoring-system`; inspect `upload`, `compact`,
`project`, and `verify` logs. A Job with no successful `verify` result is not accepted.

2026-11-21 16:36 UTC: `thanos-warm-block-drill-nmqfh` completed on socrat-1.
A 28-day synthetic gauge generated 336 raw blocks. Thanos v0.42.4 uploaded them
to the local FILESYSTEM bucket; the one-shot Compactor produced five active 5m
blocks and one 1h block. Each test Store saw **only** its resolution (hard-linked
synthetic files, no raw fallback). Both strict queries returned the expected 7 and
both raw-only negative controls were empty. This tests format, downsampling and
readback, not production-scale capacity, the 0→1 network or transfer to socrat-3.

Next gate: test the selected authenticated network transport from a disposable
shipper on 0 to an isolated bucket on 1. Interrupt only the disposable path,
continue ingesting numbered samples, restore access and compare timestamps,
values and block inventory through the test Store. Do not change the live
sidecar or retire its local bucket on the strength of this filesystem test.
