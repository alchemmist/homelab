# Pinned upstream wiki runtime

Source: alchemmist/hugo-docs `f52cf2a6c61faeaf9734053c14b63f7d5e1ad276`,
9 commits after latest tagged v0.4.1; this is NOT a new upstream release tag.
The unmodified linux/amd64 runtime was built from that exact source using
`runtime/Dockerfile` and published to Harbor by immutable registry digest.
The Dockerfile here derives from that pin and preserves one Socrat-specific
contract: requesting `groups` with `openid profile email` from Authentik.
Upstream omits that scope; applying it unchanged would risk losing group claims.
The source SHA-256 and exact old text guard the one-line change.
No client secret, issuer, account mapping, password or session signing key changes.

Final image: `harbor.socrat.alchemmist.xyz/homelab/wiki-runtime:upstream-f52cf2a-socrat-20261106`
Registry digest: `sha256:dc5b15b391cd94fad3db51dc7fa917e138d77ea345e27518371073538c5a78d9`.
Both base and final images passed fresh-volume container acceptance and 9 OIDC
regressions; final image additionally asserts the preserved groups scope.

Historical 0.4.1 OIDC overlay under `../oidc` is retained for provenance/rollback,
not applied on top of this runtime. Existing vendored chart matches upstream
except for the explicit single-writer `replicaCount` maintenance knob (0 or 1).
The current PVC, contentPrefix, branding, secret references and account identities
are preserved. Deployment remains Argo CD-owned.

Before upgrade, the only writer was stopped declaratively through a temporary
replicaCount=0 Git commit. A root-private full-volume archive and native-account/
Secret fingerprints were captured on socrat-0 with SQLite integrity checks.
Backup is not an independently tested disaster-recovery restore. Re-enable one
writer with the image pin in Git; never run old and new writers simultaneously.
