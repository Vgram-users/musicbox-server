"""Онлайн-источники: поиск и получение прямого аудиопотока через yt-dlp.

Ничего не скачивается на сервер — в базе хранится только ссылка на площадку,
а при воспроизведении поток проксируется через наш /stream.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from urllib.parse import quote

import yt_dlp

_CACHE: dict[str, tuple["Resolved", float]] = {}
_TTL = 30 * 60  # прямые ссылки живут дольше; при отказе — stale-fallback
_STALE_TTL = 24 * 60 * 60  # старую ссылку лучше попробовать, чем ждать обновления

_EXT_MIME = {
    "m4a": "audio/mp4",
    "mp3": "audio/mpeg",
    "opus": "audio/opus",
    "webm": "audio/webm",
    "ogg": "audio/ogg",
    "wav": "audio/wav",
    "flac": "audio/flac",
}


@dataclass
class Resolved:
    url: str
    headers: dict[str, str]
    title: str
    artist: str
    duration: int | None
    mime_type: str
    thumbnail: str | None
    webpage_url: str
    source: str = ""
    extra: dict = field(default_factory=dict)


def _proxy() -> str | None:
    from .config import settings

    return settings.proxy_url.strip() or None


def _requests_proxies() -> dict[str, str]:
    proxy = _proxy()
    return {"http": proxy, "https": proxy} if proxy else {}


def open_remote(request, timeout: int = 60):
    """urlopen с учётом upstream-прокси."""
    import urllib.request

    proxy = _proxy()
    if not proxy:
        return urllib.request.urlopen(request, timeout=timeout)
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    )
    return opener.open(request, timeout=timeout)


def _opts(flat: bool = False) -> dict:
    proxy = _proxy()
    return {
        "proxy": proxy,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "no_check_certificate": True,
        "retries": 2,
        "extract_flat": "in_playlist" if flat else False,
        "ignoreerrors": True,
    }


def _source_of(url: str) -> str:
    u = url.lower()
    if "youtube.com" in u or "youtu.be" in u:
        return "YouTube"
    if "soundcloud.com" in u:
        return "SoundCloud"
    if "vk.com" in u:
        return "VK"
    if "bandcamp.com" in u:
        return "Bandcamp"
    return "Сеть"


def _pick_format(info: dict, quality: str = "high") -> dict:
    candidates = []
    for fmt in info.get("formats") or []:
        if not fmt.get("url"):
            continue
        if fmt.get("acodec") in (None, "none", False):
            continue
        # без видео, с нормальным звуком; m4a/mp3 надёжнее для ExoPlayer, чем opus/webm
        ext = (fmt.get("ext") or "").lower()
        bonus = 60 if ext in ("m4a", "mp3") else 0
        if quality == "low":
            # экономим трафик: низкий битрейт важнее формата
            score = -(fmt.get("tbr") or 0) + bonus
        else:
            score = (0 if fmt.get("vcodec") in (None, "none") else 100) + (fmt.get("tbr") or 0) + bonus
        candidates.append((score, fmt))
    if candidates:
        return max(candidates, key=lambda x: x[0])[1]
    return info


def _db_key(url: str, quality: str) -> str:
    return f"{url}|{quality}"


def _from_db(url: str, quality: str, max_age: float = _STALE_TTL) -> Resolved | None:
    try:
        import json

        from .db import SessionLocal
        from .models import ResolveCache

        db = SessionLocal()
        try:
            row = db.get(ResolveCache, _db_key(url, quality))
            if row is None or time.time() - row.fetched_at > max_age:
                return None
            return Resolved(
                url=row.direct_url,
                headers=json.loads(row.headers_json or "{}"),
                title="",
                artist="",
                duration=None,
                mime_type=row.mime,
                thumbnail=None,
                webpage_url=url,
                source=_source_of(url),
            )
        finally:
            db.close()
    except Exception:
        return None


def _to_db(url: str, quality: str, resolved: "Resolved") -> None:
    try:
        import json

        from .db import SessionLocal
        from .models import ResolveCache

        db = SessionLocal()
        try:
            key = _db_key(url, quality)
            row = db.get(ResolveCache, key)
            if row is None:
                row = ResolveCache(key=key)
                db.add(row)
            row.direct_url = resolved.url
            row.headers_json = json.dumps(resolved.headers)
            row.mime = resolved.mime_type
            row.fetched_at = time.time()
            db.commit()
        finally:
            db.close()
    except Exception:
        pass


def resolve(url: str, force: bool = False, quality: str = "high") -> Resolved:
    cache_key = (url, quality)
    if not force:
        cached = _CACHE.get(cache_key)
        if cached and time.time() - cached[1] < _TTL:
            return cached[0]

    # постоянный кэш: отдельный запрос к площадке не нужен даже после рестарта
    if not force:
        fresh = _from_db(url, quality, max_age=_TTL)
        if fresh is not None:
            _CACHE[cache_key] = (fresh, time.time())
            return fresh

    import time as _time

    info = None
    for attempt in range(3):
        try:
            with yt_dlp.YoutubeDL(_opts()) as ydl:
                info = ydl.extract_info(url, download=False)
            if info:
                break
        except Exception:
            if attempt == 2:
                stale = _from_db(url, quality)
                if stale is not None:
                    _CACHE[cache_key] = (stale, time.time())
                    return stale
                raise
            _time.sleep(1 + attempt)

    if not info:
        raise ValueError("Площадка не отдала данные по ссылке")

    fmt = _pick_format(info, quality)
    direct = fmt.get("url") or info.get("url")
    if not direct:
        raise ValueError("Не удалось получить прямой аудиопоток")

    ext = (fmt.get("ext") or info.get("ext") or "m4a").lower()
    result = Resolved(
        url=direct,
        headers=dict(fmt.get("http_headers") or info.get("http_headers") or {}),
        title=str(info.get("title") or "Без названия"),
        artist=str(info.get("uploader") or info.get("artist") or info.get("channel") or ""),
        duration=int(info["duration"]) if info.get("duration") else None,
        mime_type=_EXT_MIME.get(ext, "audio/mpeg"),
        thumbnail=info.get("thumbnail"),
        webpage_url=info.get("webpage_url") or url,
        source=_source_of(url),
        extra={"id": info.get("id"), "ext": ext},
    )
    _CACHE[cache_key] = (result, time.time())
    _to_db(url, quality, result)
    return result


_SEARCH_CACHE: dict[tuple, tuple[list[dict], float]] = {}
_SEARCH_TTL = 10 * 60

_YT_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
_YT_VERSION = "2.20250101.00.00"


def _parse_duration(text: str | None) -> int | None:
    if not text:
        return None
    try:
        total = 0
        for part in str(text).split(":"):
            total = total * 60 + int(part)
        return total
    except ValueError:
        return None


def _youtube_fast(query: str, limit: int) -> list[dict]:
    """Search через InnerTube — без JS-челленджей, в разы быстрее yt-dlp."""
    import requests

    response = requests.post(
        f"https://www.youtube.com/youtubei/v1/search?key={_YT_KEY}",
        proxies=_requests_proxies(),
        json={
            "context": {
                "client": {
                    "clientName": "WEB",
                    "clientVersion": _YT_VERSION,
                    "hl": "ru",
                    "gl": "RU",
                }
            },
            "query": query,
        },
        timeout=12,
    )
    response.raise_for_status()

    def walk(node):
        if isinstance(node, dict):
            if "videoRenderer" in node:
                yield node["videoRenderer"]
            for value in node.values():
                yield from walk(value)
        elif isinstance(node, list):
            for value in node:
                yield from walk(value)

    out: list[dict] = []
    for video in walk(response.json()):
        vid = video.get("videoId")
        if not vid:
            continue
        # без lengthText — обычно 24/7-стримы, их прямой поток нестабилен
        if not (video.get("lengthText") or {}).get("simpleText"):
            continue
        thumbs = (video.get("thumbnail") or {}).get("thumbnails") or []
        out.append(
            {
                "id": vid,
                "title": "".join(r.get("text", "") for r in (video.get("title") or {}).get("runs", [])),
                "artist": "".join(r.get("text", "") for r in (video.get("ownerText") or {}).get("runs", [])),
                "duration": _parse_duration((video.get("lengthText") or {}).get("simpleText")),
                "url": f"https://www.youtube.com/watch?v={vid}",
                "thumbnail": thumbs[-1].get("url") if thumbs else None,
                "source": "YouTube",
            }
        )
        if len(out) >= limit:
            break
    return out


def _soundcloud_fast(query: str, limit: int) -> list[dict]:
    """Прямой поиск SoundCloud API: ~2 сек вместо ~20 у yt-dlp."""
    import json
    import os

    import requests

    cache_path = os.path.join(
        os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")),
        "yt-dlp",
        "soundcloud",
        "client_id.json",
    )
    with open(cache_path, encoding="utf-8") as fh:
        client_id = json.load(fh)["data"]

    response = requests.get(
        "https://api-v2.soundcloud.com/search/tracks",
        params={"q": query, "client_id": client_id, "limit": limit, "linked_partitioning": "1"},
        proxies=_requests_proxies(),
        timeout=10,
    )
    response.raise_for_status()

    out: list[dict] = []
    for item in response.json().get("collection", [])[:limit]:
        artwork = item.get("artwork_url")
        out.append(
            {
                "id": str(item.get("id") or ""),
                "title": str(item.get("title") or "Без названия"),
                "artist": str((item.get("user") or {}).get("username") or ""),
                "duration": int(item["duration"] / 1000) if item.get("duration") else None,
                "url": item.get("permalink_url") or "",
                "thumbnail": artwork.replace("-large.", "-t500x500.") if artwork else None,
                "source": "SoundCloud",
            }
        )
    return out


def _ytdlp_search(query: str, source: str, limit: int) -> list[dict]:
    if source == "soundcloud":
        q = f"scsearch{limit}:{query}"
    elif source == "vk":
        q = f"https://vk.com/search?c%5Bq%5D={quote(query)}&c%5Bsection%5D=audio"
    elif source == "yandex":
        q = f"https://music.yandex.ru/search?text={quote(query)}"
    elif source == "deezer":
        q = f"https://www.deezer.com/search/{quote(query)}"
    elif source == "spotify":
        q = f"ytsearch{limit}:{query} spotify"
    else:
        q = f"ytsearch{limit}:{query}"

    with yt_dlp.YoutubeDL(_opts(flat=True)) as ydl:
        info = ydl.extract_info(q, download=False)

    out: list[dict] = []
    for entry in (info or {}).get("entries") or []:
        if not entry:
            continue
        out.append(
            {
                "id": str(entry.get("id") or ""),
                "title": str(entry.get("title") or "Без названия"),
                "artist": str(entry.get("channel") or entry.get("uploader") or entry.get("artist") or ""),
                "duration": int(entry["duration"]) if entry.get("duration") else None,
                "url": entry.get("url") or entry.get("webpage_url") or "",
                "thumbnail": entry.get("thumbnail"),
                "source": _source_of(str(entry.get("url") or "")),
            }
        )
    return out


def search(query: str, source: str = "youtube", limit: int = 10) -> list[dict]:
    limit = max(1, min(limit, 20))
    key = (source, query.strip().lower(), limit)
    cached = _SEARCH_CACHE.get(key)
    if cached and time.time() - cached[1] < _SEARCH_TTL:
        return cached[0]

    if source in ("youtube", "spotify"):
        try:
            items = _youtube_fast(query, limit)
        except Exception:
            try:
                items = _soundcloud_fast(query, limit)
            except Exception:
                items = _ytdlp_search(query, source, limit)
    elif source == "soundcloud":
        try:
            items = _soundcloud_fast(query, limit)
        except Exception:
            items = _ytdlp_search(query, source, limit)
    else:
        items = _ytdlp_search(query, source, limit)

    _SEARCH_CACHE[key] = (items, time.time())
    return items
