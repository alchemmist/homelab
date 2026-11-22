# Rancher native login recovery —15Nov2026,22:29MSK

> Historical15Nov recovery: placement below is superseded by the accepted
>16Nov return to5 with verified native issuer routing. See
> [current management handoff](../../../archive/vm105/vm105-management-20261116.md).

## Historical recovery result

Owner reported Rancher login broken after the node5 handoff. Rancher is now
intentionally back on **socrat-1**, desired replicas1, NO HA. Only Rancher moved
back: WebUI/Terminal/SearXNG/Umami app and previously accepted workloads stay on5.
Source fix d06f60e1 changes Rancher hard affinity and adds SSL_CERT_FILE pointing
to the existing image OS CA bundle /var/lib/ca-certificates/ca-bundle.pem.
Corresponding Ansible placement defaults/template and3source tests agree.
Rancher/chart2.15.2/image/native users/roles/OIDC client and public routes unchanged.
No VM/data transfer or SQL/password/token/credential reset.

## Findings: health was NOT login acceptance

Original node5 Pod Running1/1, restart0, native /ping200, protected /v3 API401,
Argo Synced/Healthy. Those were insufficient to accept native OIDC.
GET /v1-oidc/genericoidc returned302 but Location was the INCORRECT RELATIVE
/v1-oidc/?client_id=... rather than HTTPS Authentik. Rancher2.15.2 upstream
pkg/auth/providers/oidc/oidc_provider.go:GetOIDCRedirectionURL discards the
FetchAuthURL error, leaving an empty authorization URL when discovery fails.

Two independently reproduced conditions:

1. From actual node5 Rancher Pod, auth.socrat.alchemmist.xyz public IPv4 request
   resolves but never completes TCP connect:5.002second connection deadline,
   time_connect=0. No AAAA exists; not an IPv6-only issue. Exact network-level
   cause/hairpin/firewall attribution remains UNPROVEN. Do not alter VPN/firewall
   broadly or reissue OAuth credentials to treat this symptom.
2. Curl default trust lookup in the exact Rancher image fails with unable to get
   local issuer certificate. SSL_CERT_DIR points at /etc/rancher/ssl. The existing
   /var/lib/ca-certificates/ca-bundle.pem already trusts the presented Let's Encrypt
   chain (YR2 ->RootYR cross-signed ISRG RootX1); explicit CA file verifies it.
   Internal Traefik10.43.218.222 route on5 with existing bundle gets200 in1.098s,
   not without the bundle. Isolated same-image probe on original node1 with
   SSL_CERT_FILE gets real public IdP metadata200 twice in0.301/0.336s.

Upstream chart2.15.2 does not expose hostAliases; adding an ignored values key
would NOT fix node5 routing. Chose bounded recovery on known-good node1 rather
than a chart fork, public-edge change, global DNS rewrite, insecure TLS or broad
proxy/egress expansion during a login incident. Node5 return is not authorized as
"healthy" merely because /ping is green; require real issuer transport and login.

## Source and application

- Git first; exact2.15.2 upstream Helm rendered with ACTUAL kubeVersion1.36.5.
  Local Helm default1.37 was correctly rejected by chart constraints; no release
  upgrade/version bypass performed.
- Existing Argo Application refreshed, targeted natural rolling update5->1;
  original Deployment UID retained. Desired1 throughout; native surge briefly
  starts replacement while old5 drains, then old Pod disappears. This is not HA.
- All prior container env entries unchanged, only SSL_CERT_FILE added. Existing
  image trust roots used; no CA added, no verification skip flag.
- Full genericoidc AuthConfig JSON before/after EXACTLY equal, including metadata.
  No changes to Secret reference, client ID, issuer, scope, allowedPrincipalIds,
  accessMode, grants, local emergency users, native token or public-policy config.
- Placement Ansible defaults/template preserve recovery node and CA file on future
  execution. Do not run old migration instructions that repin Rancher5 blindly.

## Acceptance and limits

Actual new Rancher Pod on1, restart0:

- Native HTTPS discovery GET from Pod200 with default curl (no special CLI CA,
  no --resolve, no -k). Native Go login handler also succeeds with this env.
-3independent public login starts redirect to HTTPS auth.socrat.alchemmist.xyz,
  correct unchanged client/callback https://rancher.socrat.alchemmist.xyz/verify-auth,
  PKCE S256 and response_type code. The prior relative redirect is gone.
- Public /ping200 and protected /v3 still401; no authentication gate removed.
- User asked to refresh and complete THEIR native login. Human token exchange and
  resulting account permission check were not impersonated or claimed complete.

Private preimages/logs/receipts are0700/0600 under
~/Library/Application Support/homelab/rancher-login-20261115.
Two isolated no-SA-token same-image probe Pods used only curl, never Rancher
startup/user commands; removed after acceptance. No personal credentials printed.

Follow-up: establish a supported narrow node5 issuer route and correct trust
selection before another move, test actual OIDC authorization redirect and human
callback, and account for required anti-affinity with one eligible node during
same-node upgrades. Earlier migration healthy/ping claims are superseded for
Rancher placement and login only, not for other accepted application data.
