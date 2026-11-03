"""One-off copy of all data from the local database into Neon.

Usage: GA_SOURCE_URL=... GA_TARGET_URL=... python migrate_to_neon.py
The target must be empty and already migrated (alembic upgrade head).
"""

import io
import os

import psycopg

TABLES = [
    "spot_quotes", "candles", "local_metal_rates", "fx_rates", "macro_observations",
    "observation_revisions", "collection_runs", "economic_events", "analysis_snapshots",
    "purchase_plan", "app_settings", "ai_analyses",
]
IDENTITY_TABLES = ["observation_revisions", "collection_runs", "ai_analyses"]


def plain(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


with psycopg.connect(plain(os.environ["GA_SOURCE_URL"])) as src, psycopg.connect(plain(os.environ["GA_TARGET_URL"])) as dst:
    for table in TABLES:
        if dst.execute(f"SELECT count(*) FROM {table}").fetchone()[0]:
            raise SystemExit(f"target table {table} is not empty; stopping")
    # Snapshots are protected by a no-update/no-delete trigger; inserts are allowed.
    for table in TABLES:
        buf = io.BytesIO()
        with src.cursor().copy(f"COPY (SELECT * FROM {table}) TO STDOUT (FORMAT binary)") as out:
            for chunk in out:
                buf.write(chunk)
        buf.seek(0)
        with dst.cursor().copy(f"COPY {table} FROM STDIN (FORMAT binary)") as inp:
            inp.write(buf.read())
        count = dst.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        print(f"{table}: {count} rows")
    for table in IDENTITY_TABLES:
        dst.execute(
            f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE((SELECT max(id) FROM {table}), 1))"
        )
    dst.commit()
print("done")
