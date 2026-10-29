"""Cross-platform encrypted `.ficha148.bak` format and atomic restore for Desktop.

The ZIP uses `ficha148_backup_v1/{manifest.json,payload.enc}`. The manifest is
validated before Argon2id is run and is also AES-GCM additional authenticated data.
Only authenticated plaintext is decompressed or passed to JSON/schema validation.
"""
from __future__ import annotations

import base64
import json
import math
import os
import secrets
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft202012Validator, FormatChecker

from .backup_archive import ArchiveFormatError, MAX_ENCRYPTED_PAYLOAD_BYTES, build_zip, read_zip
from .backup_compression import MAX_PLAINTEXT_BYTES, compress_gzip, decompress_gzip_bounded
from .backup_crypto import (DEFAULT_MEMORY_KIB, ITERATIONS as KDF_ITERATIONS,
                            NONCE_BYTES, PARALLELISM as KDF_PARALLELISM, SALT_BYTES, TAG_BYTES,
                            decrypt_aes_gcm, derive_key, encrypt_aes_gcm)
from ..ficha148_validator import Ficha148Validator
from ..licensing.canonical import validate_license
from ..licensing.fingerprint import get_device_fingerprint

SCHEMA_VERSION = "1.0.0"
KDF_ALGORITHM = "argon2id"
CIPHER_ALGORITHM = "AES-256-GCM"
BACKUP_SCHEMA_DIR = Path(__file__).with_name("schemas")
INTERNAL_PREF_PREFIX = "__fichacosto_backup_"
PASSWORD_MIN_LENGTH = 8


class BackupError(ValueError):
    """Safe user-facing backup error."""


class BackupArchiveCorrupt(BackupError):
    """ZIP, manifest, compressed stream, or backup schema is invalid."""


class BackupPasswordOrDataError(BackupError):
    """AEAD failure: wrong password and ciphertext tampering are indistinguishable."""


@dataclass(frozen=True)
class BackupPreview:
    manifest: dict[str, Any]
    payload: dict[str, Any]
    fichas: int
    insumos: int
    salarios: int
    incluye_licencia: bool
    fecha_creacion: str
    fingerprint_origen: str
    fingerprint_actual: str
    origen_diferente: bool


@dataclass(frozen=True)
class RestoreResult:
    mode: Literal["replace", "merge"]
    fichas_restauradas: int
    insumos_restaurados: int
    salarios_restaurados: int
    licencia_actualizada: bool
    usage_actualizado: bool
    respaldo_seguridad: Path | None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _date_key(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
        except ValueError:
            pass
    return datetime.fromtimestamp(0, timezone.utc)


def _iso_utc(value: datetime | None = None) -> str:
    value = (value or _utc_now()).astimezone(timezone.utc)
    text = value.isoformat(timespec="microseconds")
    text = text.replace("+00:00", "Z")
    if "." in text:
        head, fraction = text[:-1].split(".", 1)
        fraction = fraction.rstrip("0")
        text = head + ("." + fraction if fraction else "") + "Z"
    return text


def validar_contrasena(password: str) -> None:
    if not isinstance(password, str) or len(password) < PASSWORD_MIN_LENGTH:
        raise BackupError("La contraseña del respaldo debe tener al menos 8 caracteres.")
    if len(password.encode("utf-8")) > 1024:
        raise BackupError("La contraseña es demasiado larga.")


def fortaleza_contrasena(password: str) -> tuple[str, int]:
    """Small local strength meter; this never sends or stores the password."""
    common = {"password", "password1", "12345678", "qwerty123", "letmein", "admin123", "fichacosto"}
    if len(password) < PASSWORD_MIN_LENGTH or password.casefold() in common:
        return "Débil", 0
    score = min(4, len(password) // 4)
    score += sum(bool(any(test(ch) for ch in password) for test in group) for group in (
        (str.islower,), (str.isupper,), (str.isdigit,), (lambda c: not c.isalnum(),)))
    score = min(score, 4)
    return ("Débil" if score < 2 else "Media" if score < 4 else "Fuerte", score)


def _strict_json(data: bytes | str) -> Any:
    def pairs_hook(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("JSON con claves duplicadas")
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=pairs_hook,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"Constante JSON inválida: {value}")))


