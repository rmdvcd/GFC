"""Comandos no gráficos para pruebas y generación del paquete de ejemplo."""
import argparse
import json
from pathlib import Path
from .dominio import Categoria, FichaCosto, Importe, Moneda, PartidaCosto
from .intercambio import exportar_ficha, importar_ficha, validar


def ejemplo() -> dict:
    ficha = FichaCosto(nombre="Producto de ejemplo", descripcion="Datos demostrativos; no constituyen una ficha normativa oficial.")
    ficha.partidas.append(PartidaCosto(categoria=Categoria.MATERIAS_PRIMAS_MATERIALES,
        descripcion="Insumo de demostración", cantidad=2, unidadMedida="unidad", costoUnitario=Importe(125.5, Moneda.CUP)))
    return ficha.a_json()


def main():
    parser = argparse.ArgumentParser(prog="fichacosto")
    sub = parser.add_subparsers(dest="comando", required=True)
    crear = sub.add_parser("crear-ejemplo"); crear.add_argument("destino", type=Path)
    importar = sub.add_parser("validar"); importar.add_argument("archivo", type=Path)
    args = parser.parse_args()
    if args.comando == "crear-ejemplo":
        exportar_ficha(ejemplo(), args.destino)
        print(f"Paquete creado: {args.destino}")
    else:
        doc = importar_ficha(args.archivo)
        print(f"Válido: {doc['ficha']['nombre']} ({doc['schemaVersion']})")

if __name__ == "__main__":
    main()
