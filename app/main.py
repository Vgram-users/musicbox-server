from contextlib import asynccontextmanager
import secrets

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from . import __version__
from .config import settings
from .db import SessionLocal, init_db
from .models import InviteCode
from .routers import auth, extras, playlists, radio, system, tracks

_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _ensure_invites() -> None:
    """На свежей БД сразу создаём коды для друзей."""
    db = SessionLocal()
    try:
        used = db.scalar(
            select(func.count()).select_from(InviteCode).where(InviteCode.used_by.is_not(None))
        ) or 0
        free = db.scalar(
            select(func.count()).select_from(InviteCode).where(InviteCode.used_by.is_(None))
        ) or 0
        need = max(0, 15 - free)
        if need == 0:
            return
        for _ in range(need):
            raw = "".join(secrets.choice(_ALPHABET) for _ in range(8))
            db.add(InviteCode(code=f"{raw[:4]}-{raw[4:]}", note="авто"))
        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _ensure_invites()
    yield


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length", "ETag"],
)

for router in (system.router, auth.router, tracks.router, playlists.router, radio.router, extras.router):
    app.include_router(router, prefix=settings.api_prefix)


@app.get("/", include_in_schema=False)
def root() -> dict:
    return {"name": settings.app_name, "version": __version__, "docs": "/docs"}
