"""Casos de uso básicos para guardar, importar y exportar fichas."""
from pathlib import Path
from .dominio import FichaCosto
from .intercambio import exportar_ficha, validar, validar_paquete
from .ficha148_validator import ValidationSummary
from .repositorio import RepositorioFichas


def crear_ficha(nombre: str, repo: RepositorioFichas) -> dict:
    ficha = FichaCosto(nombre=nombre)
    documento = ficha.a_json()
    validar(documento)
    repo.guardar_ficha(documento)
    return documento


def exportar(id_ficha: str, destino: str | Path, repo: RepositorioFichas) -> Path:
    documento = repo.obtener_ficha(id_ficha)
    if not documento:
        raise ValueError("No se encontró la ficha")
    documento["ficha"]["catalogosSnapshot"] = repo.snapshot_catalogos()
    return exportar_ficha(documento, destino)


def validar_importacion(origen: str | Path) -> ValidationSummary:
    """Previsualiza una importación validada; no modifica la base local."""
    return validar_paquete(origen)


def importar(origen: str | Path, repo: RepositorioFichas, *, confirmada: bool = False) -> dict:
    """Guarda solo después de la confirmación explícita de la capa de presentación."""
    if not confirmada:
        raise ValueError("Confirme primero el resumen de la ficha antes de importarla")
    resumen = validar_paquete(origen)
    repo.guardar_ficha(resumen.document)
    return resumen.document
