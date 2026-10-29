from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class EstadoLicencia(str, Enum):
    VALIDA = "VALIDA"
    EXPIRADA = "EXPIRADA"
    FINGERPRINT_NO_COINCIDE = "FINGERPRINT_NO_COINCIDE"
    FIRMA_INVALIDA = "FIRMA_INVALIDA"
    SCHEMA_INVALIDO = "SCHEMA_INVALIDO"
    NO_INSTALADA = "NO_INSTALADA"


@dataclass(frozen=True)
class ResultadoLicencia:
    estado: EstadoLicencia
    payload: dict[str, Any] | None = None
    motivoRechazo: str | None = None
    advertencia: str | None = None

    @property
    def valida(self) -> bool:
        return self.estado is EstadoLicencia.VALIDA


@dataclass(frozen=True)
class EstadoLicenciaActual:
    estado: EstadoLicencia
    tipo: str | None = None
    features: tuple[str, ...] = ()
    fichasRestantes: int | None = None
    diasHastaExpiracion: int | None = None
    payload: dict[str, Any] | None = None
    motivoRechazo: str | None = None
    advertencia: str | None = None

    @property
    def permite_lectura(self) -> bool:
        # Existing records remain available under every license state.
        return True

    @property
    def permite_pdf(self) -> bool:
        # PDF remains available in every state; unlicensed/expired output is watermarked.
        return True

    @property
    def pdf_con_marca_agua(self) -> bool:
        return self.estado is not EstadoLicencia.VALIDA or "pdf" not in self.features
