# Chart-owned nginx access logging

The private-gateway, optional syncthing private GUI, img-proxy, LiteLLM branding server and socrat-home nginx HTTP contexts emit `safe_json` access records to stdout. The format is JSON-escaped and contains ISO-8601 `timestamp`, stable `service`, status-derived `level` (4xx warn, 5xx error, otherwise info), method, normalized path (`$uri`), status, response bytes and duration. The nginx images run in their default UTC timezone; keep that timezone UTC when customizing images. No request line, query arguments, client IP, headers, cookies or auth values are included. Paths themselves can still contain sensitive identifiers: avoid putting credentials in URL paths.

Maps belong in the HTTP context, not server/location blocks. The socrat-home chart mounts a logging-only HTTP include and leaves the image's server/routing configuration intact. Existing gateway, proxy, cache, TLS and authentication directives are unchanged. Gateway config checksums already trigger rollouts; socrat-home has a new logging checksum. Deployments are not applied by this change.

These are **access** log changes, not a promise that all nginx output is JSON or safe: native nginx error logs remain native and can contain request details. Collector-side privacy handling and a separate error-log policy are still required. Do not enable debug logging in production. Confirm image-level server/location blocks do not override the HTTP access logger during rollout (especially socrat-home's external image).

## External image repositories still requiring source fixes

* `blog` (`harbor.socrat.alchemmist.xyz/homelab/blog`): chart does not own nginx configuration. Update the blog image source, verify its server config and rebuild/pin the digest; do not blindly replace its routing/cache configuration here.
* `cats` (`ghcr.io/alchemmist/cats`, fallback `alchemmist/cats`): chart does not own HTTP server configuration (target port 5173). Identify its actual runtime HTTP server and implement equivalent safe structured logging in the image repository.
* `socrat-home` (`ghcr.io/alchemmist/homelab-socrat-home`): chart now supplies the HTTP logging include, but image owners must keep `/etc/nginx/conf.d/*.conf` included at HTTP scope and avoid server/location access-log overrides. Image-native error logging still needs source-level review.

## Offline checks

Run `python3 -m unittest discover -s tests -p test_nginx_safe_access_logging.py`. Requires Helm and PyYAML. Syntax validation uses local Docker with `nginx:1.28.0-alpine` and no network; pre-load that image. It parses the exact rendered logging block in a minimal HTTP context, not deployment-specific TLS certificates, node addresses or upstream services. Tests render every affected chart, including syncthing's opt-in GUI and socrat-home with homepage assets disabled. No cluster access, production mutations or sensitive log samples are used.
