# Wiki native OIDC identity patch

**Historical overlay, superseded 2026-11-07.** The active runtime uses upstream
`f52cf2a` with the small groups-scope preservation layer in `../upstream`. This
recipe and old image are retained for provenance/rollback; do not apply these
0.4.1 source edits to the new runtime. See `docs/wiki-upgrade-20261107.md`.

Live on 2026-11-01. This is a narrow patch over upstream hugo-docs **0.4.1**,
not a claim that the unmodified release supports OIDC. Original source SHA-256:
`867041976f336ea6d8c4956470c15db498b6896f078102160994d618c445ed69`.
The generic source change and nine OIDC regressions are recorded in hugo-docs
commit `c6ffb18` (`feat(auth): add native OIDC with owner-only local fallback`).
This is a source commit, not a new tagged upstream release.

- Authlib 1.6.6 handles authorization code, PKCE S256, nonce, signature/audience/expiry.
- Issuer is pinned; groups are mapped to native reader/editor/admin roles.
- Existing IDs are linked by explicitly reviewed issuer+subject, never email/name.
- Local passwords and pre-migration local sessions are accepted **only** for the
  explicit existing owner ID, not for every admin-role user.
- Default `/login` enters OIDC; `/login?local=1` is the owner's existing local form.
  Its public visibility does not grant other accounts password access.
- Public reading and bearer-authenticated `/mcp` are unchanged.
- UVICORN_ACCESS_LOG=false avoids logging authorization callback codes/state.
- Existing password hashes are preserved. A saved initial owner password was stale;
  no reset was performed. Owner must verify fallback with his current password.

`auth-edits.json` contains only exact public source edits and SHA-256 guards.
The Dockerfile is reproducible without the adjacent checkout. The vendored chart
in `../chart` adds only a Secret-backed OIDC environment hook; upstream license is
preserved here. Do not embed OAuth/state signing secrets in chart values.

```sh
docker build --platform linux/amd64 -t <registry>/homelab/wiki-runtime:<revision> deploy/wiki-runtime/oidc
# Push using protected stdin credentials; preflight an authenticated manifest pull.
# Pin the digest returned by THE REGISTRY, not Podman's local OCI RepoDigests:
# registries may convert manifests, producing a different Docker manifest digest.
```

Current registry manifest: `sha256:64d27d6f320ab7440be82578d1d73193278e6b12f77127776b715c2e98b17515`.
Private image uses the existing scoped cluster-pull robot in `wiki-harbor-pull`.
New node starts depend on Harbor unless the exact image is cached; this is not HA.

`identity-integrations.yml` with explicit service `wiki` reconciles client settings
and exact reviewed mappings into `socrat-authentik-wiki`, preserving state-signing
key. It restarts only the Wiki deployment when an active Secret actually changes.
First deployment requires the OIDC-enabled image/chart and this Secret together.
The Argo CD Application `wiki-runtime` declares the vendored chart and immutable image in this repository. Publishing
changes to main can trigger reconciliation; check the Application and running image after
publishing. Do not add a Fleet GitRepo beside it. Keep subsequent changes in this source path, not a competing manual
release manager. Historical evidence captures the earlier pre-publication state;
committing source is not itself proof of runtime acceptance.

A frozen, full-volume offline-consistent backup and configuration/Secrets are
AES-GCM encrypted on the owner Mac. SQLite integrity, exact original IDs and
unchanged password hashes were checked. Full application restore is NOT tested.
Temporary backup/image-check/smoke pods and users were removed. Public health,
real observer password/TOTP/OIDC flow and MCP read were verified.

The two direct WG-IP:443 routes currently present a non-Wiki certificate (neither
live gateway release contains a Wiki virtual host). This is a pre-existing private
routing gap, not an invitation to disable TLS verification. Public ingress works
through both edge IPs. Do not claim private-route TLS acceptance or blindly run the
legacy wiki-editor-access role over the migrated private gateway.
