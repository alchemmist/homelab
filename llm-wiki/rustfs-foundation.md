# RustFS foundation (inactive, incomplete)

Read `docs/rustfs/foundation-review.md` and
`docs/n8n/spi/rustfs-migration-plan.md` before further work. Current source is
only a disabled isolated foundation scaffold, not a working artifact gateway.
RustFS 1.0.4 official docs support native OIDC (PKCE S256/client_secret_post);
never replace authorized Authentik membership with generic authenticated login.
S3 uses scoped SigV4 keys independently. No root key in SPI/reader.
No deployment or push performed. Outstanding: gateway, IAM/bootstrap, Authentik
mapping and admission, TLS, signing/security tests, standalone/resource/probe
verification and runtime checks. Single-node local disk is neither HA nor an
independent backup; local-path size is not quota. Preserve all SPI/n8n identities,
state, write-disabled policies and historical evidence. All activation stays off.
