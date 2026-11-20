#!/usr/bin/env python3
"""Перенос данных с локального SQLite в Postgres (Neon).

    python scripts/migrate_to_postgres.py \
      sqlite:///./data/app.db \
      postgresql+psycopg2://user:pass@host/db?sslmode=require

Таблицы, которые уже создал сервер при старте, копируются с защитой от дублей.
"""

from __future__ import annotations

import sys

from sqlalchemy import create_engine, text

TABLES = [
    "users",
    "invite_codes",
    "tracks",
    "playlists",
    "playlist_items",
    "likes",
    "history",
    "resolve_cache",
]


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 1

    src = create_engine(sys.argv[1])
    dst = create_engine(sys.argv[2])

    for table in TABLES:
        rows = src.execute(text(f"SELECT * FROM {table}")).mappings().all()
        if not rows:
            print(f"{table}: пусто")
            continue

        columns = list(rows[0].keys())
        names = ", ".join(columns)
        params = ", ".join(f":{c}" for c in columns)
        stmt = text(f"INSERT INTO {table} ({names}) VALUES ({params}) ON CONFLICT DO NOTHING")

        copied = 0
        with dst.begin() as conn:
            for row in rows:
                try:
                    conn.execute(stmt, dict(row))
                    copied += 1
                except Exception as exc:
                    print(f"  пропуск в {table}: {str(exc)[:100]}")
                    break
        print(f"{table}: {copied}/{len(rows)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
