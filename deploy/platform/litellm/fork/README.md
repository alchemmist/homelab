# LiteLLM Generic OIDC fork

The amd64 base is the selected manifest of the previously deployed 1.105.1 index
`sha256:b7b9e2c306343721802253d0dd9436b9634a2eb4e14da7c7cf06c5c7b7530802`.
`build.sh` appends one checked source file from `alchemmist/litellm` to its installed
Python package. All other application files, metadata, DB schema and entrypoint
remain those of upstream. Use GNU tar and crane v0.20.6 with a push-only-purpose
Harbor robot login to build; use only the project pull robot in `llm`.

Release: set the SHA tag **and manifest digest** in both the Helm image reference
and migration guard. Keep migrations disabled for this schema-identical build.
Check OIDC redirects on every published ingress address and anonymous API denial.
Rollback by reverting the values to the previous image and matching migration guard;
no database rollback. Do not change Authentik grants, keys or passwords.

`build-owner.sh` layers the owner-only Regenerate Key handler and dashboard chunk over the pinned OIDC image. Only `socrat-admin` with proxy-admin role and a dashboard session is admitted for virtual keys. Existing master-key rotation checks remain upstream. Roll back to the OIDC image to remove this feature.
