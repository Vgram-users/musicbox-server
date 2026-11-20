"""Разбор заголовка Range — сердце стриминга."""

from __future__ import annotations


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Возвращает (start, end) включительно или None, если диапазон невалиден.

    Поддерживаются формы: bytes=0-1023, bytes=1024-, bytes=-500.
    Мультидиапазоны не поддерживаем — берём первый, клиенты этого хватает.
    """
    if not header or size <= 0 or not header.startswith("bytes="):
        return None

    spec = header[6:].split(",")[0].strip()
    if "-" not in spec:
        return None

    start_s, end_s = spec.split("-", 1)
    try:
        if start_s == "":
            suffix = int(end_s or "0")
            if suffix <= 0:
                return None
            start = max(0, size - suffix)
            end = size - 1
        else:
            start = int(start_s)
            end = int(end_s) if end_s else size - 1
    except ValueError:
        return None

    if start < 0 or start >= size or start > end:
        return None

    return start, min(end, size - 1)
