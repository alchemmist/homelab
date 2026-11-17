# Exact frozen compatibility inputs, not a lint-debt exemption

`charts/spi-triage/LEGACY-SOURCE-MANIFEST.json` predates this strict cleanup
(commit `de6f81e8`). It declares the separate canonical repository
`https://github.com/alchemmist/spi-triage`, says these are frozen compatibility
inputs that must not be developed here, and already records17backend SHA-256
values. The manifest and all17source files remain byte-identical. No checksum
was regenerated to bless this cleanup.

The strict ownership boundary now recognizes precisely those existing files.
`quality/strict-policy.json` pins the existing manifest bytes; the checker then
validates the canonical repository, fixed directory,17file count, safe basenames,
no symlinks/path escapes and every preexisting source digest. Validation runs
before exclusion in `owned()`, in graph-integrity contracts and in strict_guard.
Any missing or modified input fails closed rather than disappearing from lint.

This does **not** exclude the SPI chart, its file directory, its locally maintained
UI/backend integration, Helm output, or a newly added neighbouring Python file.
The root continues to validate/render its actual manifests. The secrets scanner
continues staging **all tracked files**, including vendor and frozen source.
Unlisted local code remains subject to owned-code checks. Frozen-input provenance
is not an authenticity/signature claim or a third-party vulnerability exemption.

Mutation tests verify changed bytes, missing input, a symlink, changed manifest,
an added manifest entry, path traversal even with a changed fixture digest, and
that new neighbours remain owned. Temporary test fixture changes are not updates
to the actual provenance pin. An upstream source update requires a separately
reviewed version/provenance change and tests; never automatically recapture the
manifest/digest merely to silence a linter.

This is the operator's narrow third-party-code scope, not acceptance of historical
owned-code findings. Other byte mirrors/content-addressed local inputs remain
owned and still need coordinated fixes; this document does not exempt them.
