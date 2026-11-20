from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import PurePosixPath
from urllib.request import Request

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, status
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from .. import sources
from ..config import settings
from ..db import get_db
from ..http_range import parse_range
from ..models import History, Like, Track, User
from ..schemas import AddByUrl, SearchResult, TrackList, TrackOut, TrackUpdate
from ..security import get_current_user, get_current_user_optional
from ..storage import storage

router = APIRouter(prefix="/tracks", tags=["tracks"])

REMOTE_PREFIX = "remote:"
CHUNK = 64 * 1024

_AUDIO_EXT = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
    ".wav": "audio/wav",
}
_IMAGE_EXT = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def _to_out(track: Track) -> TrackOut:
    out = TrackOut.model_validate(track)
    out.has_cover = bool(track.cover_key)
    out.stream_url = f"{settings.api_prefix}/tracks/{track.id}/stream"
    return out


def _ext(name: str | None, allowed: dict[str, str], fallback: str) -> str:
    ext = PurePosixPath(name or "").suffix.lower()
    return ext if ext in allowed else fallback


@router.get("", response_model=TrackList)
def list_tracks(
    q: str | None = None,
    artist: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> TrackList:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    conds = [or_(Track.is_public.is_(True), Track.owner_id == user.id)] if user else [Track.is_public.is_(True)]
    if q:
        pattern = f"%{q.strip()}%"
        conds.append(or_(Track.title.ilike(pattern), Track.artist.ilike(pattern), Track.album.ilike(pattern)))
    if artist:
        conds.append(Track.artist.ilike(f"%{artist.strip()}%"))

    total = db.scalar(select(func.count()).select_from(Track).where(*conds)) or 0
    rows = db.scalars(
        select(Track).where(*conds).order_by(Track.created_at.desc()).limit(limit).offset(offset)
    ).all()

    return TrackList(items=[_to_out(t) for t in rows], total=total, limit=limit, offset=offset)


@router.get("/history", response_model=list[TrackOut])
def history_tracks(
    db: Session = Depends(get_db), user: User | None = Depends(get_current_user_optional)
) -> list[TrackOut]:
    if user is None:
        return []
    ids = db.scalars(
        select(History.track_id)
        .where(History.user_id == user.id)
        .order_by(History.played_at.desc())
        .limit(50)
    ).all()
    rows = [db.get(Track, track_id) for track_id in ids]
    return [_to_out(t) for t in rows if t is not None]


@router.get("/liked", response_model=list[TrackOut])
def liked_tracks(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[TrackOut]:
    rows = db.scalars(
        select(Track).join(Like, Like.track_id == Track.id).where(Like.user_id == user.id)
    ).all()
    return [_to_out(t) for t in rows]


@router.get("/search", response_model=SearchResult)
def search_online(
    q: str,
    source: str = "youtube",
    limit: int = 10,
    user: User = Depends(get_current_user),
) -> SearchResult:
    """Поиск по площадкам. Треки не сохраняются — только выдача результатов."""
    if not q.strip():
        return SearchResult(items=[])
    try:
        items = sources.search(q.strip(), source, limit)
    except Exception:
        items = []
    # если выбранная площадка недоступна/пуста — не показываем пустой экран
    if not items and source != "soundcloud":
        try:
            items = sources.search(q.strip(), "soundcloud", limit)
        except Exception:
            items = []
    return SearchResult(items=items)


@router.post("", response_model=TrackOut, status_code=status.HTTP_201_CREATED)
async def upload_track(
    file: UploadFile = File(...),
    title: str = Form(""),
    artist: str = Form(""),
    album: str = Form(""),
    cover: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TrackOut:
    ext = _ext(file.filename, _AUDIO_EXT, ".mp3")
    mime = _AUDIO_EXT.get(ext, "audio/mpeg")

    storage_key = f"tracks/{uuid.uuid4().hex}{ext}"
    size = storage.save(storage_key, file.file)

    if size > settings.max_upload_mb * 1024 * 1024:
        storage.delete(storage_key)
        raise HTTPException(status_code=413, detail=f"File larger than {settings.max_upload_mb} MB")
    if size == 0:
        storage.delete(storage_key)
        raise HTTPException(status_code=400, detail="Empty file")

    cover_key = None
    if cover is not None and cover.filename:
        cover_ext = _ext(cover.filename, _IMAGE_EXT, ".jpg")
        cover_key = f"covers/{uuid.uuid4().hex}{cover_ext}"
        storage.save(cover_key, cover.file)

    name = (title or file.filename or "Untitled").rsplit(".", 1)[0]
    track = Track(
        title=name.strip()[:255],
        artist=artist.strip()[:255],
        album=album.strip()[:255],
        size_bytes=size,
        mime_type=mime,
        storage_key=storage_key,
        cover_key=cover_key,
        owner_id=user.id,
    )
    db.add(track)
    db.commit()
    db.refresh(track)
    return _to_out(track)


@router.post("/from-url", response_model=TrackOut, status_code=status.HTTP_201_CREATED)
def add_from_url(
    payload: AddByUrl,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TrackOut:
    """Добавить трек ссылкой с площадки. Файл не скачивается — хранится только источник."""
    url = payload.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="Пустая ссылка")

    try:
        resolved = sources.resolve(url)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Не удалось открыть ссылку: {exc}") from exc

    track = Track(
        title=resolved.title[:255],
        artist=resolved.artist[:255],
        duration_sec=resolved.duration,
        size_bytes=0,  # у удалённого потока неизвестен
        mime_type=resolved.mime_type,
        storage_key=REMOTE_PREFIX + resolved.webpage_url,
        cover_key=("url:" + resolved.thumbnail) if resolved.thumbnail else None,
        owner_id=user.id,
    )
    db.add(track)
    db.commit()
    db.refresh(track)
    return _to_out(track)


def _stream_remote(track: Track):
    """Прокси удалённого потока: ExoPlayer получает аудио с нашего сервера."""
    try:
        resolved = sources.resolve(track.storage_key[len(REMOTE_PREFIX) :])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Источник недоступен: {exc}") from exc

    source_url = track.storage_key[len(REMOTE_PREFIX) :]

    def chunks():
        current = resolved
        for attempt in range(2):
            try:
                request = Request(current.url, headers=current.headers)
                with sources.open_remote(request, 60) as upstream:
                    while True:
                        data = upstream.read(CHUNK)
                        if not data:
                            return
                        yield data
                return
            except Exception:
                if attempt == 0:
                    try:
                        current = sources.resolve(source_url, force=True)
                    except Exception:
                        return
                else:
                    return

    return StreamingResponse(
        chunks(),
        media_type=track.mime_type,
        headers={"Accept-Ranges": "none", "Cache-Control": "no-store"},
    )


@router.get("/{track_id}", response_model=TrackOut)
def get_track(
    track_id: str,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> TrackOut:
    track = db.get(Track, track_id)
    if track is None or (not track.is_public and (user is None or track.owner_id != user.id)):
        raise HTTPException(status_code=404, detail="Track not found")
    return _to_out(track)


@router.patch("/{track_id}", response_model=TrackOut)
def update_track(
    track_id: str,
    payload: TrackUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TrackOut:
    track = db.get(Track, track_id)
    if track is None or track.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Track not found")

    for field in ("title", "artist", "album"):
        value = getattr(payload, field)
        if value is not None:
            setattr(track, field, value.strip())
    db.commit()
    db.refresh(track)
    return _to_out(track)


@router.delete("/{track_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_track(
    track_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> Response:
    track = db.get(Track, track_id)
    if track is None or track.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Track not found")

    storage.delete(track.storage_key)
    if track.cover_key:
        storage.delete(track.cover_key)
    db.delete(track)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{track_id}/play", status_code=status.HTTP_204_NO_CONTENT)
def register_play(
    track_id: str,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> Response:
    db.execute(update(Track).where(Track.id == track_id).values(play_count=Track.play_count + 1))
    if user is not None:
        last = db.scalar(
            select(History)
            .where(History.user_id == user.id, History.track_id == track_id)
            .order_by(History.played_at.desc())
            .limit(1)
        )
        if last is not None:
            played_at = last.played_at
            if played_at.tzinfo is None:
                played_at = played_at.replace(tzinfo=timezone.utc)
            fresh = (datetime.now(timezone.utc) - played_at).total_seconds() > 30
        else:
            fresh = True
        if fresh:
            db.add(History(user_id=user.id, track_id=track_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{track_id}/like", status_code=status.HTTP_204_NO_CONTENT)
def like_track(track_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Response:
    if db.get(Track, track_id) is None:
        raise HTTPException(status_code=404, detail="Track not found")
    existing = db.scalar(select(Like).where(Like.user_id == user.id, Like.track_id == track_id))
    if existing is None:
        db.add(Like(user_id=user.id, track_id=track_id))
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{track_id}/like", status_code=status.HTTP_204_NO_CONTENT)
def unlike_track(track_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Response:
    db.execute(delete(Like).where(Like.user_id == user.id, Like.track_id == track_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{track_id}/stream")
def stream_track(
    track_id: str,
    range_header: str | None = Header(default=None, alias="Range"),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    track = db.get(Track, track_id)
    if track is None or (not track.is_public and (user is None or track.owner_id != user.id)):
        raise HTTPException(status_code=404, detail="Track not found")

    if track.storage_key.startswith(REMOTE_PREFIX):
        return _stream_remote(track)

    size = track.size_bytes
    if size <= 0:
        raise HTTPException(status_code=409, detail="Track file is missing")

    base_headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": track.mime_type,
        "Cache-Control": "public, max-age=86400",
        "ETag": f'"{track.id}-{size}"',
    }

    rng = parse_range(range_header, size)
    if range_header and rng is None:
        return Response(
            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            headers={**base_headers, "Content-Range": f"bytes */{size}"},
        )

    if rng is None:
        start, end, code = 0, size - 1, status.HTTP_200_OK
    else:
        start, end = rng
        code = status.HTTP_206_PARTIAL_CONTENT
        base_headers["Content-Range"] = f"bytes {start}-{end}/{size}"

    length = end - start + 1
    base_headers["Content-Length"] = str(length)

    return StreamingResponse(
        storage.open_range(track.storage_key, start, length),
        status_code=code,
        headers=base_headers,
        media_type=track.mime_type,
    )


@router.get("/{track_id}/cover")
def get_cover(track_id: str, db: Session = Depends(get_db)):
    track = db.get(Track, track_id)
    if track is None or not track.cover_key:
        raise HTTPException(status_code=404, detail="Cover not found")

    if track.cover_key.startswith("url:"):
        return RedirectResponse(track.cover_key[4:])

    ext = PurePosixPath(track.cover_key).suffix.lower()
    media_type = _IMAGE_EXT.get(ext, "image/jpeg")
    return StreamingResponse(
        storage.open_range(track.cover_key, 0, 5 * 1024 * 1024),
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=604800"},
    )
