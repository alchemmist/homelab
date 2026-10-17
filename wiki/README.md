# Socrat Wiki

Public Russian documentation for Socrat at <https://wiki.alchemmist.xyz/>. The site uses `github.com/alchemmist/hugo-docs` v0.1.0 and its pinned `hugo-content` dependency. The established theme supplies typography, folder navigation and local search; the Socrat icon comes from `deploy/litellm/branding/socrat-icon-v1.png` and is resized for the web.

## Local workflow

Install Hugo 0.167.0, Go 1.23 or newer, and Node.js 22 or newer with npm, then run:

```sh
make -C wiki check
make -C wiki dev
```

Open <http://localhost:1321/>. Production builds exclude drafts. `make check` validates rendered internal links and anchors, Russian search content, robots metadata, the 404 page, build metadata and publication boundaries.

Notes belong in `content/`. Folder `_index.md` files contain navigation title and weight only; the root `_index.md` is the home page. Prefer Hugo `relref` links to notes. Do not copy private infrastructure documentation, credentials or personal configuration into the public site. `noindex` is not access control.

## Container

```sh
make -C wiki image SOURCE_SHA=local
```

The only Docker build context is `wiki/`; `.dockerignore` allowlists site inputs. The runtime is static nginx on port 8080 as UID/GID 101, supports a read-only root filesystem with writable `/tmp`, and needs no volume containing user data. `/healthz` is the readiness endpoint. `/version.json` reports `source_sha` (a full commit SHA in CI, `local` for local builds). The full nginx configuration emits `X-Robots-Tag: noindex, nofollow` on successful and error responses.

Runtime theme assets and the search index are hosted locally; readers do not need a third-party search service. No sitemap or RSS feed is generated.

## Private inline editor

The page itself becomes editable when the private gateway authorizes an administrative WireGuard peer. Tiptap stores Markdown in the same Git repository; it does not replace Hugo or the publication workflow. Frontend tests verify existing content roundtrips, including Hugo relref links. Unsupported special syntax is refused before editing so it cannot be silently lost. See `docs/wiki-editor-network.md` at the repository root for split-DNS and gateway setup, and `wiki-editor/README.md` for the backend contract.
