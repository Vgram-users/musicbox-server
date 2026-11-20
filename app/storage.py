"""Абстракция хранилища: локальный диск (dev) и S3/R2 (prod).

Ключевой метод — open_range(): отдаёт ровно кусок файла под HTTP Range.
Без него перемотка в плеере не работает.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

from .config import settings

CHUNK = 64 * 1024


class Storage:
    def save(self, key: str, fileobj: BinaryIO) -> int:  # -> размер в байтах
        raise NotImplementedError

    def open_range(self, key: str, start: int, length: int) -> Iterator[bytes]:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError


class LocalStorage(Storage):
    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not str(path).startswith(str(self.root)):
            raise ValueError("path traversal")
        return path

    def save(self, key: str, fileobj: BinaryIO) -> int:
        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as out:
            shutil.copyfileobj(fileobj, out, CHUNK)
        return dest.stat().st_size

    def open_range(self, key: str, start: int, length: int) -> Iterator[bytes]:
        path = self._path(key)
        with path.open("rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                chunk = fh.read(min(CHUNK, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink()
        except FileNotFoundError:
            pass


class S3Storage(Storage):
    """Cloudflare R2 или любой S3. boto3 импортируется лениво."""

    def __init__(self) -> None:
        import boto3

        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
        )

    def save(self, key: str, fileobj: BinaryIO) -> int:
        fileobj.seek(0, 2)
        size = fileobj.tell()
        fileobj.seek(0)
        self.client.upload_fileobj(fileobj, self.bucket, key)
        return size

    def open_range(self, key: str, start: int, length: int) -> Iterator[bytes]:
        end = start + length - 1
        obj = self.client.get_object(Bucket=self.bucket, Key=key, Range=f"bytes={start}-{end}")
        yield from obj["Body"].iter_chunks(CHUNK)
        obj["Body"].close()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


def _build() -> Storage:
    if settings.storage_backend == "s3":
        return S3Storage()
    return LocalStorage(settings.media_dir)


storage: Storage = _build()
