#!/usr/bin/env python3
"""Бэкап библиотеки: дамп SQLite + архив медиа в ./backups, старые чистятся.

    python scripts/backup.py

Ставить в cron на сервере:
    0 4 * * * cd /opt/music-server && /usr/bin/python3 scripts/backup.py
"""

from __future__ import annotations

import sqlite3
import sys
import tarfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402

KEEP = 7


def main() -> int:
    if not settings.database_url.startswith("sqlite"):
        print("БД не SQLite — используй pg_dump, скрипт только архивирует медиа")
        return 1

    backups = ROOT / "backups"
    backups.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    db_path = Path(settings.database_url.split("sqlite:///")[-1]).resolve()
    if not db_path.exists():
        print(f"нет файла БД: {db_path}")
        return 1

    db_copy = backups / f"db-{stamp}.sqlite"
    with sqlite3.connect(db_path) as src, sqlite3.connect(db_copy) as dst:
        src.backup(dst)  # безопасно даже при работающем сервере
    print(f"БД  -> {db_copy} ({db_copy.stat().st_size // 1024} КБ)")

    media_dir = Path(settings.media_dir)
    if media_dir.exists():
        media_copy = backups / f"media-{stamp}.tar.gz"
        with tarfile.open(media_copy, "w:gz") as tar:
            tar.add(media_dir, arcname="media")
        print(f"медиа -> {media_copy} ({media_copy.stat().st_size // 1024 // 1024} МБ)")
    else:
        print(f"медиа нет: {media_dir}")

    for pattern in ("db-*.sqlite", "media-*.tar.gz"):
        stale = sorted(backups.glob(pattern))[:-KEEP]
        for path in stale:
            path.unlink()
            print(f"удалён старый: {path.name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
