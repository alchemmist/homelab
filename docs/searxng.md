# Private web search

SearXNG runs on `socrat-1` in namespace `llm`, with the internal API at `http://searxng.llm.svc.cluster.local:8080`. Its HTML UI and JSON API share `https://search.socrat.alchemmist.xyz/`, reached through the private Socrat network. The chart creates no public ingress or NodePort.

Open WebUI uses its native SearXNG search integration. The query URL is `http://searxng.llm.svc.cluster.local:8080/search?q=<query>&format=json`. WebUI grants search to users and enables it for Qwen independently of the SearXNG service.

Deploy from `ansible/`:

```sh
ansible-playbook playbooks/search.yml
```

The umbrella playbook runs `searxng.yml`, `searxng-private-access.yml`, and `open-webui-search.yml` in order. They can also be run individually for targeted maintenance.

The service playbook creates the Kubernetes signing secret once and retains it on subsequent runs. No signing secret or search provider API key is stored in Git. The official `docker.io/searxng/searxng` image is pinned by the registry's multi-platform manifest digest; the initial deployment uses version `2026.10.19-d47cb96bf`.

Only free Bing and Brave HTML engines are enabled. During deployment checks on 2026-10-19, Brave returned relevant results for English and Russian queries and Bing returned ten results for an English query. Google returned access denied and DuckDuckGo a CAPTCHA, so they were excluded. Upstream services can still throttle or change their pages; this is not an availability guarantee. Engine selection is managed in `charts/searxng/values.yaml`.

The service has a one-CPU and 768 MiB memory limit. Its cache is ephemeral. The SearXNG bot limiter is disabled for this private service; do not publish it publicly without revisiting access controls and rate limiting. Search requests leave the cluster for the configured upstream engines.

Validation on 2026-10-19: the private HTTPS UI returned 200 with a trusted certificate; its JSON API returned 33 results. All three WireGuard DNS resolvers returned `10.250.0.1`; the public IP with the same hostname returned 404. WebUI's actual native `search_web` returned three results for both English and Russian queries under a regular user's context; `fetch_url` extracted 2,062 characters from Debian's page. Both active users have search permission and model read access. The configuration helper's second run made no changes. New Qwen chats enable search by default; existing chats may need their Web Search toggle enabled.

References: [official container installation](https://docs.searxng.org/admin/installation-docker.html), [server settings](https://docs.searxng.org/admin/settings/settings_server.html), [search API](https://docs.searxng.org/dev/search_api.html), [Open WebUI integration](https://docs.openwebui.com/features/chat-conversations/web-search/providers/searxng/).
