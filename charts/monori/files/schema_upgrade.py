"""Run inside the pinned Monori backend image, in the PreSync Job only."""

import os
from pathlib import Path

import psycopg


def upgrade(db, root):
    """Upgrade in the caller's transaction; never infer earlier state or downgrade."""
    marker = root / "revision"
    target = marker.read_text().strip() if marker.exists() else "0022"
    if len(target) != 4 or not target.isascii() or not target.isdigit() or target < "0022":
        raise ValueError("Invalid Monori image schema target")
    db.execute("SET LOCAL ROLE monori_owner")
    db.execute("SET LOCAL lock_timeout = '8s'")
    db.execute("LOCK TABLE public.alembic_version IN EXCLUSIVE MODE")
    versions = db.execute("SELECT version_num FROM public.alembic_version").fetchall()
    supported = [f"{number:04d}" for number in range(21, int(target) + 1)]
    if len(versions) != 1 or versions[0][0] not in supported:
        raise ValueError("Unsupported schema revision; refusing downgrade or bootstrap")
    for version in supported[supported.index(versions[0][0]) + 1 :]:
        matches = list(root.glob(f"{version}_*.sql"))
        if len(matches) != 1:
            raise RuntimeError(f"Expected one migration for {version}, found {len(matches)}")
        migration = matches[0]
        db.execute(migration.read_text())
        if db.execute("SELECT version_num FROM public.alembic_version").fetchall() != [(version,)]:
            raise RuntimeError(f"Migration did not reach {version}")
    db.execute("SELECT refund_tx_id, original_tx_id FROM public.refund_links LIMIT 0")
    db.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON public.refund_links TO monori_app")
    for version in supported[2:]:
        grants = root / "grants" / f"{version}.sql"
        if grants.exists():
            db.execute(grants.read_text())


if __name__ == "__main__":
    with psycopg.connect(os.environ["MIGRATION_URL"], connect_timeout=6) as connection:
        upgrade(connection, Path("/app/server/postgres"))
