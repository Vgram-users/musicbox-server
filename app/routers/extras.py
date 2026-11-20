"""Дополнительные фишки: тексты песен и подсказки поиска."""

from __future__ import annotations

import time

import requests
from fastapi import APIRouter, HTTPException, Query

from ..sources import _requests_proxies

router = APIRouter(prefix="/extras", tags=["extras"])

_CACHE: dict[tuple, tuple[dict, float]] = {}
_TTL = 60 * 60 * 24
_HEADERS = {"User-Agent": "MusicBox/0.2 (lyrics)"}


@router.get("/stats")
def stats() -> dict:
    from sqlalchemy import func, select

    from ..db import SessionLocal
    from ..models import History, Like, Playlist, Track

    db = SessionLocal()
    try:
        return {
            "tracks": db.scalar(select(func.count()).select_from(Track)) or 0,
            "plays": db.scalar(select(func.coalesce(func.sum(Track.play_count), 0))) or 0,
            "likes": db.scalar(select(func.count()).select_from(Like)) or 0,
            "history": db.scalar(select(func.count()).select_from(History)) or 0,
            "playlists": db.scalar(select(func.count()).select_from(Playlist)) or 0,
        }
    finally:
        db.close()


@router.get("/lyrics")
def lyrics(title: str = Query(..., min_length=1), artist: str = "") -> dict:
    key = (title.strip().lower(), artist.strip().lower())
    cached = _CACHE.get(key)
    if cached and time.time() - cached[1] < _TTL:
        return cached[0]

    params: dict[str, str] = {"track_name": title.strip()}
    if artist.strip():
        params["artist_name"] = artist.strip()

    try:
        response = requests.get(
            "https://lrclib.net/api/search",
            params=params,
            headers=_HEADERS,
            proxies=_requests_proxies(),
            timeout=10,
        )
        response.raise_for_status()
        rows = response.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Тексты недоступны: {exc}") from exc

    chosen = None
    for row in rows:
        if row.get("syncedLyrics") or row.get("plainLyrics"):
            chosen = row
            break

    result = {
        "title": (chosen or {}).get("trackName", title),
        "artist": (chosen or {}).get("artistName", artist),
        "synced": (chosen or {}).get("syncedLyrics") or "",
        "plain": (chosen or {}).get("plainLyrics") or "",
    }
    _CACHE[key] = (result, time.time())
    return result


@router.get("/suggest")
def suggest(q: str = Query(..., min_length=2), limit: int = 6) -> dict:
    """Быстрые подсказки через подсказки YouTube."""
    try:
        response = requests.get(
            "https://suggestqueries.google.com/complete/search",
            params={"client": "firefox", "q": q, "hl": "ru"},
            proxies=_requests_proxies(),
            timeout=8,
        )
        response.raise_for_status()
        suggestions = response.json()[1][:limit]
    except Exception:
        suggestions = []
    return {"items": [str(s) for s in suggestions]}
