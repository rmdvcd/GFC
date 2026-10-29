"""Secure structural and semantic validation for the .ficha148 package.

No ZIP path is ever extracted to disk. All archive members are preflighted and
read through bounded streams, preventing ZipSlip and limiting decompression-bomb
impact before JSON decoding. The shared Draft 2020-12 schema is the source of truth.
"""
from __future__ import annotations

import json
import re
from io import BytesIO
import stat
import struct
import sys
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError as JsonSchemaError

MAX_PACKAGE_BYTES = 10 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 10 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100
EXPECTED_FILES = {"manifest.json", "ficha.json"}
ZIP_ERROR = "El archivo no es un paquete .ficha148 válido. Puede estar dañado o no ser un archivo ZIP."

_FIELD_LABELS = {
    "schemaVersion": "versión del esquema", "ficha": "ficha", "id": "identificador UUID",
    "nombre": "nombre de la ficha", "descripcion": "descripción", "fechaCreacion": "fecha de creación",
    "fechaActualizacion": "fecha de actualización", "estado": "estado", "monedaBase": "moneda base",
    "partidas": "partidas", "categoria": "categoría", "cantidad": "cantidad",
    "unidadMedida": "unidad de medida", "costoUnitario": "costo unitario", "subtotal": "subtotal",
    "insumoId": "identificador del insumo", "observaciones": "observaciones", "valor": "valor",
    "moneda": "moneda", "catalogosSnapshot": "instantánea de catálogos", "insumos": "insumos",
    "tarifasSalario": "tarifas salariales", "cargo": "cargo", "tarifa": "tarifa",
    "unidadTarifa": "unidad de tarifa", "coeficientes": "coeficientes", "coeficienteIndirecto": "coeficiente indirecto",
    "margenGanancia": "margen de ganancia", "unidadCoeficiente": "unidad del coeficiente",
    "totales": "totales", "porCategoria": "totales por categoría", "costoTotal": "costo total",
    "CUP": "total CUP", "MLC": "total MLC", "precioCalculado": "precio calculado", "extensionData": "datos adicionales",
}


def _schema_path() -> Path:
    roots = [Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3])), Path.cwd()]
    for root in roots:
        candidate = root / "shared" / "ficha_costo_v1.schema.json"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("No se encontró shared/ficha_costo_v1.schema.json")


SCHEMA_PATH = _schema_path()


class Ficha148ValidationError(ValueError):
    """A safe, user-facing validation error; never includes a traceback."""

    def __init__(self, messages: Iterable[str], *, package_error: bool = False):
        self.messages = list(messages)
        self.package_error = package_error
        super().__init__("\n".join(f"• {message}" for message in self.messages))


@dataclass(frozen=True)
class ValidationSummary:
    document: dict[str, Any]
    entity: str
    period: str
    cup: float
    mlc: float


