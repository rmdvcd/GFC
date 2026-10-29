"""Modelos y reglas de dominio alineados con shared/ficha_costo_v1.schema.json."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any
from uuid import uuid4


class Moneda(str, Enum):
    CUP = "CUP"
    MLC = "MLC"


class EstadoFicha(str, Enum):
    BORRADOR = "borrador"
    FINALIZADA = "finalizada"


class Categoria(str, Enum):
    MATERIAS_PRIMAS_MATERIALES = "materias_primas_materiales"
    FUERZA_TRABAJO_DIRECTA = "fuerza_trabajo_directa"
    OTROS_GASTOS_DIRECTOS = "otros_gastos_directos"
    GASTOS_INDIRECTOS_PRODUCCION = "gastos_indirectos_produccion"


CATEGORIAS = tuple(Categoria)


def ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _decimal(valor: float | int | str | Decimal) -> Decimal:
    resultado = Decimal(str(valor))
    if not resultado.is_finite() or resultado < 0:
        raise ValueError("Los importes y cantidades deben ser números finitos no negativos")
    return resultado


def _redondear(valor: Decimal) -> float:
    return float(valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


@dataclass
class Importe:
    valor: float
    moneda: Moneda

    def json(self) -> dict[str, Any]:
        return {"valor": _redondear(_decimal(self.valor)), "moneda": self.moneda.value}


@dataclass
class PartidaCosto:
    categoria: Categoria
    descripcion: str
    cantidad: float
    unidadMedida: str
    costoUnitario: Importe
    id: str = field(default_factory=lambda: str(uuid4()))
    insumoId: str | None = None
    observaciones: str = ""

    @property
    def subtotal(self) -> Importe:
        return Importe(_redondear(_decimal(self.cantidad) * _decimal(self.costoUnitario.valor)), self.costoUnitario.moneda)

    def json(self) -> dict[str, Any]:
        return {
            "id": self.id, "categoria": self.categoria.value, "descripcion": self.descripcion,
            "insumoId": self.insumoId, "cantidad": float(_decimal(self.cantidad)),
            "unidadMedida": self.unidadMedida, "costoUnitario": self.costoUnitario.json(),
            "subtotal": self.subtotal.json(), "observaciones": self.observaciones,
        }


@dataclass
class Coeficientes:
    coeficienteIndirecto: float | None = None
    margenGanancia: float | None = None
    unidadCoeficiente: str = "porcentaje"

    def json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FichaCosto:
    nombre: str
    monedaBase: Moneda = Moneda.CUP
    id: str = field(default_factory=lambda: str(uuid4()))
    descripcion: str = ""
    fechaCreacion: str = field(default_factory=ahora_iso)
    fechaActualizacion: str = field(default_factory=ahora_iso)
    estado: EstadoFicha = EstadoFicha.BORRADOR
    partidas: list[PartidaCosto] = field(default_factory=list)
    coeficientes: Coeficientes = field(default_factory=Coeficientes)
    catalogosSnapshot: dict[str, Any] = field(default_factory=lambda: {"insumos": [], "tarifasSalario": []})
    extensionData: dict[str, Any] = field(default_factory=dict)

    def totales(self) -> dict[str, Any]:
        # Keep independent ledgers: CUP and MLC are never silently converted or combined.
        sums = {categoria.value: {moneda.value: Decimal("0") for moneda in Moneda} for categoria in CATEGORIAS}
        for partida in self.partidas:
            moneda = partida.costoUnitario.moneda.value
            sums[partida.categoria.value][moneda] += _decimal(partida.subtotal.valor)
        por_categoria = {key: {moneda: _redondear(value) for moneda, value in por_moneda.items()} for key, por_moneda in sums.items()}
        total = {moneda.value: _redondear(sum((sums[c.value][moneda.value] for c in CATEGORIAS), Decimal("0"))) for moneda in Moneda}
        precio = None
        if self.coeficientes.margenGanancia is not None:
            margen = _decimal(self.coeficientes.margenGanancia)
            if self.coeficientes.unidadCoeficiente == "porcentaje":
                precio = {moneda: _redondear(Decimal(str(valor)) * (Decimal("1") + margen / Decimal("100"))) for moneda, valor in total.items()}
            else:
                precio = {moneda: _redondear(Decimal(str(valor)) * margen) for moneda, valor in total.items()}
        return {"porCategoria": por_categoria, "costoTotal": total, "precioCalculado": precio}

    def a_json(self) -> dict[str, Any]:
        self.fechaActualizacion = ahora_iso()
        return {"schemaVersion": 1, "ficha": {
            "id": self.id, "nombre": self.nombre, "descripcion": self.descripcion,
            "fechaCreacion": self.fechaCreacion, "fechaActualizacion": self.fechaActualizacion,
            "estado": self.estado.value, "monedaBase": self.monedaBase.value,
            "partidas": [p.json() for p in self.partidas], "catalogosSnapshot": self.catalogosSnapshot,
            "coeficientes": self.coeficientes.json(), "totales": self.totales(), "extensionData": self.extensionData,
        }}

    @classmethod
    def desde_json(cls, documento: dict[str, Any]) -> "FichaCosto":
        if documento.get("schemaVersion") != 1:
            raise ValueError(f"Versión de esquema no soportada: {documento.get('schemaVersion')}")
        f = documento["ficha"]
        partidas = [PartidaCosto(
            id=p["id"], categoria=Categoria(p["categoria"]), descripcion=p["descripcion"],
            insumoId=p.get("insumoId"), cantidad=p["cantidad"], unidadMedida=p["unidadMedida"],
            costoUnitario=Importe(p["costoUnitario"]["valor"], Moneda(p["costoUnitario"]["moneda"])),
            observaciones=p.get("observaciones", "")) for p in f["partidas"]]
        return cls(nombre=f["nombre"], id=f["id"], descripcion=f.get("descripcion", ""),
                   fechaCreacion=f["fechaCreacion"], fechaActualizacion=f["fechaActualizacion"],
                   estado=EstadoFicha(f["estado"]), monedaBase=Moneda(f["monedaBase"]), partidas=partidas,
                   coeficientes=Coeficientes(**f.get("coeficientes", {})), catalogosSnapshot=f.get("catalogosSnapshot", {"insumos": [], "tarifasSalario": []}), extensionData=f.get("extensionData", {}))


@dataclass
class Insumo:
    nombre: str
    unidadMedida: str
    costoUnitario: Importe
    id: str = field(default_factory=lambda: str(uuid4()))


@dataclass
class TarifaSalario:
    cargo: str
    tarifa: Importe
    unidadTarifa: str  # e.g. hora or unidad; configured by the user
    id: str = field(default_factory=lambda: str(uuid4()))
