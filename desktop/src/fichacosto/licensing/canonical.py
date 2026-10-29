"""Interoperable license JSON canonicalization and schema/signature helpers.

Signature input is exactly the UTF-8 bytes of the payload object (not the envelope):
1) recursively normalize every string/key to Unicode NFC;
2) sort object keys lexicographically (payload keys are ASCII);
3) serialize compact JSON with no spaces, ensure_ascii=False, and no NaN/Infinity;
4) encode the resulting text as UTF-8.
Flutter implements the same rules in mobile/lib/licensing/canonical.dart.
"""
from __future__ import annotations

import base64
import json
import math
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jsonschema import Draft202012Validator, FormatChecker


def schema_path() -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[4]))
    candidates = [root / "shared" / "licencia_v1.schema.json", Path.cwd() / "shared" / "licencia_v1.schema.json", Path(__file__).with_name("licencia_v1.schema.json")]
    for item in candidates:
        if item.is_file():
            return item
    raise FileNotFoundError("No se encontró shared/licencia_v1.schema.json")


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("El payload no permite NaN ni infinito")
        raise ValueError("El payload de licencia no permite números decimales")
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        normalized = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("Las claves JSON del payload deben ser texto")
            nkey = unicodedata.normalize("NFC", key)
            if nkey in normalized:
                raise ValueError("Claves duplicadas después de normalización Unicode")
            normalized[nkey] = _normalize(item)
        return normalized
    raise ValueError(f"Tipo no permitido en payload: {type(value).__name__}")


def canonical_payload(payload: dict[str, Any]) -> bytes:
    normalized = _normalize(payload)
    text = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return text.encode("utf-8")


def validate_license(document: Any, path: Path | None = None) -> list[str]:
    if not isinstance(document, dict):
        return ["El archivo .lic debe contener un objeto JSON."]
    schema = json.loads((path or schema_path()).read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(document), key=lambda error: (list(map(str, error.absolute_path)), error.message))
    return [_schema_error(error) for error in errors[:50]]


def verify_payload_signature(document: dict[str, Any], public_key: bytes) -> bool:
    if len(public_key) != 32:
        return False
    try:
        signature = base64.b64decode(document["signature"], validate=True)
        if len(signature) != 64:
            return False
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, canonical_payload(document["payload"]))
        return True
    except (KeyError, TypeError, ValueError, InvalidSignature):
        return False


def _schema_error(error) -> str:
    path = " › ".join(_label(x) for x in error.absolute_path) or "documento"
    if error.validator == "required":
        parent = error.instance if isinstance(error.instance, dict) else {}
        missing = [name for name in error.validator_value if name not in parent]
        return "Falta el campo obligatorio: " + ", ".join(_label(x) for x in missing) + "."
    if error.validator == "format":
        formats = {"uuid": "un UUID", "date-time": "una fecha y hora ISO 8601", "email": "un correo electrónico"}
        return f"El campo {path} debe tener {formats.get(str(error.validator_value), 'un formato válido')}."
    if error.validator == "type":
        return f"El campo {path} tiene un tipo de dato no válido."
    if error.validator in ("enum", "const"):
        return f"El campo {path} tiene un valor no permitido."
    if error.validator == "additionalProperties":
        return f"El campo {path} contiene propiedades no reconocidas."
    if error.validator in ("minLength", "minimum", "maxLength", "pattern", "uniqueItems"):
        return f"El campo {path} no cumple una condición obligatoria del esquema."
    return f"El campo {path} no cumple el esquema de licencia v1."


def _label(value: Any) -> str:
    labels = {
        "schemaVersion": "versión del esquema", "payload": "payload", "signature": "firma",
        "licenseId": "identificador de licencia", "producto": "producto", "tipo": "tipo de licencia",
        "titular": "titular", "nombre": "nombre", "nit": "NIT", "email": "correo electrónico",
        "deviceFingerprint": "ID de dispositivo", "fechaEmision": "fecha de emisión",
        "fechaExpiracion": "fecha de expiración", "features": "funciones habilitadas",
        "maxFichas": "límite de fichas", "notas": "notas",
    }
    return labels.get(str(value), str(value))
