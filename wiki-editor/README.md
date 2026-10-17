# Wiki editor service

Private API for the Socrat Wiki inline editor. Run one replica and one Uvicorn worker. All repository operations are serialized within the process. The deployment must restrict ingress to the private gateway; that gateway must replace, never append or forward, `X-Socrat-WG-Peer` with the actual WireGuard client address. The gateway must also overwrite `X-Socrat-Editor-Key` with a shared secret matching `EDITOR_GATEWAY_TOKEN`. Missing or incorrect secrets fail closed; never forward this secret to browser clients.

## Configuration

| Variable | Value |
| --- | --- |
| `EDITOR_GATEWAY_TOKEN` | Required shared secret supplied only by the trusted gateway |
| `GIT_REPOSITORY` | SSH repository URL with a dedicated write deploy key |
| `GIT_SSH_KEY` | Readable mounted private key path |
| `GIT_KNOWN_HOSTS` | Readable mounted pinned SSH host keys file |
| `GIT_BRANCH` | `main` by default |
| `WORK_DIR` | `/data/repository` by default |
| `PUBLIC_ORIGIN` | `https://wiki.alchemmist.xyz` by default |

Mount a writable `/data` volume owned by UID/GID 1000. The clone is disposable; committed content resides in the remote repository. Mount SSH credentials read-only, readable by UID 1000. The container listens on port 8080. Use a TCP readiness probe. Do not expose its port publicly or configure multiple workers/replicas against the same working clone.

## API

All endpoints live under `/api/editor/`, require a gateway-provided administrative WireGuard peer address in `10.250.0.0/24`, and return `Cache-Control: no-store`.

- `GET session` creates an eight-hour Secure, HttpOnly, SameSite=Strict session cookie and returns `{writable:true,csrf_token}`.
- `GET pages?path=ai/example.md` returns `{path,title,body,revision}`. Paths are relative to `wiki/content`; revision is the Git blob SHA.
- `GET catalog` returns `{sections:[{path,title}]}`. The root section has an empty path.
- `PUT pages` accepts `{path,title,body,revision}`.
- `POST pages` accepts `{section,slug,title,body}`. Slugs use lowercase ASCII letters, digits and hyphens. Sections must already exist and contain `_index.md`.
- Both writes return `{commit,path,url,revision}`. Unknown YAML front-matter fields and weights are retained. Only YAML-front-matter UTF-8 Markdown is supported. Writes commit directly to `main` with a service identity and a lowercase English message. No force push is used.
- `POST preview` accepts `{path,title,body}` and returns `{html,approximate:true}`. This is a Markdown preview, not an exact Hugo build. Raw HTML is escaped, unsafe link protocols are blocked, `relref` is resolved, and arbitrary Hugo shortcodes are never executed. The browser must render the result in its sandboxed preview frame.
- `GET publications/{commit}` checks public `version.json` and returns `{status,url}`. Status is `published` when that commit or a descendant is deployed, otherwise `pending`. This API cannot assert a CI failure without authenticated CI status access; frontend polling must eventually show an unconfirmed publication notice with a CI link rather than claim success.

Every write/preview requires the exact public `Origin` and `X-CSRF-Token`. Sessions are bound to the gateway peer address and expire on service restart. The frontend should reacquire a session when necessary without discarding the draft. Request bodies are limited to 2 MiB; Markdown text is limited to 256 KiB. Same-file edits conflict with HTTP 409. Concurrent unrelated repository changes are fetched and retried up to three times. Repository failures return HTTP 503. Validation errors return HTTP 400/422.

## Tests

```sh
python3 -m venv /tmp/wiki-editor-venv
/tmp/wiki-editor-venv/bin/pip install -r wiki-editor/requirements.txt httpx==0.28.1
/tmp/wiki-editor-venv/bin/python -m unittest discover -s wiki-editor/tests -v
```

Tests use temporary local bare repositories. They verify metadata preservation, revision conflicts, unrelated and same-page push races, path/symlink rejection, peer binding, CSRF/Origin validation, creation conflicts and escaped preview HTML. They never push to the live repository.