class Ficha148Validator:
    """Validates .ficha148 bytes/paths and JSON documents against the shared schema."""

    def __init__(self, schema_path: Path = SCHEMA_PATH):
        try:
            schema = _json_load_strict(schema_path.read_bytes())
            if not isinstance(schema, dict):
                raise SchemaError("El esquema raíz debe ser un objeto")
            Draft202012Validator.check_schema(schema)
            self._validator = Draft202012Validator(schema, format_checker=FormatChecker())
        except (OSError, json.JSONDecodeError, SchemaError, UnicodeDecodeError) as exc:
            raise RuntimeError("No se pudo preparar la validación del esquema compartido") from exc

    def validar_documento(self, document: Any) -> list[str]:
        if not isinstance(document, dict):
            return ["El contenido de ficha.json debe ser un objeto JSON."]
        errors = sorted(self._validator.iter_errors(document), key=lambda error: (list(map(str, error.absolute_path)), error.message))
        messages: list[str] = []
        for error in errors:
            messages.extend(_traducir_error(error, document))
        # Avoid flooding the UI with pathological arrays or adversarial schemas/data.
        unique = list(dict.fromkeys(messages))
        if len(unique) > 50:
            return unique[:50] + ["Hay más errores; corrija los anteriores y vuelva a validar."]
        return unique

    def validar_o_lanzar(self, document: Any) -> dict[str, Any]:
        messages = self.validar_documento(document)
        if messages:
            raise Ficha148ValidationError(messages)
        return document

    def validar_paquete(self, source: str | Path | bytes | bytearray) -> ValidationSummary:
        """Read an exact two-file package without extracting it, then validate JSON."""
        try:
            if isinstance(source, (bytes, bytearray)):
                package = bytes(source)
            else:
                package_path = Path(source)
                if package_path.stat().st_size > MAX_PACKAGE_BYTES:
                    raise _InvalidZip
                with package_path.open("rb") as package_file:
                    package = package_file.read(MAX_PACKAGE_BYTES + 1)
            if len(package) > MAX_PACKAGE_BYTES or len(package) < 4 or not package.startswith(b"PK\x03\x04"):
                raise _InvalidZip
            with zipfile.ZipFile(BytesIO(package), mode="r") as archive:
                infos = archive.infolist()
                if len(infos) != len(EXPECTED_FILES):
                    raise _InvalidZip
                names: list[str] = []
                total_uncompressed = 0
                for info in infos:
                    name = info.filename
                    _validar_nombre_zip(name)
                    if name not in EXPECTED_FILES or name in names:
                        raise _InvalidZip
                    names.append(name)
                    mode = (info.external_attr >> 16) & 0xFFFF
                    file_type = stat.S_IFMT(mode)
                    if stat.S_ISLNK(mode) or info.is_dir() or (file_type and file_type != stat.S_IFREG):
                        raise _InvalidZip
                    if info.flag_bits & 0x1:  # encrypted ZIP members are not accepted
                        raise _InvalidZip
                    if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                        raise _InvalidZip
                    if info.file_size < 0 or info.file_size > MAX_UNCOMPRESSED_BYTES:
                        raise _InvalidZip
                    if info.compress_size < 0 or info.compress_size > MAX_PACKAGE_BYTES:
                        raise _InvalidZip
                    if info.file_size and (not info.compress_size or info.file_size / info.compress_size > MAX_COMPRESSION_RATIO):
                        raise _InvalidZip
                    total_uncompressed += info.file_size
                    if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                        raise _InvalidZip
                if set(names) != EXPECTED_FILES:
                    raise _InvalidZip

                contents = {info.filename: _read_member_bounded(archive, info) for info in infos}

            try:
                manifest = _json_load_strict(contents["manifest.json"])
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                raise Ficha148ValidationError(["El archivo manifest.json contiene JSON mal formado."]) from None
            try:
                document = _json_load_strict(contents["ficha.json"])
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                raise Ficha148ValidationError(["El archivo ficha.json contiene JSON mal formado."]) from None
            if not isinstance(manifest, dict):
                raise _InvalidZip
            if not isinstance(document, dict):
                raise Ficha148ValidationError(["El contenido de ficha.json debe ser un objeto JSON."])
            if (manifest.get("format") != "ficha148" or type(manifest.get("formatVersion")) is not int
                    or manifest.get("formatVersion") != 1 or manifest.get("document") != "ficha.json"
                    or type(manifest.get("schemaVersion")) is not int):
                raise _InvalidZip
            if manifest["schemaVersion"] != document.get("schemaVersion"):
                raise _InvalidZip
        except Ficha148ValidationError:
            raise
        except (OSError, ValueError, KeyError, TypeError, UnicodeDecodeError, zipfile.BadZipFile,
                zipfile.LargeZipFile, EOFError, RuntimeError, NotImplementedError, zlib.error, struct.error, _InvalidZip):
            raise Ficha148ValidationError([ZIP_ERROR], package_error=True) from None

        validated = self.validar_o_lanzar(document)
        ficha = validated.get("ficha", {})
        totals = ficha.get("totales", {}) if isinstance(ficha, dict) else {}
        total = totals.get("costoTotal", {}) if isinstance(totals, dict) else {}
        extension = ficha.get("extensionData", {}) if isinstance(ficha, dict) else {}
        anexo = extension.get("anexoI", {}) if isinstance(extension, dict) else {}
        entity = anexo.get("nombreEntidad", "[PENDIENTE]") if isinstance(anexo, dict) else "[PENDIENTE]"
        period = anexo.get("periodoVigencia", "[PENDIENTE]") if isinstance(anexo, dict) else "[PENDIENTE]"
        return ValidationSummary(validated, str(entity or "[PENDIENTE]"), str(period or "[PENDIENTE]"),
                                 float(total.get("CUP", 0)), float(total.get("MLC", 0)))


class _InvalidZip(Exception):
    pass


def _validar_nombre_zip(name: str) -> None:
    # Strict whitelist plus explicit path checks protects against ZipSlip, absolute paths,
    # Windows drive paths, backslash traversal, and alternate separator tricks.
    if (not name or "\\" in name or name.startswith("/") or ":" in name
            or any(part in ("", ".", "..") for part in name.split("/"))):
        raise _InvalidZip


