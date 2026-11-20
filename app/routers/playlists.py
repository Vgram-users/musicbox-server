from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Playlist, PlaylistItem, Track, User
from ..schemas import PlaylistAddTrack, PlaylistCreate, PlaylistDetail, PlaylistOut
from ..security import get_current_user, get_current_user_optional
from .tracks import _to_out as track_out

router = APIRouter(prefix="/playlists", tags=["playlists"])


def _to_out(playlist: Playlist, track_count: int) -> PlaylistOut:
    return PlaylistOut(
        id=playlist.id,
        name=playlist.name,
        description=playlist.description,
        is_public=playlist.is_public,
        share_slug=playlist.share_slug,
        owner_id=playlist.owner_id,
        created_at=playlist.created_at,
        track_count=track_count,
    )


@router.get("", response_model=list[PlaylistOut])
def list_playlists(
    db: Session = Depends(get_db), user: User | None = Depends(get_current_user_optional)
) -> list[PlaylistOut]:
    counts = (
        select(PlaylistItem.playlist_id, func.count().label("n")).group_by(PlaylistItem.playlist_id).subquery()
    )
    stmt = select(Playlist, func.coalesce(counts.c.n, 0)).outerjoin(counts, counts.c.playlist_id == Playlist.id)
    if user:
        stmt = stmt.where((Playlist.is_public.is_(True)) | (Playlist.owner_id == user.id))
    else:
        stmt = stmt.where(Playlist.is_public.is_(True))

    rows = db.execute(stmt.order_by(Playlist.created_at.desc())).all()
    return [_to_out(p, n) for p, n in rows]


@router.post("", response_model=PlaylistOut, status_code=status.HTTP_201_CREATED)
def create_playlist(
    payload: PlaylistCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> PlaylistOut:
    playlist = Playlist(
        name=payload.name.strip(),
        description=payload.description.strip(),
        is_public=payload.is_public,
        owner_id=user.id,
    )
    db.add(playlist)
    db.commit()
    db.refresh(playlist)
    return _to_out(playlist, 0)


@router.get("/by-slug/{slug}", response_model=PlaylistDetail)
def get_playlist_by_slug(
    slug: str,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> PlaylistDetail:
    playlist = db.scalar(select(Playlist).where(Playlist.share_slug == slug))
    if playlist is None or (not playlist.is_public and (user is None or playlist.owner_id != user.id)):
        raise HTTPException(status_code=404, detail="Playlist not found")

    tracks = [track_out(item.track) for item in playlist.items if item.track is not None]
    base = _to_out(playlist, len(tracks))
    return PlaylistDetail(**base.model_dump(), tracks=tracks)


@router.get("/{playlist_id}", response_model=PlaylistDetail)
def get_playlist(
    playlist_id: str,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> PlaylistDetail:
    playlist = db.get(Playlist, playlist_id)
    if playlist is None or (not playlist.is_public and (user is None or playlist.owner_id != user.id)):
        raise HTTPException(status_code=404, detail="Playlist not found")

    tracks = [track_out(item.track) for item in playlist.items if item.track is not None]
    base = _to_out(playlist, len(tracks))
    return PlaylistDetail(**base.model_dump(), tracks=tracks)


@router.delete("/{playlist_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_playlist(
    playlist_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> Response:
    playlist = db.get(Playlist, playlist_id)
    if playlist is None or playlist.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Playlist not found")
    db.delete(playlist)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{playlist_id}/tracks", status_code=status.HTTP_204_NO_CONTENT)
def add_track(
    playlist_id: str,
    payload: PlaylistAddTrack,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    playlist = db.get(Playlist, playlist_id)
    if playlist is None or playlist.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Playlist not found")
    if db.get(Track, payload.track_id) is None:
        raise HTTPException(status_code=404, detail="Track not found")

    exists = db.scalar(
        select(PlaylistItem).where(
            PlaylistItem.playlist_id == playlist_id, PlaylistItem.track_id == payload.track_id
        )
    )
    if exists is None:
        position = db.scalar(
            select(func.coalesce(func.max(PlaylistItem.position), -1) + 1).where(
                PlaylistItem.playlist_id == playlist_id
            )
        )
        db.add(PlaylistItem(playlist_id=playlist_id, track_id=payload.track_id, position=position or 0))
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{playlist_id}/tracks/{track_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_track(
    playlist_id: str,
    track_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    playlist = db.get(Playlist, playlist_id)
    if playlist is None or playlist.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Playlist not found")

    item = db.scalar(
        select(PlaylistItem).where(
            PlaylistItem.playlist_id == playlist_id, PlaylistItem.track_id == track_id
        )
    )
    if item is not None:
        db.delete(item)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
