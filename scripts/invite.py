#!/usr/bin/env python3
"""Инвайт-коды для закрытого клуба.

    python scripts/invite.py --count 15 --note "друзья"
    python scripts/invite.py --list

Код одноразовый: сгорает в момент регистрации.
"""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import InviteCode, User  # noqa: E402

# без похожих символов: нет 0/O, 1/I/L
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def make_code() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--note", default="")
    parser.add_argument("--list", action="store_true", help="показать неиспользованные")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()

    if args.list:
        rows = db.scalars(select(InviteCode).where(InviteCode.used_by.is_(None))).all()
        if not rows:
            print("свободных кодов нет")
        for row in rows:
            print(f"{row.code}  {row.note}")
        used = db.scalar(select(InviteCode).where(InviteCode.used_by.is_not(None)))
        if used:
            user = db.get(User, used.used_by) if used.used_by else None
            print(f"\nпример использованного: {used.code} -> {user.email if user else '?'}")
        return 0

    created = []
    for _ in range(max(1, args.count)):
        while True:
            code = make_code()
            if db.get(InviteCode, code) is None:
                break
        db.add(InviteCode(code=code, note=args.note[:64]))
        created.append(code)
    db.commit()
    db.close()

    print(f"создано {len(created)} кодов:\n")
    for code in created:
        print(f"  {code}")
    print("\nотдай по одному другу — повторно тот же код не сработает")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
