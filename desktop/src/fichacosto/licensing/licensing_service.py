"""Offline license lifecycle and Ed25519 verification for FichaCosto Desktop."""
from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .canonical import schema_path, validate_license, verify_payload_signature
from .fingerprint import get_device_fingerprint
from .models import EstadoLicencia, EstadoLicenciaActual, ResultadoLicencia
from .public_key import PUBLIC_KEY_B64

MAX_LICENSE_BYTES = 128 * 1024
CLOCK_GRACE = timedelta(hours=24)
_PRIVATE_ADVICE = "Contacte al proveedor para obtener una licencia válida para este dispositivo."


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("La fecha debe incluir zona horaria")
    return parsed.astimezone(timezone.utc)


def _load_strict_json(data: bytes) -> Any:
    def pairs_hook(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Clave JSON duplicada")
            value[key] = item
        return value
    return json.loads(data.decode("utf-8"), object_pairs_hook=pairs_hook,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Constante JSON inválida")))


class LicensingService:
    """Verifies licenses and persists the activation/clock/quota state through SQLCipher.

    `repository` must provide license_get_state, license_set_state, license_get_usage,
    and license_consume_quota methods. The persisted wall-clock guard detects common
    clock rollback; it is not a trusted clock and cannot resist a local administrator.
    """

    def __init__(self, repository, *, public_key_b64: str | None = None,
                 fingerprint_provider: Callable[[], str] = get_device_fingerprint,
                 now_provider: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 schema: Path | None = None):
        self.repository = repository
        self.public_key_b64 = PUBLIC_KEY_B64 if public_key_b64 is None else public_key_b64
        self.fingerprint_provider = fingerprint_provider
        self.now_provider = now_provider
        self.schema = schema or schema_path()

    def cargar_licencia(self, archivo: str | Path) -> ResultadoLicencia:
        try:
            path = Path(archivo)
            with path.open("rb") as stream:
                raw = stream.read(MAX_LICENSE_BYTES + 1)
            if len(raw) > MAX_LICENSE_BYTES:
                return self._reject(EstadoLicencia.SCHEMA_INVALIDO, "El archivo de licencia supera el tamaño permitido.")
            document = _load_strict_json(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return self._reject(EstadoLicencia.SCHEMA_INVALIDO, "No se pudo leer el archivo .lic como JSON válido.")
        errors = validate_license(document, self.schema)
        if errors:
            return self._reject(EstadoLicencia.SCHEMA_INVALIDO, "\n".join(f"• {e}" for e in errors))
        try:
            public_key = base64.b64decode(self.public_key_b64, validate=True)
        except (ValueError, TypeError):
            public_key = b""
        if len(public_key) != 32 or not verify_payload_signature(document, public_key):
            return self._reject(EstadoLicencia.FIRMA_INVALIDA,
                                "La firma Ed25519 no es válida o la clave pública de esta compilación no está configurada. " + _PRIVATE_ADVICE)
        payload = document["payload"]
        if payload["deviceFingerprint"] != self.fingerprint_provider():
            return self._reject(EstadoLicencia.FINGERPRINT_NO_COINCIDE,
                                "La licencia fue emitida para otro dispositivo. " + _PRIVATE_ADVICE, payload)

        # Only schema-valid, correctly signed, device-bound licenses are persisted.
        self.repository.license_set_state("license_document", json.dumps(document, ensure_ascii=False, separators=(",", ":")))
        return self.estado_actual()

    def estado_actual(self) -> EstadoLicenciaActual:
        raw = self.repository.license_get_state("license_document")
        if not raw:
            return EstadoLicenciaActual(EstadoLicencia.NO_INSTALADA,
                motivoRechazo="No hay una licencia instalada. Importe un archivo .lic válido.")
        try:
            document = _load_strict_json(raw.encode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return EstadoLicenciaActual(EstadoLicencia.SCHEMA_INVALIDO,
                motivoRechazo="La licencia guardada está dañada. Vuelva a importarla.")
        errors = validate_license(document, self.schema)
        if errors:
            return EstadoLicenciaActual(EstadoLicencia.SCHEMA_INVALIDO, motivoRechazo="\n".join(errors))
        try:
            public_key = base64.b64decode(self.public_key_b64, validate=True)
        except (ValueError, TypeError):
            public_key = b""
        if len(public_key) != 32 or not verify_payload_signature(document, public_key):
            return EstadoLicenciaActual(EstadoLicencia.FIRMA_INVALIDA,
                motivoRechazo="La firma de la licencia guardada no es válida. " + _PRIVATE_ADVICE)
        payload = document["payload"]
        if payload["deviceFingerprint"] != self.fingerprint_provider():
            return EstadoLicenciaActual(EstadoLicencia.FINGERPRINT_NO_COINCIDE, tipo=payload["tipo"],
                features=tuple(payload["features"]), payload=payload,
                motivoRechazo="La licencia no corresponde a este dispositivo. " + _PRIVATE_ADVICE)

        now = self._now()
        last_seen_text = self.repository.license_get_state("last_seen_ts")
        rollback_text = self.repository.license_get_state("clock_rollback_started_at")
        warning = None
        if last_seen_text:
            try:
                last_seen = _parse_time(last_seen_text)
            except ValueError:
                last_seen = now
            if now < last_seen:
                if not rollback_text:
                    rollback_text = now.isoformat().replace("+00:00", "Z")
                    self.repository.license_set_state("clock_rollback_started_at", rollback_text)
                try:
                    rollback_started = _parse_time(rollback_text)
                except ValueError:
                    rollback_started = now
                if now - rollback_started >= CLOCK_GRACE:
                    return self._status(EstadoLicencia.EXPIRADA, payload, now,
                        reason="Se detectó un retroceso del reloj y se agotó la gracia de 24 horas. Corrija la fecha del dispositivo.")
                warning = "Se detectó un retroceso del reloj. La licencia está en gracia temporal de 24 horas; corrija la fecha del dispositivo."
            else:
                self.repository.license_set_state("last_seen_ts", now.isoformat().replace("+00:00", "Z"))
                if rollback_text:
                    self.repository.license_set_state("clock_rollback_started_at", "")
        else:
            self.repository.license_set_state("last_seen_ts", now.isoformat().replace("+00:00", "Z"))

        expiration = payload["fechaExpiracion"]
        if expiration is not None and now >= _parse_time(expiration) and warning is None:
            return self._status(EstadoLicencia.EXPIRADA, payload, now,
                reason="La licencia expiró. Puede seguir consultando sus fichas y exportar PDF con marca de agua.")
        return self._status(EstadoLicencia.VALIDA, payload, now, warning=warning)

    def consumir_feature(self, feature: str) -> bool:
        status = self.estado_actual()
        payload = status.payload
        if status.estado is not EstadoLicencia.VALIDA or payload is None or feature not in payload["features"]:
            return False
        if feature == "fichas":
            return self.repository.license_consume_quota(payload["licenseId"], feature, payload["maxFichas"])
        return True

    def _status(self, state: EstadoLicencia, payload: dict[str, Any], now: datetime,
                reason: str | None = None, warning: str | None = None) -> EstadoLicenciaActual:
        license_id = payload["licenseId"]
        used = self.repository.license_get_usage(license_id, "fichas")
        expiry = payload["fechaExpiracion"]
        days = None if expiry is None else max(0, int((_parse_time(expiry) - now).total_seconds() // 86400))
        return EstadoLicenciaActual(
            estado=state, tipo=payload["tipo"], features=tuple(payload["features"]),
            fichasRestantes=max(0, payload["maxFichas"] - used), diasHastaExpiracion=days,
            payload=payload, motivoRechazo=reason, advertencia=warning,
        )

    def _now(self) -> datetime:
        now = self.now_provider()
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc)

    @staticmethod
    def _reject(state: EstadoLicencia, reason: str, payload: dict[str, Any] | None = None) -> ResultadoLicencia:
        return ResultadoLicencia(state, payload, reason)

    # API aliases matching the product-level terminology.
    cargarLicencia = cargar_licencia
    estadoActual = estado_actual
    consumirFeature = consumir_feature
