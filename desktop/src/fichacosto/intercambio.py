"""Export/import wrappers for .ficha148; validation lives in ficha148_validator."""
from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .ficha148_validator import Ficha148ValidationError, Ficha148Validator, SCHEMA_PATH

SCHEMA = SCHEMA_PATH


def validar(documento: dict[str, Any], ruta_esquema: Path = SCHEMA) -> None:
    """Validate a document and raise user-readable messages for every schema error."""
    validator = Ficha148Validator(ruta_esquema)
    validator.validar_o_lanzar(documento)


def exportar_ficha(documento: dict[str, Any], destino: str | Path) -> Path:
    validar(documento)
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "format": "ficha148", "formatVersion": 1, "schemaVersion": documento["schemaVersion"],
        "document": "ficha.json", "producer": "FichaCosto Desktop",
        "exportedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    with zipfile.ZipFile(destino, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr("ficha.json", json.dumps(documento, ensure_ascii=False, indent=2))
    return destino


def validar_paquete(origen: str | Path):
    """Return a summary without changing the local database."""
    return Ficha148Validator().validar_paquete(origen)


def importar_ficha(origen: str | Path) -> dict[str, Any]:
    """Compatibility helper: safely validate and return document, no DB writes."""
    return validar_paquete(origen).document


__all__ = ["SCHEMA", "Ficha148ValidationError", "Ficha148Validator", "validar", "validar_paquete", "exportar_ficha", "importar_ficha"]
