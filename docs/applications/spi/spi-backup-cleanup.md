# Private backup cleanup correction

The POSIX main-thread helper blocks SIGALRM across temporary-file and connection
ownership assignment. Its one-shot handler disarms before raising (including a
manual deadline check). Cleanup blocks and cancels cancellation before independently
attempting both connection closes, a remaining descriptor close, and all four
owned SQLite path/sidecar unlinks. Cleanup exceptions remain failures, never valid
backup output. Pending helper SIGALRM is consumed before restoring the caller's
handler and elapsed-time-adjusted periodic timer. The CLI's canonical stderr and
nonzero immediate exit occur only after cleanup.

The main operation deadline includes backup, integrity VM, streaming and flush.
Ownership acquisition defers signal delivery until assignment; this requires
normally returning OS/SQLite acquisition calls. Neither this deadline nor cleanup
can bound uninterruptible kernel I/O. Cleanup uses one attempt per resource, not
retry loops, background workers or additional timers. Actual unlink errors remain
failures and cannot guarantee deletion on a failing filesystem.

The independent review recorded two intermittent busy-source leftovers after
process exit. The exact historical race remains UNKNOWN; neither creation nor
close interruption is proven to have caused those cases. Earlier 15x4 passes
were not proof. New real-file boundary tests exercise pending creation signals,
close exceptions, sidecar removal and caller alarm restoration. Existing actual
subprocess blocked-consumer, broken-pipe, busy-source, open failure and slow
integrity cases retain wait-before-path-absence assertions.

Validation: existing sha256:87741b7b6a39b2ac77606ced0bd8f809297d77dd89df0d49b28356b28883fb5e
linux/amd64 image, network none, RO root/source/Git common directory, 384 MiB,
one CPU, private 64 MiB tmpfs: CLI 28/28, hash 5/5, backup 9/9 followed by
15 more complete 9-test runs; final added prior-periodic-timer regression 10/10.
This is not a fresh reproduction of the old intermittent failure, nor a fresh
full worker/compatibility/asset/CVE run. Those unchanged-source proofs remain
as recorded in /tmp/spi-operator-hash-final-review.md. No production operation,
authorization refresh, registry, build, deployment or model call occurred.
