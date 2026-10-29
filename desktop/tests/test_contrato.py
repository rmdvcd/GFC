import json
import tempfile
import unittest
from pathlib import Path
from fichacosto.cli import ejemplo
from fichacosto.dominio import Categoria, FichaCosto, Importe, Moneda, PartidaCosto
from fichacosto.intercambio import exportar_ficha, importar_ficha, validar


class ContratoTest(unittest.TestCase):
    def test_documento_ejemplo_valido(self):
        validar(ejemplo())

    def test_zip_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.ficha148"
            original = ejemplo()
            exportar_ficha(original, path)
            self.assertEqual(importar_ficha(path), original)

    def test_calculo_categoria_y_moneda(self):
        f = FichaCosto("Prueba")
        f.partidas = [
            PartidaCosto(Categoria.MATERIAS_PRIMAS_MATERIALES, "A", 2, "kg", Importe(3.25, Moneda.CUP)),
            PartidaCosto(Categoria.OTROS_GASTOS_DIRECTOS, "B", 1, "u", Importe(900, Moneda.MLC)),
        ]
        self.assertEqual(f.totales()["costoTotal"], {"CUP": 6.5, "MLC": 900.0})

    def test_margen_configurable_es_estimacion_y_monedas_separadas(self):
        f = FichaCosto("Margen")
        f.partidas = [PartidaCosto(Categoria.MATERIAS_PRIMAS_MATERIALES, "CUP", 1, "u", Importe(100, Moneda.CUP)), PartidaCosto(Categoria.OTROS_GASTOS_DIRECTOS, "MLC", 1, "u", Importe(5, Moneda.MLC))]
        f.coeficientes.margenGanancia = 20
        self.assertEqual(f.totales()["costoTotal"], {"CUP": 100.0, "MLC": 5.0})
        self.assertEqual(f.totales()["precioCalculado"], {"CUP": 120.0, "MLC": 6.0})

    def test_rechaza_version_no_soportada(self):
        doc = ejemplo(); doc["schemaVersion"] = 99
        with self.assertRaises(Exception): validar(doc)

if __name__ == "__main__": unittest.main()
