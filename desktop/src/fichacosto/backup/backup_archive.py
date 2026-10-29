"""Strict ZIP container primitives. Entries are stored, never ZIP-compressed."""
from __future__ import annotations

import os
import stat
import zipfile
from io import BytesIO
from pathlib import Path

ROOT = "ficha148_backup_v1"
MANIFEST_ENTRY = f"{ROOT}/manifest.json"
PAYLOAD_ENTRY = f"{ROOT}/payload.enc"
MAX_ARCHIVE_BYTES = 160 * 1024 * 1024
MAX_MANIFEST_BYTES = 32 * 1024
MAX_ENCRYPTED_PAYLOAD_BYTES = 128 * 1024 * 1024


class ArchiveFormatError(ValueError):
    pass


def build_zip(manifest: bytes, ciphertext: bytes) -> bytes:
    if len(manifest) > MAX_MANIFEST_BYTES or len(ciphertext) > MAX_ENCRYPTED_PAYLOAD_BYTES:
        raise ArchiveFormatError("El respaldo supera el tamaño máximo permitido.")
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
        archive.writestr(MANIFEST_ENTRY, manifest, compress_type=zipfile.ZIP_STORED)
        archive.writestr(PAYLOAD_ENTRY, ciphertext, compress_type=zipfile.ZIP_STORED)
    result = buffer.getvalue()
    if len(result) > MAX_ARCHIVE_BYTES:
        raise ArchiveFormatError("El respaldo supera el tamaño máximo del archivo ZIP.")
    return result


def read_zip(path: Path) -> tuple[bytes, bytes]:
    try:
        if path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise ArchiveFormatError("El archivo de respaldo supera el tamaño permitido.")
        raw = path.read_bytes()
        if len(raw) > MAX_ARCHIVE_BYTES:
            raise ArchiveFormatError("El archivo de respaldo supera el tamaño permitido.")
        with zipfile.ZipFile(BytesIO(raw), "r") as archive:
            infos = archive.infolist()
            expected = {MANIFEST_ENTRY, PAYLOAD_ENTRY}
            names = [info.filename for info in infos]
            if len(infos) != 2 or len(names) != len(set(names)) or set(names) != expected:
                raise ArchiveFormatError("El ZIP no contiene exactamente los miembros requeridos del respaldo v1.")
            values = {}
            for info in infos:
                _check_name(info.filename)
                if info.is_dir() or info.compress_type != zipfile.ZIP_STORED or info.flag_bits & 1:
                    raise ArchiveFormatError("El ZIP contiene una entrada no admitida.")
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(mode):
                    raise ArchiveFormatError("El ZIP contiene enlaces no admitidos.")
                limit = MAX_MANIFEST_BYTES if info.filename == MANIFEST_ENTRY else MAX_ENCRYPTED_PAYLOAD_BYTES
                if info.file_size < 0 or info.file_size > limit or info.compress_size != info.file_size:
                    raise ArchiveFormatError("El ZIP contiene una entrada de tamaño no válido.")
                values[info.filename] = _read_member_bounded(archive, info, limit)
            return values[MANIFEST_ENTRY], values[PAYLOAD_ENTRY]
    except ArchiveFormatError:
        raise
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile, EOFError, RuntimeError, ValueError) as exc:
        raise ArchiveFormatError("El archivo no es un respaldo ZIP válido o está dañado.") from exc


def _read_member_bounded(archive: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes:
    chunks = []
    total = 0
    with archive.open(info, "r") as stream:
        while True:
            chunk = stream.read(min(64 * 1024, limit + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise ArchiveFormatError("Una entrada ZIP excede el tamaño permitido.")
            chunks.append(chunk)
    if total != info.file_size:
        raise ArchiveFormatError("El tamaño declarado de una entrada ZIP no coincide.")
    return b"".join(chunks)


def _check_name(name: str) -> None:
    parts = name.split("/")
    if (not name or name.startswith("/") or "\\" in name or ":" in name
            or any(part in ("", ".", "..") for part in parts)):
        raise ArchiveFormatError("El ZIP contiene una ruta no segura.")
