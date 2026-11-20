"""Прямое воспроизведение из результатов поиска.

Трек не добавляется в библиотеку и не скачивается: по ссылке площадки
сразу открывается поток, который уходит в ExoPlayer по частям.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request

from fastapi import APIRouter, HTTPException, Query
from fastapi import Request as FastAPIRequest
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .. import sources

router = APIRouter(prefix="/radio", tags=["radio"])

CHUNK = 64 * 1024
_pool = ThreadPoolExecutor(max_workers=4)


class PrefetchIn(BaseModel):
    urls: list[str]


def _warm(urls: list[str]) -> None:
    import time as _time

    for url in urls[:8]:
        try:
            sources.resolve(url)
        except Exception:
            pass
        _time.sleep(0.15)


@router.get("/stream")
def radio_stream(
    url: str = Query(..., min_length=8),
    quality: str = Query("high", pattern="^(low|high)$"),
    request: FastAPIRequest = None,
):
    """Прокси потока с поддержкой Range: плеер стартует быстрее и может перематывать."""
    try:
        resolved = sources.resolve(url, quality=quality)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Источник недоступен: {exc}") from exc

    range_header = request.headers.get("range") if request is not None else None
    upstream_headers = dict(resolved.headers)
    if range_header:
        upstream_headers["Range"] = range_header

    try:
        upstream = sources.open_remote(Request(resolved.url, headers=upstream_headers), 30)
    except Exception:
        try:
            resolved = sources.resolve(url, quality=quality, force=True)
            upstream = sources.open_remote(Request(resolved.url, headers=upstream_headers), 30)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Поток недоступен: {exc}") from exc

    status = 200
    response_headers = {"Cache-Control": "no-store", "Accept-Ranges": "bytes"}
    content_length = upstream.headers.get("Content-Length")
    content_range = upstream.headers.get("Content-Range")
    if content_range:
        status = 206
        response_headers["Content-Range"] = content_range
    if content_length:
        response_headers["Content-Length"] = content_length

    def chunks():
        try:
            while True:
                data = upstream.read(CHUNK)
                if not data:
                    break
                yield data
        finally:
            upstream.close()

    return StreamingResponse(
        chunks(),
        status_code=status,
        media_type=resolved.mime_type,
        headers=response_headers,
    )


_MOODS = {
    "Обычная": "lofi chill hip hop beats",
    "Спокойная": "calm ambient piano relaxing",
    "Сон": "sleep deep relaxing ambient music",
    "Радостная": "happy upbeat indie pop summer",
    "Дорога": "dancing electronic synthwave drive",
}


@router.get("/wave")
def wave(mood: str = "Обычная", limit: int = 20) -> dict:
    """«Моя волна» — очеред из треков под настроение."""
    query = _MOODS.get(mood, _MOODS["Обычная"])
    try:
        items = sources.search(query, "youtube", min(limit, 20))
    except Exception:
        items = []
    if not items:
        try:
            items = sources.search(query, "soundcloud", min(limit, 20))
        except Exception:
            items = []
    return {"items": items, "mood": mood}


@router.post("/prefetch")
def prefetch(payload: PrefetchIn) -> dict:
    """Подогреть кэш ссылок, пока пользователь смотрит результаты поиска."""
    urls = [u for u in payload.urls if u][:20]
    if urls:
        _pool.submit(_warm, urls)
    return {"queued": len(urls)}
