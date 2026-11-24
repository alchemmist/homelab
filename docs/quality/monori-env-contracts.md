# Monori runtime env/secret wiring contracts

Monori app images (`homelab-monori-back`, `homelab-monori-sync`, pinned by digest in
`deploy/monori/values.yaml` at commit `716141e6d9c6a9b04b8e5da9c9393a4a5b1018c2`,
public mirrors `ghcr.io/alchemmist/homelab-monori-{back,sync}:latest`) read runtime
configuration exclusively from environment variables:

- `monori-back` Deployment `back` container: `envFrom` secretRefs `monori-env` and
  `monori-postgres` (app startup requires `MONORI_DATABASE_URL`,
  `MONORI_CONSOLE_DATABASE_URL`, `.auth_secret` / `.encryption_key` paths in
  `/app/data` — see the rendered `require-monori-ledger` init container assertion).
  The FastAPI/uvicorn application has no file-based or CLI configuration interface
  for these values; the environment is the app contract.
- `monori-schema` Job `migrate` container: `MIGRATION_URL` via `secretKeyRef`
  (secret `monori-pg-migrator`, key `DATABASE_URL`) — consumed directly by
  `charts/monori/files/schema_upgrade.py`, which calls `psycopg.connect(os.environ['MIGRATION_URL'])`.

Both secrets are managed out-of-band (externally-managed runtime secrets, same class
as `MONORI_*` tokens in the harbor/netbird image-contract registrations). Docker
verification of the runtime hardening recorded during this pass:

- `homelab-monori-back` (uvicorn `monori.server.app.main:app`): full application
  startup as uid 1000 with `--read-only` root fs, tmpfs `/tmp`, PVC at `/app/data`;
  `GET /openapi.json` → 200 (probe target).
- `homelab-monori-sync` (uvicorn `monori.server.app.sync_service:app`, port 8010):
  full startup under the same hardening; `GET /health` → 200 (probe target).
- `homelab-monori-front` (nginx, uid 101): `nginx -t` passes as uid 101; `--read-only`
  fs serves `GET /` → 200 with writable mounts for `nginx` temp paths (`/var/cache/nginx`,
  `/run` for `nginx.pid`), provided in-cluster as dedicated `emptyDir`s plus pod
  `fsGroup: 101`.
- venv python in the back image runs as uid 1000 under `--read-only` +
  `PYTHONDONTWRITEBYTECODE=1` with a tmpfs `/tmp` (schema/migration jobs).