def _normalize_payload(value: Any, *, parent_key: str = "", in_license: bool = False) -> Any:
    # Preserve the exact signed license envelope. The rest of the backup uses a shared
    # JSON numeric policy: integral floats serialize as integers; fractions stay numeric.
    if parent_key == "licenciaActual":
        in_license = True
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            normalized_key = unicodedata.normalize("NFC", str(key))
            out[normalized_key] = _normalize_payload(item, parent_key=normalized_key, in_license=in_license)
        return out
    if isinstance(value, list):
        items = [_normalize_payload(item, parent_key=parent_key, in_license=in_license) for item in value]
        if items and all(isinstance(item, dict) and isinstance(item.get("id"), str) for item in items):
            items.sort(key=lambda item: item["id"])
        return items
    if isinstance(value, str):
        if not in_license:
            value = unicodedata.normalize("NFC", value)
            if parent_key in {"fechaCreacion", "fechaActualizacion", "fechaEmision", "fechaExpiracion", "exportadoEn", "ultimoTimestamp", "lastSeenTimestamp"}:
                try:
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    return _iso_utc(parsed)
                except ValueError:
                    pass
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise BackupError("El respaldo contiene un número no finito.")
        return int(value) if value.is_integer() else value
    return value


def _json_bytes(value: Any) -> bytes:
    normalized = _normalize_payload(value)
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _validate_schema(document: Any, path: Path) -> list[str]:
    try:
        schema = _strict_json(path.read_bytes())
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        errors = sorted(validator.iter_errors(document), key=lambda e: (list(map(str, e.absolute_path)), e.message))
        return [" › ".join(map(str, error.absolute_path)) + ": " + error.message for error in errors[:30]]
    except Exception as exc:
        raise RuntimeError(f"No se pudo cargar el esquema {path.name}") from exc


def _json_pref(value: str) -> Any:
    try:
        return _strict_json(value)
    except (ValueError, TypeError):
        return value


