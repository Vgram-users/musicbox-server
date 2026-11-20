#!/usr/bin/env python3
"""Импорт локальной музыки в библиотеку сервера.

    python scripts/import_music.py /storage/emulated/0/Music you@example.com --password secret123

Повторный запуск дубликаты не создаёт (сверка по названию + размеру файла).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Track, User  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.storage import storage  # noqa: E402

AUDIO_EXT = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
    ".wav": "audio/wav",
}


def split_name(path: Path) -> tuple[str, str]:
    stem = path.stem.replace("_", " ").strip()
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        return artist.strip(), title.strip()
    return "", stem


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="папка с музыкой")
    parser.add_argument("email", help="владелец библиотеки")
    parser.add_argument("--password", default="changeme123", help="пароль, если пользователя ещё нет")
    args = parser.parse_args()

    if not args.source.is_dir():
        print(f"нет такой папки: {args.source}")
        return 1

    init_db()
    db = SessionLocal()

    user = db.scalar(select(User).where(User.email == args.email.lower()))
    if user is None:
        user = User(
            email=args.email.lower(),
            password_hash=hash_password(args.password),
            display_name=args.email.split("@")[0],
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"создан пользователь {user.email} / {args.password}")

    files = sorted(p for p in args.source.rglob("*") if p.suffix.lower() in AUDIO_EXT)
    added = skipped = 0

    for path in files:
        artist, title = split_name(path)
        size = path.stat().st_size

        duplicate = db.scalar(
            select(Track).where(Track.title == title, Track.size_bytes == size, Track.owner_id == user.id)
        )
        if duplicate is not None:
            skipped += 1
            continue

        key = f"tracks/{path.stem[:60]}-{size:x}{path.suffix.lower()}"
        with path.open("rb") as fh:
            stored = storage.save(key, fh)

        db.add(
            Track(
                title=title[:255] or path.name[:255],
                artist=artist[:255],
                size_bytes=stored,
                mime_type=AUDIO_EXT[path.suffix.lower()],
                storage_key=key,
                owner_id=user.id,
            )
        )
        db.commit()
        added += 1
        print(f"+ {artist + ' - ' if artist else ''}{title}")

    db.close()
    print(f"\nготово: добавлено {added}, пропущено {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
