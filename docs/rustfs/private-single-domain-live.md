# Private RustFS browser domain — live edge, 2026-11-07

## Current browser endpoints

- Console: **https://rustfs.socrat.alchemmist.xyz/**
- Protected immutable evidence: **https://rustfs.socrat.alchemmist.xyz/spi/v1/…**
- Previous `https://spi-evidence.socrat.alchemmist.xyz/spi/v1/…` links remain compatible through a fixed-host **308 redirect** to the same validated immutable path on the RustFS domain. The old host does not serve artifact bodies or an authentication callback. Invalid paths and query-bearing legacy URLs are rejected; caller-supplied redirect destinations are not accepted.

The bucket remains private. Browser access is through an authenticated, read-only Reader, not anonymous S3 GetObject/ListBucket permission. Anonymous S3 listing was independently observed denied (403, body not read).

## Authentication and authorization

A dedicated RustFS-only Authentik `forward_single` provider/application protects the shared domain. The existing `homelab-owner` and `homelab-platform-operator` application bindings are enabled, non-negated, fail closed, and combined with `any` semantics. The Reader validates the session with a fixed same-origin Authentik endpoint and checks those groups; client identity headers are not authority. Missing browser sessions enter normal SSO and return to the **exact file**, rather than the console home. Forbidden sessions return 403; authentication-upstream failure returns 503 without artifact data.

Console traffic retains the existing identity-namespace bridge to RustFS port 9001, now behind ForwardAuth. Native RustFS OAuth provider 12 remains separate and unchanged. Its exact personal `alchemmist` identity mapping to `consoleAdmin` is preserved; this does not grant admin to an entire SSO group or make Reader access public. No global SSO repair or role elevation was performed.

## Raw browser presentation

The Reader preserves stored bytes and manifest/artifact integrity checks. JSON remains `application/json` with `Content-Disposition: inline`; safe text/log/YAML/CSV and existing reviewed preview types retain their deliberate presentation. Unknown types and active HTML are attachments. Responses retain `nosniff` and the restrictive CSP; no extra viewer or formatting layer is introduced.

Protected artifact responses now use **`Cache-Control: private, no-store`**. This intentionally favors privacy over browser-back/cache performance. Previously downloaded or cached responses from the former public Reader cannot be retroactively revoked. GitHub opening a link in a new tab remains browser/client behavior, not a server promise.

## Verified deployment and access

Edge source commit: `5c4f940754cf3269fedee271896bc352e25c7f62`.

Reader registry manifest:
`harbor.socrat.alchemmist.xyz/homelab/rustfs-gateway@sha256:9d884a7bd593fd6852db2da0af3f5117862f4a3c1e70e1928fd6b77ab10988ac`.

Argo reported this exact edge revision Synced/Healthy/Succeeded. Anonymous HEAD of an existing artifact returned canonical 401 with no body, while the old host returned the exact canonical 308 target; a legacy redirect-query attempt returned 404. A legitimate existing human SSO browser session automatically reached the exact canonical manifest and verified HTTP 200, 16,303 ASCII bytes, SHA-256 `af2b3b2d183b60bebd61520c527e1e3c682c0bb6df5b0fc2c149a4d610792a35`, inline JSON, `nosniff`, and private/no-store. The same legitimate browser retained native console access as `alchemmist`, with private bucket and IAM navigation visible.

No second forbidden human account login was performed, and a fresh native OIDC callback was not forcibly exercised after cutover. Denial logic has offline regression tests and actual application-binding readback; these are distinct from a second-user browser proof.

The RustFS storage Deployment pod template and UID, PVC render, SPI worker Deployment template/UID, and both SPI ConfigMaps remained unchanged through edge activation. SPI kept its active 10-node workflow and the other five workflows retained their active states. No paid job or waiting execution was cancelled or restarted for this edge rollout. Original immutable objects, manifests, published history, and evidence hashes were not rewritten.

## Pending: new publication-link origin

**The publication-generator rollout is not yet complete.** The running SPI worker still generates compatible old-host links. Those links now redirect to the protected canonical Reader, but this is not a claim that newly generated GitHub/Telegram artifact URLs already use the new primary host.

Canonical-origin generator changes are prepared separately. Applying them changes the SPI worker ConfigMap checksum/environment and causes Recreate. A current paid model reservation plus many durable Wait owners prevented a safe worker rollout. No workflow deactivation, owner/admission reset, forced retry, or paid-call interruption was used to force an idle window. Complete this remaining change only under a reviewed owner-aware, paid-safe drain or admission barrier, with a fresh verified backup immediately before its push/deployment.
