"""Bounded gzip compression/decompression used before/after AES-GCM."""
from __future__ import annotations

import gzip
from io import BytesIO

MAX_PLAINTEXT_BYTES = 256 * 1024 * 1024


def compress_gzip(data: bytes) -> bytes:
    return gzip.compress(data, compresslevel=6, mtime=0)


def decompress_gzip_bounded(data: bytes, limit: int = MAX_PLAINTEXT_BYTES) -> bytes:
    with gzip.GzipFile(fileobj=BytesIO(data), mode="rb") as stream:
        output = stream.read(limit + 1)
        if len(output) > limit or stream.read(1):
            raise ValueError("BACKUP_DECOMPRESSED_SIZE_LIMIT")
        return output