def _read_member_bounded(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    chunks: list[bytes] = []
    actual_size = 0
    try:
        with archive.open(info, "r") as member:
            while True:
                chunk = member.read(min(64 * 1024, MAX_UNCOMPRESSED_BYTES + 1 - actual_size))
                if not chunk:
                    break
                actual_size += len(chunk)
                if actual_size > MAX_UNCOMPRESSED_BYTES or actual_size > info.file_size:
                    raise _InvalidZip
                chunks.append(chunk)
    except (OSError, EOFError, RuntimeError, zipfile.BadZipFile) as exc:
        raise _InvalidZip from exc
    if actual_size != info.file_size:
        raise _InvalidZip
    return b"".join(chunks)


def _json_load_strict(content: bytes) -> Any:
    def reject_constant(value: str):
        raise ValueError(f"Constante JSON no permitida: {value}")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Clave JSON duplicada")
            result[key] = value
        return result

    return json.loads(content.decode("utf-8"), parse_constant=reject_constant, object_pairs_hook=unique_object)


def _traducir_error(error: JsonSchemaError, document: dict[str, Any]) -> list[str]:
    path_parts = list(error.absolute_path)
    field = _ruta_legible(path_parts)
    keyword = error.validator

    if keyword == "required":
        parent = _obtener(document, path_parts)
        missing = [key for key in error.validator_value if not isinstance(parent, dict) or key not in parent]
        return [f"Falta el campo obligatorio: {_etiqueta(key)}." for key in missing] or [f"Falta un campo obligatorio en {field}."]
    if keyword == "additionalProperties":
        instance = _obtener(document, path_parts)
        allowed = set(error.schema.get("properties", {})) if isinstance(error.schema, dict) else set()
        extras = sorted(set(instance) - allowed) if isinstance(instance, dict) else []
        return [f"El campo {field} contiene una propiedad no reconocida: '{key}'." for key in extras] or [f"El campo {field} contiene propiedades no reconocidas."]
    if keyword == "type":
        expected = error.validator_value
        expected_text = " o ".join(_tipo_espanol(item) for item in expected) if isinstance(expected, list) else _tipo_espanol(expected)
        actual = _obtener(document, path_parts)
        return [f"El campo {field} debe ser {_articulo_tipo(expected_text)}{expected_text}; se recibió {_tipo_instancia(actual)}."]
    if keyword == "format":
        fmt = {"uuid": "un UUID válido", "date-time": "una fecha y hora ISO 8601 válida"}.get(str(error.validator_value), "un formato válido")
        return [f"El campo {field} debe tener {fmt}."]
    if keyword in ("enum", "const"):
        return [f"El campo {field} tiene un valor no permitido."]
    if keyword == "minLength":
        return [f"El campo {field} no puede estar vacío." if error.validator_value == 1 else f"El campo {field} debe tener al menos {error.validator_value} caracteres."]
    if keyword == "minimum":
        return [f"El campo {field} debe ser mayor o igual que {error.validator_value}."]
    if keyword == "minItems":
        return [f"La lista {field} debe contener al menos {error.validator_value} elemento(s)."]
    if keyword == "pattern":
        return [f"El campo {field} no cumple el formato esperado."]
    if keyword == "anyOf":
        return [f"El campo {field} no tiene una estructura válida."]
    return [f"El campo {field} no cumple una regla obligatoria del formato ficha148."]


def _obtener(document: Any, path: list[Any]) -> Any:
    current = document
    for part in path:
        try:
            current = current[part]
        except (KeyError, IndexError, TypeError):
            return None
    return current


def _etiqueta(part: Any) -> str:
    if isinstance(part, int):
        return f"partida {part + 1}"
    return _FIELD_LABELS.get(str(part), str(part))


def _ruta_legible(parts: list[Any]) -> str:
    if not parts:
        return "el documento"
    chunks: list[str] = []
    for part in parts:
        if isinstance(part, int):
            chunks.append(f"{part + 1}")
        else:
            chunks.append(_etiqueta(part))
    path = ".".join(chunks)
    # Make list indexes understandable without exposing JSON Pointer syntax.
    return re.sub(r"\.([0-9]+)(?=\.|$)", lambda match: f" (elemento {int(match.group(1)) + 1})", path)


def _tipo_espanol(value: Any) -> str:
    return {"string": "texto", "number": "número", "integer": "número entero", "object": "objeto", "array": "lista", "boolean": "valor lógico", "null": "nulo"}.get(str(value), "valor")


def _tipo_instancia(value: Any) -> str:
    if value is None:
        return "nulo"
    if isinstance(value, bool):
        return "un valor lógico"
    if isinstance(value, dict):
        return "un objeto"
    if isinstance(value, list):
        return "una lista"
    if isinstance(value, str):
        return "un texto"
    if isinstance(value, (float, int)):
        return "un número"
    return "un valor"


def _articulo_tipo(expected: str) -> str:
    if expected.startswith(("número", "objeto")):
        return "un "
    if expected.startswith(("texto", "lista")):
        return "un " if expected == "texto" else "una "
    return "un "