class BackupService:
    def __init__(self, repository, *, app_origin: Literal["desktop", "mobile"] = "desktop",
                 app_version: str = "0.1.0", fingerprint_provider=get_device_fingerprint,
                 output_dir: Path | None = None):
        self.repository = repository
        self.db = repository.db
        self.app_origin = app_origin
        self.app_version = app_version
        self.fingerprint_provider = fingerprint_provider
        self.output_dir = output_dir or (Path.home() / ".fichacosto" / "backups")

    def crear_backup(self, password: str, destino: str | Path | None = None) -> Path:
        validar_contrasena(password)
        payload = self._snapshot_payload()
        errors = _validate_schema(payload, BACKUP_SCHEMA_DIR / "ficha148_backup_payload_v1.schema.json")
        self._validate_fichas(payload["fichas"])
        self._validate_unique_ids(payload["insumos"], "insumos")
        self._validate_unique_ids(payload["tarifasSalarios"], "tarifas salariales")
        self._validate_license_record(payload["licenciaActual"])
        if errors:
            raise BackupError("No se pudo validar el contenido antes de respaldar: " + "; ".join(errors[:5]))
        salt = secrets.token_bytes(SALT_BYTES)
        nonce = secrets.token_bytes(NONCE_BYTES)
        now = _iso_utc()
        memory = DEFAULT_MEMORY_KIB
        manifest = {
            "schemaVersion": SCHEMA_VERSION, "formato": "ficha148_backup", "fechaCreacion": now,
            "appOrigen": self.app_origin, "appVersion": self.app_version,
            "deviceFingerprintOrigen": self.fingerprint_provider(),
            "kdf": {"algoritmo": KDF_ALGORITHM, "salt": base64.b64encode(salt).decode("ascii"),
                    "memory": memory, "iterations": KDF_ITERATIONS, "parallelism": KDF_PARALLELISM},
            "cifrado": {"algoritmo": CIPHER_ALGORITHM, "nonce": base64.b64encode(nonce).decode("ascii")},
            "contenido": {"fichas": len(payload["fichas"]), "insumos": len(payload["insumos"]),
                          "salarios": len(payload["tarifasSalarios"]), "incluyeLicencia": payload["licenciaActual"] is not None,
                          "incluyePreferencias": True},
        }
        derived_key = derive_key(password, salt, memory)
        key, actual_memory = derived_key.key, derived_key.memory_kib
        if actual_memory != memory:
            manifest["kdf"]["memory"] = actual_memory
        manifest_bytes = _json_bytes(manifest)
        if _validate_schema(manifest, BACKUP_SCHEMA_DIR / "ficha148_backup_v1.schema.json"):
            raise BackupError("El manifiesto generado no cumple el esquema compartido.")
        plaintext = _json_bytes(payload)
        if len(plaintext) > MAX_PLAINTEXT_BYTES:
            raise BackupError("El respaldo supera el tamaño máximo de contenido admitido.")
        compressed = compress_gzip(plaintext)
        if len(compressed) + TAG_BYTES > MAX_ENCRYPTED_PAYLOAD_BYTES:
            raise BackupError("El respaldo supera el tamaño máximo admitido.")
        ciphertext = encrypt_aes_gcm(key, nonce, manifest_bytes, compressed)
        archive_bytes = build_zip(manifest_bytes, ciphertext)
        if destino is None:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            destino = self.output_dir / f"FichaCosto_{now.replace(':', '').replace('-', '')}.ficha148.bak"
        target = Path(destino)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".ficha148-bak-", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(archive_bytes)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
            os.replace(temporary, target)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
        return target

    def previsualizar_backup(self, path: str | Path, password: str) -> BackupPreview:
        validar_contrasena(password)
        try:
            manifest_bytes, ciphertext = read_zip(Path(path))
        except ArchiveFormatError as exc:
            raise BackupArchiveCorrupt(str(exc)) from exc
        try:
            manifest = _strict_json(manifest_bytes)
        except (ValueError, UnicodeDecodeError) as exc:
            raise BackupArchiveCorrupt("El manifiesto del respaldo está dañado.") from exc
        errors = _validate_schema(manifest, BACKUP_SCHEMA_DIR / "ficha148_backup_v1.schema.json")
        if errors:
            raise BackupArchiveCorrupt("El manifiesto no cumple el formato de respaldo v1.")
        try:
            salt = base64.b64decode(manifest["kdf"]["salt"], validate=True)
            nonce = base64.b64decode(manifest["cifrado"]["nonce"], validate=True)
            if len(salt) != SALT_BYTES or len(nonce) != NONCE_BYTES:
                raise ValueError("salt o nonce de longitud incorrecta")
        except (ValueError, TypeError, KeyError) as exc:
            raise BackupArchiveCorrupt("Los parámetros criptográficos del manifiesto no son válidos.") from exc
        try:
            key = derive_key(password, salt, int(manifest["kdf"]["memory"]), allow_fallback=False).key
        except Exception as exc:
            raise BackupError("No hay memoria disponible para aplicar los parámetros Argon2id de este respaldo. Libere memoria e inténtelo de nuevo; no se modificaron datos.") from exc
        try:
            compressed = decrypt_aes_gcm(key, nonce, manifest_bytes, ciphertext)
        except ValueError as exc:
            if str(exc) != "BACKUP_AUTHENTICATION_FAILED":
                raise
            raise BackupPasswordOrDataError("No se pudo autenticar el respaldo: contraseña incorrecta o archivo dañado/manipulado.") from exc
        try:
            plaintext = decompress_gzip_bounded(compressed, MAX_PLAINTEXT_BYTES)
        except (OSError, EOFError, ValueError) as exc:
            raise BackupArchiveCorrupt("El contenido gzip está dañado o supera el tamaño permitido.") from exc
        try:
            payload = _strict_json(plaintext)
        except (ValueError, UnicodeDecodeError) as exc:
            raise BackupArchiveCorrupt("Los datos descifrados no contienen JSON válido.") from exc
        errors = _validate_schema(payload, BACKUP_SCHEMA_DIR / "ficha148_backup_payload_v1.schema.json")
        if errors:
            raise BackupArchiveCorrupt("El contenido descifrado no cumple el esquema de respaldo v1.")
        self._validate_license_record(payload["licenciaActual"])
        try:
            self._validate_fichas(payload["fichas"])
            self._validate_unique_ids(payload["insumos"], "insumos")
            self._validate_unique_ids(payload["tarifasSalarios"], "tarifas salariales")
        except Exception as exc:
            raise BackupArchiveCorrupt("Una o más fichas del respaldo no cumplen el esquema de FichaCosto.") from exc
        counts = manifest["contenido"]
        if (counts["fichas"] != len(payload["fichas"]) or counts["insumos"] != len(payload["insumos"])
                or counts["salarios"] != len(payload["tarifasSalarios"])
                or counts["incluyeLicencia"] != (payload["licenciaActual"] is not None)):
            raise BackupArchiveCorrupt("Los contadores del manifiesto no coinciden con el contenido cifrado.")
        current = self.fingerprint_provider()
        return BackupPreview(manifest=manifest, payload=payload, fichas=len(payload["fichas"]),
            insumos=len(payload["insumos"]), salarios=len(payload["tarifasSalarios"]),
            incluye_licencia=payload["licenciaActual"] is not None, fecha_creacion=manifest["fechaCreacion"],
            fingerprint_origen=manifest["deviceFingerprintOrigen"], fingerprint_actual=current,
            origen_diferente=current != manifest["deviceFingerprintOrigen"])

    def aplicar_restauracion(self, preview: BackupPreview, *, modo: Literal["reemplazar", "fusionar"],
                              restaurar_licencia: bool = False, restaurar_usage: bool = False,
                              crear_respaldo_seguridad: bool = True) -> RestoreResult:
        if modo not in ("reemplazar", "fusionar"):
            raise BackupError("El modo debe ser reemplazar o fusionar.")
        payload = preview.payload
        errors = _validate_schema(payload, BACKUP_SCHEMA_DIR / "ficha148_backup_payload_v1.schema.json")
        self._validate_fichas(payload.get("fichas", []))
        self._validate_unique_ids(payload.get("insumos", []), "insumos")
        self._validate_unique_ids(payload.get("tarifasSalarios", []), "tarifas salariales")
        if errors:
            raise BackupArchiveCorrupt("La previsualización ya no contiene un payload válido.")
        self._validate_license_record(payload["licenciaActual"])
        safety_path = None
        if modo == "reemplazar" and crear_respaldo_seguridad:
            safety_path = self._crear_respaldo_seguridad()
        now = _iso_utc()
        try:
            self.db.execute("BEGIN IMMEDIATE")
            if modo == "reemplazar":
                self.db.execute("DELETE FROM fichas")
                self.db.execute("DELETE FROM catalogos")
                self._insert_records(payload["fichas"], payload["insumos"], payload["tarifasSalarios"])
                self.db.execute("DELETE FROM preferences WHERE key NOT LIKE ?", (INTERNAL_PREF_PREFIX + "%",))
                self._restore_preferences(payload["preferencias"], merge=False)
            else:
                self._merge_records(payload["fichas"], payload["insumos"], payload["tarifasSalarios"])
                self._restore_preferences(payload["preferencias"], merge=True)
            if restaurar_licencia:
                if payload["licenciaActual"] is None:
                    self.db.execute("DELETE FROM licensing_state WHERE key = 'license_document'")
                else:
                    self.db.execute("INSERT OR REPLACE INTO licensing_state (key, value) VALUES (?, ?)",
                                    ("license_document", json.dumps(payload["licenciaActual"], ensure_ascii=False, separators=(",", ":"))))
            if restaurar_usage:
                self._restore_usage(payload["usage"]["features"], payload["usage"]["ultimoTimestamp"], replace=(modo == "reemplazar"))
            # Never import another device's anti-rollback clock. Establish a local baseline.
            self.db.execute("INSERT OR REPLACE INTO licensing_state (key, value) VALUES (?, ?)", ("last_seen_ts", now))
            self.db.execute("INSERT OR REPLACE INTO licensing_state (key, value) VALUES (?, ?)", ("clock_rollback_started_at", ""))
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            suffix = f" El respaldo de seguridad está en {safety_path}." if safety_path else ""
            raise BackupError("No se aplicaron cambios: la restauración se revirtió." + suffix) from exc
        return RestoreResult(mode=modo, fichas_restauradas=len(payload["fichas"]),
            insumos_restaurados=len(payload["insumos"]), salarios_restaurados=len(payload["tarifasSalarios"]),
            licencia_actualizada=restaurar_licencia, usage_actualizado=restaurar_usage, respaldo_seguridad=safety_path)

    def restaurar_backup(self, path: str | Path, password: str, *, modo: Literal["reemplazar", "fusionar"] | None = None,
                         confirmacion: str | None = None, restaurar_licencia: bool = False,
                         restaurar_usage: bool = False) -> BackupPreview | RestoreResult:
        preview = self.previsualizar_backup(path, password)
        if modo is None:
            return preview
        if modo == "reemplazar" and confirmacion != "REEMPLAZAR":
            raise BackupError("El reemplazo requiere escribir REEMPLAZAR para confirmar el borrado local.")
        return self.aplicar_restauracion(preview, modo=modo, restaurar_licencia=restaurar_licencia,
                                         restaurar_usage=restaurar_usage)

    def restaurar_respaldo_seguridad(self) -> RestoreResult:
        path = self._get_internal_pref("safety_path")
        password = self._get_internal_pref("safety_password")
        if not isinstance(path, str) or not isinstance(password, str) or not Path(path).is_file():
            raise BackupError("No hay un respaldo de seguridad previo disponible.")
        preview = self.previsualizar_backup(path, password)
        return self.aplicar_restauracion(preview, modo="reemplazar", restaurar_licencia=True,
                                         restaurar_usage=True, crear_respaldo_seguridad=False)

    def _snapshot_payload(self) -> dict[str, Any]:
        db = self.db
        db.execute("BEGIN")
        try:
            fichas = [_strict_json(row[0]) for row in db.execute("SELECT documento_json FROM fichas").fetchall()]
            catalog_rows = db.execute("SELECT tipo, documento_json FROM catalogos").fetchall()
            insumos = [_strict_json(value) for kind, value in catalog_rows if kind == "insumo"]
            salaries = [_strict_json(value) for kind, value in catalog_rows if kind == "tarifa"]
            state = dict(db.execute("SELECT key, value FROM licensing_state").fetchall())
            usage = [{"licenseId": license_id, "feature": feature, "usedCount": int(count)}
                     for license_id, feature, count in db.execute("SELECT license_id, feature, used_count FROM licensing_usage").fetchall()]
            preferences = {}
            for key, value in db.execute("SELECT key, value_json FROM preferences").fetchall():
                if not key.startswith(INTERNAL_PREF_PREFIX):
                    preferences[key] = _json_pref(value)
            db.commit()
        except Exception:
            db.rollback()
            raise
        license_document = _strict_json(state["license_document"]) if state.get("license_document") else None
        last_seen = state.get("last_seen_ts") or None
        usage.sort(key=lambda item: (item["licenseId"], item["feature"]))
        return _normalize_payload({
            "schemaVersion": SCHEMA_VERSION, "exportadoEn": _iso_utc(),
            "fichas": fichas, "insumos": insumos, "tarifasSalarios": salaries,
            "licenciaActual": license_document, "preferencias": preferences,
            "usage": {"features": usage, "fichasCreadasTotal": sum(x["usedCount"] for x in usage if x["feature"] == "fichas"),
                      "ultimoTimestamp": state.get("usage_last_timestamp") or last_seen, "lastSeenTimestamp": last_seen},
        })

    @staticmethod
    def _validate_license_record(document: dict[str, Any] | None) -> None:
        if document is None:
            return
        schema = Path(__file__).resolve().parents[1] / "licensing" / "licencia_v1.schema.json"
        errors = validate_license(document, schema)
        if errors:
            raise BackupArchiveCorrupt("La copia de licencia guardada no cumple su esquema v1.")

    @staticmethod
    def _validate_unique_ids(records: list[Any], label: str) -> None:
        ids = [item.get("id") for item in records if isinstance(item, dict)]
        if len(ids) != len(records) or len(set(ids)) != len(ids) or any(not isinstance(value, str) for value in ids):
            raise BackupArchiveCorrupt(f"El respaldo contiene identificadores duplicados o inválidos en {label}.")

    @staticmethod
    def _validate_fichas(fichas: list[Any]) -> None:
        if not isinstance(fichas, list):
            raise BackupArchiveCorrupt("La lista de fichas no es válida.")
        validator = Ficha148Validator()
        seen = set()
        for doc in fichas:
            errors = validator.validar_documento(doc)
            if errors:
                raise BackupArchiveCorrupt("Ficha inválida: " + "; ".join(errors[:3]))
            ficha = doc.get("ficha", {})
            if ficha.get("id") in seen:
                raise BackupArchiveCorrupt("El respaldo contiene identificadores de ficha duplicados.")
            seen.add(ficha.get("id"))

    def _insert_records(self, fichas, insumos, salarios):
        for document in fichas:
            ficha = document["ficha"]
            self.db.execute("INSERT INTO fichas (id, nombre, estado, fecha_actualizacion, documento_json) VALUES (?, ?, ?, ?, ?)",
                (ficha["id"], ficha["nombre"], ficha["estado"], ficha["fechaActualizacion"], json.dumps(document, ensure_ascii=False, separators=(",", ":"))))
        for kind, records in (("insumo", insumos), ("tarifa", salarios)):
            for item in records:
                self.db.execute("INSERT INTO catalogos (id, tipo, documento_json) VALUES (?, ?, ?)",
                    (item["id"], kind, json.dumps(item, ensure_ascii=False, separators=(",", ":"))))

    def _merge_records(self, fichas, insumos, salarios):
        for incoming in fichas:
            ficha = incoming["ficha"]
            current = self.db.execute("SELECT documento_json FROM fichas WHERE id = ?", (ficha["id"],)).fetchone()
            if current is not None:
                existing_doc = _strict_json(current[0])
                existing_date = existing_doc.get("ficha", {}).get("fechaActualizacion", "")
                if _date_key(existing_date) >= _date_key(ficha.get("fechaActualizacion", "")):
                    continue
            self.db.execute("INSERT OR REPLACE INTO fichas (id, nombre, estado, fecha_actualizacion, documento_json) VALUES (?, ?, ?, ?, ?)",
                (ficha["id"], ficha["nombre"], ficha["estado"], ficha["fechaActualizacion"], json.dumps(incoming, ensure_ascii=False, separators=(",", ":"))))
        for kind, records in (("insumo", insumos), ("tarifa", salarios)):
            for item in records:
                self.db.execute("INSERT OR REPLACE INTO catalogos (id, tipo, documento_json) VALUES (?, ?, ?)",
                    (item["id"], kind, json.dumps(item, ensure_ascii=False, separators=(",", ":"))))

    def _restore_preferences(self, preferences: dict[str, Any], *, merge: bool):
        for key, value in preferences.items():
            if not isinstance(key, str) or key.startswith(INTERNAL_PREF_PREFIX):
                continue
            self.db.execute("INSERT OR REPLACE INTO preferences (key, value_json) VALUES (?, ?)",
                            (key, json.dumps(value, ensure_ascii=False, separators=(",", ":"))))

    def _restore_usage(self, records: list[dict[str, Any]], last_timestamp: str | None, *, replace: bool):
        # Keep local counts as a monotonic floor so an older backup cannot reset quotas.
        for record in records:
            existing = self.db.execute("SELECT used_count FROM licensing_usage WHERE license_id = ? AND feature = ?",
                (record["licenseId"], record["feature"])).fetchone()
            count = max(int(record["usedCount"]), int(existing[0]) if existing else 0)
            self.db.execute("INSERT OR REPLACE INTO licensing_usage (license_id, feature, used_count) VALUES (?, ?, ?)",
                (record["licenseId"], record["feature"], count))
        if last_timestamp:
            current = self.db.execute("SELECT value FROM licensing_state WHERE key = 'usage_last_timestamp'").fetchone()
            existing = current[0] if current else None
            if not existing or _date_key(last_timestamp) > _date_key(existing):
                self.db.execute("INSERT OR REPLACE INTO licensing_state (key, value) VALUES (?, ?)",
                                ("usage_last_timestamp", last_timestamp))

    def _crear_respaldo_seguridad(self) -> Path:
        password = secrets.token_urlsafe(36)
        timestamp = _iso_utc().replace(":", "").replace("-", "")
        path = self.output_dir / f".pre-restore-{timestamp}.ficha148.bak"
        self.crear_backup(password, path)
        # This recovery secret is itself protected by the local SQLCipher database.
        # It is never exported in user backups and is only used to recover a failed replace.
        self.db.execute("INSERT OR REPLACE INTO preferences (key, value_json) VALUES (?, ?)",
                        (INTERNAL_PREF_PREFIX + "safety_path", json.dumps(str(path))))
        self.db.execute("INSERT OR REPLACE INTO preferences (key, value_json) VALUES (?, ?)",
                        (INTERNAL_PREF_PREFIX + "safety_password", json.dumps(password)))
        self.db.commit()
        return path

    def _get_internal_pref(self, name: str):
        row = self.db.execute("SELECT value_json FROM preferences WHERE key = ?", (INTERNAL_PREF_PREFIX + name,)).fetchone()
        return _json_pref(row[0]) if row else None


# Friendly camelCase aliases for the cross-platform API naming.
BackupService.crearBackup = BackupService.crear_backup
BackupService.previsualizarBackup = BackupService.previsualizar_backup
BackupService.aplicarRestauracion = BackupService.aplicar_restauracion
BackupService.restaurarBackup = BackupService.restaurar_backup
