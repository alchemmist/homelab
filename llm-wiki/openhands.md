# OpenHands Agent Canvas — installation and acceptance

Updated 2026-11-18. **Partial acceptance, NOT a completed Ready-to-Review service.**

## Installed

Official Agent Canvas 1.41.0, pinned image digest, upstream vendored chart under
`charts/openhands`, Argo Application `deploy/argocd/apps/openhands.yaml`, values
`deploy/openhands/values.yaml`. StatefulSet `openhands-0` is on socrat-5. Retained
6Gi PVC persists both `.openhands` state and `workspace` using upstream subpaths.
Restricted PSA, non-root, no capabilities/privilege escalation/SA token/RBAC,
no Docker socket or host filesystem. Quota storage 12Gi is headroom, not PVC resize.

Local runtime is the official shared-container backend: **not per-conversation or
multi-user isolation**. Do not expose it as an unrestricted shared coding service.
No GitHub write credentials, App signer, production or Kubernetes credentials are
provided to coding tools. NetworkPolicy permits DNS, the actual LiteLLM pod label,
and public HTTP(S), excluding RFC1918, metadata, loopback and CGNAT destinations.
Public production hosts are not distinguished by this policy; it is NOT domain
allowlisting or proof against public-production probing.

## Native configuration, not LLM_* environment assumptions

Run `python3 scripts/provision-openhands.py` explicitly as the operator, after Argo
creates the app. It creates/preserves a distinct LiteLLM virtual key restricted to
`venice-deepseek`, max_parallel_requests=1, in Secret `openhands-model`. Personal Pi
and SWE Mini keys are unchanged. The original copied SWE key was replaced by the
independent OpenHands key; no old key is revoked while SWE work might still use it.

The helper uses the native settings, provider-connection, LLM-profile and
AgentProfile APIs and activates `socrat-deepseek`. Profiles reference an encrypted
provider connection; no GH integrations, extra secrets or MCP servers are enabled.
UI launchers require an AgentProfile: merely setting legacy agent settings made
API-started tasks work but left the UI's LLM-setup warning. Environment LLM_MODEL,
LLM_BASE_URL and LLM_API_KEY did not configure native settings and were removed.

Native backend owner key is saved, without printing, in
`~/.config/homelab/openhands/session-key` (directory0700/file0600). Do not commit,
paste into chat, put into URLs or share it: access allows shell and file operations.
`pbcopy < ~/.config/homelab/openhands/session-key` copies it for the native backend
password field without printing it. Browser usage-reporting consent was opted out
in the diagnostic browser; do not assume that proves all SDK telemetry is disabled.

## Proven and not proven

- `7cb28d7a-87e3-4bcd-930f-5489faf77acb`: actual Venice/DeepSeek native tool calls,
  two terminal commands, `openhands-autonomy-ok` read back, then finish; no client
  connection was held open. Events and workspace are on PVC. Initial connection
  failure was a wrong NetworkPolicy pod selector; corrected via GitOps, then retried.
- Browser Canvas loaded through an operator-only loopback forward; native backend
  login and persistent conversation listing were inspected. This is NOT a public
  browser/close-laptop end-to-end acceptance.
- Longer PR500 pilot `e23f711a-5db2-47ce-a428-026d97a9bac9` cloned/read the repo but
  stopped with a future-intent sentence after a condensation event, without a
  candidate. `finished` is NOT evidence of task completion. Native Stop-hook
  behavior is under investigation; do not claim unattended long-task reliability.
- Publication, remote-CI follow-up and per-comment reply/resolve integration are
  NOT connected. `services/openhands/READY_TO_REVIEW.md` is policy, not enforcement.
  `scripts/openhands-pr-ready.py` is a read-only fail-closed audit, not an orchestrator.

## Public entrance: blocked on privileged DNS step

Ingress remains **disabled**. Intended URL `https://openhands.socrat.alchemmist.xyz`
is not yet a working public service. Existing native LAN session-key disclosure is
disabled; before enabling ingress, validate remote anonymous auth, TLS and UI.

All four installed authoritative renderer hashes matched the tracked baseline
`833d1fea75afe5ff76c172b7f73fb7ed82192b11f1b4ea4900b43d79dbfc6b3c` at inspection.
SSH succeeds through existing strictly pinned local aliases. The default inventory's
host-key-file/alias combination failed verification; no check was disabled or new
key accepted. Existing `sudo -n true` fails on all four nodes. Passwords are not
retained and must never be sent through chat.

A narrow DNS addition is prepared in `scripts/openhands-public-dns.py` and
`ansible/playbooks/openhands-public-dns.yml`: all four health combinations must keep
every unrelated record byte-identical; whole-fleet preflight, fresh exact hash,
serial refresh, private before/after receipts, no daemon restart. The source adds
only `openhands.socrat`; it has NOT been applied to authoritative servers.

Owner can run from the checkout, using existing SSH aliases and an interactive
sudo prompt (one-time infrastructure bootstrap, not the task UX):

```sh
ANSIBLE_CONFIG=ansible/ansible.cfg ansible-playbook \
  -i 'socrat-0,socrat-1,socrat-2,socrat-4,' \
  ansible/playbooks/openhands-public-dns.yml --ask-become-pass \
  -e openhands_public_dns_apply=true \
  -e openhands_public_dns_hash=4aba95fb60852174e00eb5ea98cdc848ee4b3b42e112622c5eb82860d40ac42f
```

Any renderer/script drift invalidates that hash; stop and obtain a fresh plan.
An uncertain marker is a blocker, not permission to retry. Afterwards independently
verify authoritative and recursive DNS, then enable ingress in Git, accept TLS/auth
and demonstrate a browser-started task continuing after closing its tab. Do not use
live ingress overrides or describe the diagnostic forward as the final entrance.

## PR500 handoff is still blocked

Last inspected head `c2be67056ea0e5c00a8d1be5238bd8c4fd50a820`, merge conflicts,
Workflow graph validation/Quality Graph red, other jobs skipped, CodeRabbit review
skipped for bot-authored PR. The actual graph error was three stale generated workflow
files (`uv run --locked --group quality-graph qg validate`); npm ci itself passed.
Current main `e2738ad` contains newer maintainer dependency updates that must not be
downgraded by conflict resolution. CodeRabbit needs a deliberate current-head review
request through the trusted handler. Never bulk-resolve remarks or treat skipped as
green. No merge or Ready-to-Review handoff has been performed.
