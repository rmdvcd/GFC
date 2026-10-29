"""Exportación local a CSV, Excel y PDF (sin dependencia de red)."""
from pathlib import Path
from .dominio import FichaCosto


def exportar_csv(ficha: FichaCosto, destino: str | Path) -> Path:
    import csv
    ruta = Path(destino)
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        writer = csv.writer(archivo, delimiter=";")
        writer.writerow(["id", "categoria", "descripcion", "cantidad", "unidadMedida", "costoUnitario", "moneda", "subtotal"])
        for p in ficha.partidas:
            writer.writerow([p.id, p.categoria.value, p.descripcion, p.cantidad, p.unidadMedida,
                             p.costoUnitario.valor, p.costoUnitario.moneda.value, p.subtotal.valor])
    return ruta


def exportar_excel(ficha: FichaCosto, destino: str | Path) -> Path:
    import pandas as pd
    ruta = Path(destino)
    filas = [{"categoria": p.categoria.value, "descripcion": p.descripcion, "cantidad": p.cantidad,
              "unidadMedida": p.unidadMedida, "costoUnitario": p.costoUnitario.valor,
              "moneda": p.costoUnitario.moneda.value, "subtotal": p.subtotal.valor} for p in ficha.partidas]
    with pd.ExcelWriter(ruta, engine="openpyxl") as writer:
        pd.DataFrame(filas, columns=["categoria", "descripcion", "cantidad", "unidadMedida", "costoUnitario", "moneda", "subtotal"]).to_excel(writer, index=False, sheet_name="Partidas")
        totales = ficha.totales()
        pd.DataFrame([{"categoria": k, "CUP": v["CUP"], "MLC": v["MLC"]} for k, v in totales["porCategoria"].items()]).to_excel(writer, index=False, sheet_name="Totales")
    return ruta


def generar_pdf_ficha(ficha: FichaCosto, marca_agua: bool = False) -> bytes:
    """Genera el PDF referencial y opcionalmente aplica la marca de agua de licencia."""
    from .pdf_ficha import generar_pdf_ficha as _generar
    return _generar(ficha, marca_agua=marca_agua)


def exportar_pdf(ficha: FichaCosto, destino: str | Path, marca_agua: bool = False) -> Path:
    ruta = Path(destino)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(generar_pdf_ficha(ficha, marca_agua=marca_agua))
    return ruta
