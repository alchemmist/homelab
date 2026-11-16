# Private web search

SearXNG runs on `socrat-5` in namespace `llm`, with the internal API at `http://searxng.llm.svc.cluster.local:8080`. Its HTML UI and JSON API share `https://search.socrat.alchemmist.xyz/`, reached through the private Socrat network. The chart creates no public ingress or NodePort.

Open WebUI uses its native SearXNG search integration. The query URL is `http://searxng.llm.svc.cluster.local:8080/search?q=<query>&format=json`. WebUI grants search to users and enables it for Qwen independently of the SearXNG service.

## Git-owned maintenance

Existing owner: `deploy/argocd/apps/searxng.yaml` and `charts/searxng/`.
Commit reviewed changes to that source and verify the addressed Application.
`ansible/playbooks/searxng.yml` and the legacy `search.yml` umbrella are retired,
refusal-only before namespace/key creation, Helm or imported integration/DNS writes.
Do not use either as a bootstrap/recovery fallback. Preserve the existing signing
Secret and native WebUI permissions; separately review new installation/recovery.
Companion access/integration helpers have not been certified as safe-to-run and
are not authorized by this documentation update. Existing DNS/TLS paths are unchanged.

The installed image digest/version must be read from the owning Git values and
accepted runtime revision. The version and network checks below are historical
receipts, not a recommendation to redeploy the original initializer.

Only free Bing and Brave HTML engines are enabled. During deployment checks on 2026-10-19, Brave returned relevant results for English and Russian queries and Bing returned ten results for an English query. Google returned access denied and DuckDuckGo a CAPTCHA, so they were excluded. Upstream services can still throttle or change their pages; this is not an availability guarantee. Engine selection is managed in `charts/searxng/values.yaml`.

The service has a one-CPU and 768 MiB memory limit. Its cache is ephemeral. The SearXNG bot limiter is disabled for this private service; do not publish it publicly without revisiting access controls and rate limiting. Search requests leave the cluster for the configured upstream engines.

Validation on 2026-10-19: the private HTTPS UI returned 200 with a trusted certificate; its JSON API returned 33 results. All three WireGuard DNS resolvers returned `10.250.0.1`; the public IP with the same hostname returned 404. WebUI's actual native `search_web` returned three results for both English and Russian queries under a regular user's context; `fetch_url` extracted 2,062 characters from Debian's page. Both active users have search permission and model read access. The configuration helper's second run made no changes. New Qwen chats enable search by default; existing chats may need their Web Search toggle enabled.

References: [official container installation](https://docs.searxng.org/admin/installation-docker.html), [server settings](https://docs.searxng.org/admin/settings/settings_server.html), [search API](https://docs.searxng.org/dev/search_api.html), [Open WebUI integration](https://docs.openwebui.com/features/chat-conversations/web-search/providers/searxng/).
